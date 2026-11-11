"""Unit tests for the GitHub client pagination, pipeline normalisers and deterministic scoring.

These are pure/offline — no live server or Mongo needed.
"""

import pytest

from services import github_client as gh
from services import pipeline
from services.scoring import score_contribution


def _page(n: int, tag: str = "x") -> list[dict]:
    return [{"number": i, "tag": tag} for i in range(n)]


class FakeClient(gh.GitHubClient):
    """GitHubClient with _get stubbed from a {path: [pages]} fixture."""

    def __init__(self, pages: dict):
        self._pages = pages
        self.calls: list[tuple[str, dict]] = []

    async def _get(self, path, params=None):
        self.calls.append((path, params or {}))
        page = (params or {}).get("page", 1)
        key = path
        seq = self._pages.get(key)
        if seq is None:
            return []
        idx = page - 1
        return seq[idx] if idx < len(seq) else []


@pytest.mark.asyncio
async def test_paginate_collects_all_pages():
    c = FakeClient({"/repos/o/r/pulls": [_page(100, "a"), _page(30, "b")]})
    items, truncated = await c._paginate("/repos/o/r/pulls", {})
    assert len(items) == 130
    assert truncated is False
    assert [p for p, _ in c.calls] == ["/repos/o/r/pulls", "/repos/o/r/pulls"]


@pytest.mark.asyncio
async def test_paginate_stops_on_short_page():
    c = FakeClient({"/x": [_page(100), _page(100), _page(5)]})
    items, truncated = await c._paginate("/x", {})
    assert len(items) == 205
    assert truncated is False
    assert len(c.calls) == 3


@pytest.mark.asyncio
async def test_paginate_reports_truncation_at_cap():
    c = FakeClient({"/x": [_page(100) for _ in range(gh.MAX_PAGES + 1)]})
    items, truncated = await c._paginate("/x", {})
    assert len(items) == 100 * gh.MAX_PAGES
    assert truncated is True


@pytest.mark.asyncio
async def test_fetch_prs_filters_to_author():
    mine = {"number": 1, "user": {"login": "me"}}
    theirs = {"number": 2, "user": {"login": "other"}}
    c = FakeClient({"/repos/o/r/pulls": [[mine, theirs]]})
    prs, _ = await c.fetch_prs("o/r", "me")
    assert prs == [mine]


@pytest.mark.asyncio
async def test_summarize_reviews_counts_states():
    reviews = [
        {"state": "APPROVED", "user": {"login": "a"}},
        {"state": "CHANGES_REQUESTED", "user": {"login": "b"}},
        {"state": "COMMENTED", "user": {"login": "a"}},
        {"state": "APPROVED", "user": {"login": "c"}},
    ]
    s = gh.GitHubClient.summarize_reviews(reviews)
    assert s["review_count"] == 4
    assert s["approvals"] == 2
    assert s["change_requests"] == 1
    assert s["reviewers"] == 3


def test_norm_pr_captures_collaboration_evidence():
    pr = {
        "number": 7, "title": "Fix thing", "body": "b", "html_url": "u",
        "state": "closed", "merged_at": "2024-01-02T00:00:00Z", "draft": False,
        "author_association": "FIRST_TIME_CONTRIBUTOR",
        "additions": 100, "deletions": 20, "comments": 3, "changed_files": 5,
        "commits": 4, "labels": [], "user": {"login": "me"},
    }
    stats = {"review_count": 3, "approvals": 1, "change_requests": 1, "reviewers": 2}
    item = pipeline.norm_pr(pr, "other-org/repo", ["Python"], "me", stats)
    assert item["state"] == "merged"
    assert item["merged"] is True
    assert item["is_own_repo"] is False
    assert item["repo_owner"] == "other-org"
    assert item["review_count"] == 3 and item["change_requests"] == 1
    assert item["author_association"] == "FIRST_TIME_CONTRIBUTOR"


def test_norm_pr_own_repo_flag():
    pr = {"number": 1, "title": "t", "state": "open", "user": {"login": "me"}}
    item = pipeline.norm_pr(pr, "me/myrepo", [], "me")
    assert item["is_own_repo"] is True


def test_score_merged_external_pr_outranks_own_closed():
    external_merged = {
        "kind": "pr", "state": "merged", "merged": True, "is_own_repo": False,
        "additions": 400, "deletions": 60, "changed_files": 12, "commits_count": 6,
        "review_count": 4, "approvals": 2, "change_requests": 2, "comments": 8,
        "complexity": "High",
    }
    own_closed = {
        "kind": "pr", "state": "closed", "is_own_repo": True,
        "additions": 20, "deletions": 5, "comments": 0, "complexity": "Low",
    }
    a = score_contribution(external_merged)
    b = score_contribution(own_closed)
    assert a["impact_score"] > b["impact_score"]
    assert set(a["dimensions"]) == {"substance", "collaboration", "acceptance", "context", "problem_complexity"}
    # determinism
    assert score_contribution(external_merged) == a


def test_score_review_evidence():
    approved = score_contribution({"kind": "review", "state": "APPROVED", "is_own_repo": False})
    commented = score_contribution({"kind": "review", "state": "COMMENTED", "is_own_repo": False})
    assert approved["dimensions"]["collaboration"] > commented["dimensions"]["collaboration"]
