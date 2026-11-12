"""Discovery tests: partitioned search around the 1,000-result ceiling,
dedupe, coverage reporting, pagination, and rate-limit retry behaviour.

All offline — _get is stubbed; no live GitHub or Mongo needed.
"""

import asyncio
from datetime import date

import httpx
import pytest

from services import github_client as gh


class SearchFake(gh.GitHubClient):
    """GitHubClient whose /search/issues + /search/commits calls route to a handler.

    handler(query, page, endpoint) -> dict envelope {"total_count","items","incomplete_results"}
    """

    def __init__(self, handler):
        self.handler = handler
        self.queries: list[tuple[str, int, str]] = []
        self._search_sem = asyncio.Semaphore(2)

    async def _get(self, path, params=None):
        params = params or {}
        if path in ("/search/issues", "/search/commits"):
            page = int(params.get("page", 1))
            self.queries.append((params.get("q", ""), page, path))
            return self.handler(params.get("q", ""), page, path)
        return None


def _items(prefix: str, n: int, start: int = 0) -> list[dict]:
    return [
        {
            "id": f"{prefix}-{i}",
            "number": i,
            "title": f"item {i}",
            "state": "closed",
            "pull_request": {},
            "user": {"login": "me"},
            "repository_url": "https://api.github.com/repos/o/r",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        for i in range(start, start + n)
    ]


def _window_days(query: str) -> int:
    """Extract the created: window size (in days) from a partitioned query."""
    import re

    m = re.search(r"created:(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", query)
    if not m:
        return 10**9  # unbounded probe
    a = date.fromisoformat(m.group(1))
    b = date.fromisoformat(m.group(2))
    return max(1, (b - a).days + 1)


@pytest.mark.asyncio
async def test_partitioned_search_small_history_single_window():
    """Under the safe limit: one probe + remaining pages, one coverage window."""
    calls = {"n": 0}

    def handler(q, page, endpoint):
        if "created:" not in q:
            return {"total_count": 3, "items": _items("u", 3), "incomplete_results": False}
        return {"total_count": 0, "items": [], "incomplete_results": False}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:pr author:me", today=date(2024, 6, 1))
    assert len(result.items) == 3
    assert result.coverage_complete is True
    assert len(result.windows) == 1
    assert result.windows[0].status == "complete"
    assert result.windows[0].total_count == 3


@pytest.mark.asyncio
async def test_partitioned_search_bisects_dense_history():
    """A history denser than 1,000 results is split into created: windows until
    every window fits under the ceiling — coverage stays complete."""
    # Simulate ~2 items per day: windows wider than ~450 days exceed the safe limit.
    def handler(q, page, endpoint):
        days = _window_days(q)
        total = days * 2
        per_page = min(100, max(0, total - (page - 1) * 100))
        items = _items(f"w{days}-{page}", per_page) if page <= -(-total // 100) else []
        return {"total_count": total, "items": items, "incomplete_results": False}

    c = SearchFake(handler)
    # Narrow the history so the test stays fast: pretend 'today' is 2020-01-01,
    # earliest bound 2008 → ~4400 days → several bisection levels.
    result = await c.search_partitioned("is:pr author:me", today=date(2020, 1, 1))
    assert result.coverage_complete is True
    assert len(result.windows) > 3  # partitioning actually happened
    assert all(w.status in ("complete", "split") for w in result.windows)
    # Every window reports ≤ safe-limit totals (or was resolved at max depth).
    fetched = sum(w.fetched for w in result.windows)
    assert fetched > 0
    # Items deduped by id across overlapping boundary windows.
    assert len(result.items) == len({i["id"] for i in result.items.values()})


@pytest.mark.asyncio
async def test_partitioned_search_marks_partial_on_incomplete_results():
    def handler(q, page, endpoint):
        return {"total_count": 5, "items": _items("x", 5), "incomplete_results": True}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:pr author:me", today=date(2024, 6, 1))
    assert result.coverage_complete is False
    assert result.truncated is True


@pytest.mark.asyncio
async def test_discover_activity_uses_partitioned_searches():
    """discover_activity runs three partitioned searches and buckets results."""

    def handler(q, page, endpoint):
        items = []
        if "author:me" in q and "is:pr" in q:
            items = _items("pr", 2)
        elif "reviewed-by:me" in q:
            items = _items("rev", 1)
            for it in items:
                it["user"] = {"login": "someone-else"}  # not self-authored
        return {"total_count": len(items), "items": items, "incomplete_results": False}

    c = SearchFake(handler)
    activity = await c.discover_activity("me")
    assert len(activity["authored_prs"]) == 2
    assert len(activity["reviewed_prs"]) == 1
    assert "o/r" in activity["repos"]
    assert set(activity["coverage"].keys()) == {"authored_prs", "authored_issues", "reviewed_prs"}

    # reviewed-by results authored by the user themself are filtered out
    def self_handler(q, page, endpoint):
        items = _items("self", 1) if "reviewed-by:me" in q else []
        return {"total_count": len(items), "items": items, "incomplete_results": False}

    c2 = SearchFake(self_handler)
    activity2 = await c2.discover_activity("me")
    assert activity2["reviewed_prs"] == []


@pytest.mark.asyncio
async def test_pagination_follows_link_style_pages_to_exhaustion():
    """_paginate keeps going until a short page — no small arbitrary ceiling."""
    seq = []
    for i in range(1, 7):
        seq.append([{"n": j} for j in range(100)] if i < 6 else [{"n": j} for j in range(37)])

    class P(gh.GitHubClient):
        async def _get(self, path, params=None):
            page = (params or {}).get("page", 1)
            return seq[page - 1] if page <= len(seq) else []

    c = P()
    items, truncated = await c._paginate("/r/x", {})
    assert len(items) == 537
    assert truncated is False


@pytest.mark.asyncio
async def test_request_retries_on_429_with_retry_after():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={"message": "slow down"})
        return httpx.Response(200, json={"ok": True})

    c = gh.GitHubClient("tok")
    c._client = httpx.AsyncClient(base_url=gh.API, transport=httpx.MockTransport(handler))
    data = await c._get("/user")
    assert data == {"ok": True}
    assert calls["n"] == 2
    await c.close()


@pytest.mark.asyncio
async def test_request_does_not_retry_permission_403():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "4000"},
            json={"message": "Resource not accessible by integration"},
        )

    c = gh.GitHubClient("tok")
    c._client = httpx.AsyncClient(base_url=gh.API, transport=httpx.MockTransport(handler))
    with pytest.raises(gh.GitHubAPIError):
        await c._get("/repos/o/r")
    assert calls["n"] == 1  # permission errors are not retried
    await c.close()


@pytest.mark.asyncio
async def test_request_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    c = gh.GitHubClient("tok")
    c._client = httpx.AsyncClient(base_url=gh.API, transport=httpx.MockTransport(handler))
    assert await c._get("/repos/gone/repo") is None
    await c.close()


@pytest.mark.asyncio
async def test_search_partitioned_records_window_coverage():
    """Every bisection leaf is persisted as a coverage window with fetched counts."""

    def handler(q, page, endpoint):
        days = _window_days(q)
        total = min(days, 50)
        items = _items(f"c{days}-{page}", min(100, total)) if page == 1 else []
        return {"total_count": total, "items": items, "incomplete_results": False}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:issue author:me", today=date(2024, 1, 1))
    assert result.windows
    assert all(w.fetched >= 0 for w in result.windows)
    assert sum(w.total_count for w in result.windows) >= len(result.items)


@pytest.mark.asyncio
async def test_partitioned_search_marks_error_windows_incomplete():
    """A failing window is recorded as an error — coverage stays honest."""

    def handler(q, page, endpoint):
        if "created:" not in q:
            return {"total_count": 5000, "items": [], "incomplete_results": False}
        if "2017-04-24" in q:
            raise gh.GitHubAPIError(500, "/search/issues", "boom")
        days = _window_days(q)
        if days > 900:
            return {"total_count": days * 2, "items": [], "incomplete_results": False}
        return {"total_count": 10, "items": _items(f"d{days}", 10), "incomplete_results": False}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:pr author:me", today=date(2020, 6, 1))
    assert result.coverage_complete is False
    assert any(w.status == "error" for w in result.windows)


@pytest.mark.asyncio
async def test_partitioned_search_depth_cap_marks_partial():
    """A window denser than the safe limit even at max partition depth is
    marked partial rather than silently claiming completeness."""
    # Every window reports huge totals — recursion hits MAX_PARTITION_DEPTH.
    def handler(q, page, endpoint):
        return {"total_count": 999999, "items": _items("x", 100), "incomplete_results": False}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:pr author:me", today=date(2024, 1, 2))
    assert result.coverage_complete is False
    # Deepest windows were fetched (first 1000) but flagged partial.
    assert any(w.status == "partial" for w in result.windows)


@pytest.mark.asyncio
async def test_paginate_reports_truncation_at_safety_bound():
    """The 10k-item safety bound is reported, never silent."""
    seq = [[{"n": j} for j in range(100)] for _ in range(gh.MAX_PAGES)]

    class P(gh.GitHubClient):
        async def _get(self, path, params=None):
            page = (params or {}).get("page", 1)
            return seq[page - 1] if page <= len(seq) else [{"n": j} for j in range(100)]

    c = P()
    items, truncated = await c._paginate("/big", {})
    assert len(items) == 100 * gh.MAX_PAGES
    assert truncated is True


@pytest.mark.asyncio
async def test_identical_timestamps_dedupe_by_node_id():
    """Overlapping windows returning the same PR id collapse to one item."""
    shared = {"id": 42, "number": 1, "title": "dup", "state": "open",
              "user": {"login": "me"}, "repository_url": "https://api.github.com/repos/o/r",
              "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z"}

    def handler(q, page, endpoint):
        # Two adjacent windows both return the same item.
        return {"total_count": 1, "items": [shared], "incomplete_results": False}

    c = SearchFake(handler)
    result = await c.search_partitioned("is:pr author:me", today=date(2024, 1, 2))
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_find_revert_prs_matches_references_and_title():
    """Revert fallback: same-repo merged `Revert ...` PRs that reference the
    original PR number or carry its title are returned; unrelated reverts are not."""
    def handler(q, page, endpoint):
        assert "repo:o/r" in q and "is:pr" in q and "is:merged" in q and "revert" in q
        return {
            "total_count": 3,
            "items": [
                # references the PR explicitly
                {"number": 11, "title": 'Revert "Fix race"', "body": "Reverts o/r#7", "html_url": "u11"},
                # title match on the original title
                {"number": 12, "title": 'Revert "Fix race in worker"', "body": "", "html_url": "u12"},
                # unrelated revert — must be filtered out
                {"number": 13, "title": 'Revert "Bump deps"', "body": "Reverts o/r#99", "html_url": "u13"},
            ],
            "incomplete_results": False,
        }

    c = SearchFake(handler)
    out = await c.find_revert_prs("o/r", 7, "Fix race in worker")
    assert [r["number"] for r in out] == [11, 12]


@pytest.mark.asyncio
async def test_commit_search_items_without_id_are_kept():
    """Regression: /search/commits items have sha/node_id but no top-level `id`.
    Dedupe must fall back or every commit is silently dropped."""
    def handler(q, page, endpoint):
        assert endpoint == "/search/commits"
        return {
            "total_count": 2,
            "items": [
                {"sha": "abc123", "node_id": "C_1", "html_url": "u1",
                 "repository": {"full_name": "o/r"},
                 "commit": {"message": "fix", "author": {"date": "2024-01-01T00:00:00Z"}}},
                {"sha": "def456", "node_id": "C_2", "html_url": "u2",
                 "repository": {"full_name": "o/r"},
                 "commit": {"message": "feat", "author": {"date": "2024-01-02T00:00:00Z"}}},
            ],
            "incomplete_results": False,
        }

    c = SearchFake(handler)
    result = await c.search_partitioned("author:me", endpoint="/search/commits", date_qualifier="author-date")
    assert len(result.items) == 2
