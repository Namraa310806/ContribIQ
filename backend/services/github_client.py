"""Rate-limit aware GitHub REST + Search fetcher used by the analysis pipeline.

Discovery model (PR-centric):
- Authored PRs are discovered through the Search API (`is:pr author:<login>`),
  NOT through per-repo `GET /repos/{o}/{r}/pulls` — the pulls endpoint only
  exposes a bounded recent window and silently misses older PRs.
- The Search API caps any single query at 1,000 results. `search_partitioned`
  works around that by recursively bisecting `created:` date windows whenever a
  window reports more than SEARCH_SAFE_LIMIT matches, and records per-window
  coverage so partial history is never reported as complete.
- Reviews the user *wrote* on other people's PRs are discovered separately via
  `is:pr reviewed-by:<login>` — review participation is secondary evidence and
  is never conflated with authored contributions.
- Every list endpoint paginates to exhaustion (bounded only by a high safety
  ceiling that is reported as truncation, never silently).
- Retries: exponential backoff on 403/429/5xx, honouring Retry-After and the
  x-ratelimit-reset headers; permission errors (403 with quota remaining) are
  not retried.
"""

import asyncio
import logging
import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API = "https://api.github.com"
PER_PAGE = 100
# Search returns at most 1,000 items per query. We partition before hitting it.
SEARCH_RESULT_CEILING = 1000
SEARCH_SAFE_LIMIT = 900  # partition when a window could exceed what one query returns
MAX_PAGES = 100  # list endpoints: 10k items safety bound — truncation is reported
MAX_RETRIES = 4
MAX_PARTITION_DEPTH = 15
# Never bisect below a fortnight: a >900-result fortnight for one author is
# beyond what search can resolve — mark it partial rather than recurse forever.
MIN_SPLIT_SPAN_DAYS = 14
REVIEW_FETCH_CONCURRENCY = 4
SEARCH_CONCURRENCY = 2  # search has a much lower rate limit than core REST
EARLIEST_ACTIVITY = date(2008, 1, 1)  # GitHub launch; lower bound for partitioning


class GitHubAPIError(Exception):
    """Non-retryable GitHub API failure (permission, validation, etc.)."""

    def __init__(self, status: int, path: str, detail: str = ""):
        super().__init__(f"GitHub API {status} on {path}: {detail[:200]}")
        self.status = status
        self.path = path


class SearchWindow:
    """One `created:` partition of a search query and its coverage outcome."""

    def __init__(self, start: date, end: date):
        self.start = start
        self.end = end
        self.total_count = 0
        self.fetched = 0
        self.status = "complete"  # complete | partial | error
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "window_start": self.start.isoformat(),
            "window_end": self.end.isoformat(),
            "total_count": self.total_count,
            "fetched": self.fetched,
            "status": self.status,
            "error": self.error,
        }


class PartitionedSearchResult:
    def __init__(self) -> None:
        self.items: dict[int, dict] = {}  # deduped by GitHub node id
        self.windows: list[SearchWindow] = []
        self.incomplete_results = False

    @property
    def truncated(self) -> bool:
        # "split" windows are internal bisection nodes — their coverage is the
        # union of their children, so they don't count for or against completeness.
        return any(w.status in ("partial", "error") for w in self.windows) or self.incomplete_results

    @property
    def coverage_complete(self) -> bool:
        return not self.truncated

    def to_list(self) -> list[dict]:
        # Most recently updated first — matches the previous discovery ordering.
        return sorted(
            self.items.values(),
            key=lambda i: i.get("updated_at") or i.get("created_at") or "",
            reverse=True,
        )


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_SERVER_TOKEN") or None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.AsyncClient(base_url=API, timeout=30, headers=headers)
        self._search_sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def close(self) -> None:
        await self._client.aclose()

    # ---------- low-level request with retry/backoff ----------

    async def _request(self, method: str, path: str, params: Optional[dict] = None):
        """One logical request with bounded retries on transient failures."""
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, params=params or {})
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(min(30, 2**attempt) + random.random())
                    continue
                raise

            remaining = resp.headers.get("x-ratelimit-remaining")
            reset = resp.headers.get("x-ratelimit-reset")
            if remaining is not None and remaining.isdigit() and int(remaining) <= 5 and reset:
                wait = max(1, min(90, int(reset) - int(datetime.now(timezone.utc).timestamp()) + 1))
                logger.warning("GitHub core rate limit low — sleeping %ss", wait)
                await asyncio.sleep(wait)

            if resp.status_code in (403, 429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                # 403 with quota remaining is a permission problem, not throttling.
                if resp.status_code == 403 and remaining is not None and remaining.isdigit() and int(remaining) > 0:
                    detail = ""
                    try:
                        detail = (resp.json() or {}).get("message", "")
                    except Exception:
                        pass
                    if "rate limit" not in detail.lower():
                        raise GitHubAPIError(403, path, detail)
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    wait = min(120, int(retry_after))
                else:
                    # Secondary rate limits ask for exponential backoff; honour it.
                    wait = min(120, (2**attempt) * 5 + random.random() * 2)
                logger.warning("GitHub %s on %s — retry %s in %.1fs", resp.status_code, path, attempt + 1, wait)
                await asyncio.sleep(wait)
                continue

            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = (resp.json() or {}).get("message", "")
                except Exception:
                    pass
                raise GitHubAPIError(resp.status_code, path, detail or resp.text[:200])
            return resp.json() if resp.content else None
        raise last_exc or GitHubAPIError(0, path, "retries exhausted")

    async def _get(self, path: str, params: Optional[dict] = None):
        return await self._request("GET", path, params)

    async def _paginate(self, path: str, params: Optional[dict] = None, envelope: bool = False) -> tuple[list, bool]:
        """Fetch every page of a list endpoint. Returns (items, truncated).

        `envelope=True` for endpoints that wrap results in {"total_count","items"}
        (e.g. check-runs) instead of returning a bare array.
        """
        items: list = []
        truncated = False
        for page in range(1, MAX_PAGES + 1):
            data = await self._get(path, {**(params or {}), "page": page, "per_page": PER_PAGE})
            batch = (data or {}).get("items") if envelope else data
            if not batch:
                break
            items.extend(batch)
            if len(batch) < PER_PAGE:
                break
            if page == MAX_PAGES:
                truncated = True
        return items, truncated

    # ---------- search ----------

    async def _search_page(self, query: str, page: int, endpoint: str = "/search/issues") -> dict:
        async with self._search_sem:
            data = await self._get(
                endpoint,
                {
                    "q": query,
                    "sort": "updated",
                    "order": "desc",
                    "page": page,
                    "per_page": PER_PAGE,
                },
            )
        return data or {}

    async def _search_window_pages(
        self, query: str, total_count: int, window: SearchWindow, result: PartitionedSearchResult, endpoint: str
    ) -> None:
        """Fetch every page of one already-sized window."""
        pages = max(1, min(MAX_PAGES, -(-min(total_count, SEARCH_RESULT_CEILING) // PER_PAGE)))
        for page in range(1, pages + 1):
            data = await self._search_page(query, page, endpoint)
            batch = (data or {}).get("items") or []
            if (data or {}).get("incomplete_results"):
                result.incomplete_results = True
                window.status = "partial"
            for item in batch:
                # Commit-search items have no top-level `id` — fall back through
                # node_id/sha or every commit is silently dropped at dedupe.
                item_id = item.get("id") or item.get("node_id") or item.get("sha")
                if item_id is not None:
                    result.items[item_id] = item
            window.fetched += len(batch)
            if len(batch) < PER_PAGE:
                break
            if page == MAX_PAGES:
                window.status = "partial"
        # A window that still exceeds what one query can return is partial —
        # we fetched the 1,000-item ceiling, not the whole window.
        if window.fetched < min(total_count, SEARCH_RESULT_CEILING) or total_count > SEARCH_RESULT_CEILING:
            if window.status == "complete":
                window.status = "partial"

    async def _collect_window(
        self, base_query: str, start: date, end: date, result: PartitionedSearchResult, depth: int = 0, endpoint: str = "/search/issues", date_qualifier: str = "created"
    ) -> None:
        """Recursively bisect a created: window until each holds ≤ SEARCH_SAFE_LIMIT hits."""
        window = SearchWindow(start, end)
        result.windows.append(window)
        query = f"{base_query} {date_qualifier}:{start.isoformat()}..{end.isoformat()}"
        try:
            first = await self._search_page(query, 1, endpoint)
        except GitHubAPIError as exc:
            window.status = "error"
            window.error = str(exc)[:200]
            logger.warning("search window %s..%s failed: %s", start, end, exc)
            return
        total = int((first or {}).get("total_count") or 0)
        window.total_count = total
        if (first or {}).get("incomplete_results"):
            result.incomplete_results = True

        if total == 0:
            return  # complete: nothing in this window
        span = (end - start).days
        if total <= SEARCH_SAFE_LIMIT or depth >= MAX_PARTITION_DEPTH or span <= MIN_SPLIT_SPAN_DAYS:
            # Small enough to page through — or as resolved as we can get.
            # Windows still over the ceiling land here and are marked partial.
            await self._search_window_pages(query, total, window, result, endpoint)
            return

        # Too many hits for one query — split the window in half and recurse.
        # The shared boundary day may surface in both halves; dedupe by node id.
        # This window's coverage is now the union of its children — mark it "split".
        window.status = "split"
        mid = start + timedelta(days=max(1, span // 2))
        await self._collect_window(base_query, start, mid, result, depth + 1, endpoint, date_qualifier)
        await self._collect_window(base_query, mid, end, result, depth + 1, endpoint, date_qualifier)

    async def search_partitioned(self, base_query: str, today: Optional[date] = None, endpoint: str = "/search/issues", date_qualifier: str = "created") -> PartitionedSearchResult:
        """Search `base_query` across all of GitHub history, partitioning around the
        1,000-result search ceiling. Returns deduped items plus per-window coverage —
        callers must check `coverage_complete` before claiming full history.
        `endpoint` is "/search/issues" (PRs/issues) or "/search/commits"."""
        result = PartitionedSearchResult()
        end = today or datetime.now(timezone.utc).date()

        # Fast path: the whole history fits in one query.
        probe = await self._search_page(base_query, 1, endpoint)
        total = int((probe or {}).get("total_count") or 0)
        if (probe or {}).get("incomplete_results"):
            result.incomplete_results = True
        if 0 < total <= SEARCH_SAFE_LIMIT and not result.incomplete_results:
            window = SearchWindow(EARLIEST_ACTIVITY, end)
            window.total_count = total
            result.windows.append(window)
            # page 1 was already fetched — reuse it by fetching remaining pages.
            for item in (probe or {}).get("items") or []:
                item_id = item.get("id") or item.get("node_id") or item.get("sha")
                if item_id is not None:
                    result.items[item_id] = item
            window.fetched += len((probe or {}).get("items") or [])
            for page in range(2, max(2, -(-total // PER_PAGE) + 1)):
                data = await self._search_page(base_query, page, endpoint)
                batch = (data or {}).get("items") or []
                if (data or {}).get("incomplete_results"):
                    result.incomplete_results = True
                    window.status = "partial"
                for item in batch:
                    item_id = item.get("id") or item.get("node_id") or item.get("sha")
                    if item_id is not None:
                        result.items[item_id] = item
                window.fetched += len(batch)
                if len(batch) < PER_PAGE:
                    break
            if window.fetched < total and window.status == "complete":
                window.status = "partial"
            return result

        # Dense history — bisect by created: windows.
        await self._collect_window(base_query, EARLIEST_ACTIVITY, end, result, endpoint=endpoint, date_qualifier=date_qualifier)
        return result

    async def search_commits(self, login: str) -> PartitionedSearchResult:
        """Authored commits via /search/commits — replaces per-repo commit scans.

        Limitation: commit search indexes default-branch commits; commits that
        only exist inside PR head branches are captured via pulls/{n}/commits
        evidence instead. Coverage windows are recorded like any other search.
        """
        return await self.search_partitioned(f"author:{login}", endpoint="/search/commits", date_qualifier="author-date")

    @staticmethod
    def _repo_from_search_item(item: dict) -> Optional[str]:
        url = item.get("repository_url") or ""
        # https://api.github.com/repos/owner/name
        parts = url.rstrip("/").split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 and parts[-2] else None

    # ---------- identity / discovery ----------

    async def authenticated_user(self) -> dict:
        """The token's GitHub identity: login, numeric id, account type."""
        me = await self._get("/user")
        if not me:
            raise GitHubAPIError(401, "/user", "no authenticated user")
        return {
            "login": me.get("login") or "",
            "github_id": str(me.get("id") or ""),
            "account_type": me.get("type") or "User",
            "name": me.get("name") or "",
            "avatar_url": me.get("avatar_url") or "",
            "profile_url": me.get("html_url") or "",
        }

    async def authenticated_login(self) -> str:
        return (await self.authenticated_user())["login"]

    async def list_user_orgs(self) -> list[str]:
        """Orgs the authenticated user belongs to (membership ≠ ownership/control)."""
        orgs, _ = await self._paginate("/user/orgs", {})
        return [o.get("login") for o in orgs if o.get("login")]

    async def list_org_memberships(self) -> dict[str, str]:
        """{org_login: role} for every org membership — role is "admin" or "member".

        This is the verifiable signal that distinguishes an org the developer
        *controls* (admin) from one they merely *belong to* (member)."""
        memberships, _ = await self._paginate("/user/memberships/orgs", {"state": "active"})
        out: dict[str, str] = {}
        for m in memberships or []:
            org = (m.get("organization") or {}).get("login")
            role = (m.get("role") or "").lower()
            if org:
                out[org.lower()] = role or "member"
        return out

    async def fetch_org_membership(self, org: str) -> Optional[dict]:
        """Single-org membership check: {state, role} or None when not a member."""
        return await self._get(f"/user/memberships/orgs/{org}")

    async def fetch_repos(self, login: str) -> tuple[list[dict], bool]:
        """Repos the token can see: owned, collaborated on, and org memberships."""
        repos, truncated = await self._paginate(
            "/user/repos",
            {
                "affiliation": "owner,collaborator,organization_member",
                "sort": "pushed",
                "direction": "desc",
            },
        )
        return repos, truncated

    async def fetch_repo(self, repo_full: str) -> Optional[dict]:
        """Repository metadata incl. owner type, fork parent, and caller permissions."""
        return await self._get(f"/repos/{repo_full}")

    async def discover_activity(self, login: str) -> dict:
        """Partitioned search discovery: authored PRs, authored issues, reviewed PRs.

        Returns {"authored_prs": [...], "authored_issues": [...], "reviewed_prs": [...],
        "repos": set, "coverage": {kind: PartitionedSearchResult}, "truncated": bool}.
        """
        out = {
            "authored_prs": [],
            "authored_issues": [],
            "reviewed_prs": [],
            "repos": set(),
            "coverage": {},
            "truncated": False,
        }
        searches = [
            (f"is:pr author:{login}", "authored_prs"),
            (f"is:issue author:{login}", "authored_issues"),
            (f"is:pr reviewed-by:{login}", "reviewed_prs"),
        ]
        for query, bucket in searches:
            result = await self.search_partitioned(query)
            out["coverage"][bucket] = result
            out["truncated"] = out["truncated"] or result.truncated
            for item in result.to_list():
                repo = self._repo_from_search_item(item)
                if not repo:
                    continue
                out["repos"].add(repo)
                entry = {
                    "id": item.get("id"),
                    "repo": repo,
                    "number": item.get("number"),
                    "node_id": item.get("node_id"),
                    "author": (item.get("user") or {}).get("login"),
                    "title": item.get("title") or "",
                    "state": item.get("state") or "",
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "closed_at": item.get("closed_at"),
                    "draft": bool(item.get("draft")),
                    "labels": [l.get("name", "") for l in (item.get("labels") or []) if isinstance(l, dict) and l.get("name")],
                    "comments": item.get("comments") or 0,
                    "html_url": item.get("html_url") or "",
                }
                if bucket == "reviewed_prs" and entry["author"] == login:
                    continue  # self-authored PRs are covered by the authored-PR path
                out[bucket].append(entry)
        return out

    # ---------- per-repo fetches ----------

    async def fetch_prs(self, repo_full: str, login: str) -> tuple[list[dict], bool]:
        prs, truncated = await self._paginate(
            f"/repos/{repo_full}/pulls",
            {"state": "all", "sort": "updated", "direction": "desc"},
        )
        return [p for p in prs if (p.get("user") or {}).get("login") == login], truncated

    async def fetch_issues(self, repo_full: str, login: str) -> tuple[list[dict], bool]:
        issues, truncated = await self._paginate(
            f"/repos/{repo_full}/issues",
            {"state": "all", "sort": "updated", "direction": "desc"},
        )
        # drop PRs (they carry a pull_request key) and other authors' issues
        return [
            i
            for i in issues
            if "pull_request" not in i and (i.get("user") or {}).get("login") == login
        ], truncated

    async def fetch_issue(self, repo_full: str, number: int) -> Optional[dict]:
        return await self._get(f"/repos/{repo_full}/issues/{number}")

    async def fetch_issue_timeline(self, repo_full: str, number: int) -> tuple[list[dict], bool]:
        """Issue/PR timeline events — source of revert & cross-reference evidence.

        Returns (events, truncated). Event types include merged, closed,
        cross-referenced, reverted, referenced, headed, committed, reviewed."""
        return await self._paginate(
            f"/repos/{repo_full}/issues/{number}/timeline",
            {"per_page": PER_PAGE},
        )

    async def fetch_commits(self, repo_full: str, login: str) -> tuple[list[dict], bool]:
        return await self._paginate(
            f"/repos/{repo_full}/commits", {"author": login}
        )

    # ---------- PR detail + evidence ----------

    async def fetch_pr_detail(self, repo_full: str, number: int) -> Optional[dict]:
        """Full PR object: merge state, diff stats, review pointers, head sha."""
        return await self._get(f"/repos/{repo_full}/pulls/{number}")

    async def fetch_pr_files(self, repo_full: str, number: int) -> tuple[list[dict], bool]:
        return await self._paginate(f"/repos/{repo_full}/pulls/{number}/files", {})

    async def fetch_pr_reviews(self, repo_full: str, number: int) -> list[dict]:
        reviews, _ = await self._paginate(f"/repos/{repo_full}/pulls/{number}/reviews", {})
        return reviews

    async def fetch_pr_review_comments(self, repo_full: str, number: int) -> list[dict]:
        """Inline review comments (pulls/{n}/comments)."""
        comments, _ = await self._paginate(f"/repos/{repo_full}/pulls/{number}/comments", {})
        return comments

    async def fetch_pr_conversation_comments(self, repo_full: str, number: int) -> list[dict]:
        """PR-level conversation comments (issues/{n}/comments)."""
        comments, _ = await self._paginate(f"/repos/{repo_full}/issues/{number}/comments", {})
        return comments

    async def find_revert_prs(self, repo_full: str, number: int, title: str = "") -> list[dict]:
        """Merged PRs in the same repo that look like reverts of PR #number.

        Second-chance signal for when the timeline API misses `reverted`
        events: GitHub's revert flow produces PRs titled `Revert "..."` whose
        body links back (`Reverts owner/repo#N`). One search page, filtered
        locally — a candidate list, not a verdict."""
        query = f"repo:{repo_full} is:pr is:merged in:title revert"
        data = await self._search_page(query, 1)
        items = (data or {}).get("items") or []
        out = []
        title_head = (title or "")[:60].lower()
        for it in items:
            text = f"{it.get('title') or ''}\n{it.get('body') or ''}"
            revert_title = (it.get("title") or "").lower()
            referenced = f"#{number}" in text or f"/pull/{number}" in text
            # GitHub names revert PRs `Revert "<original title>"` — a title
            # match is corroborating evidence even when the body link is absent.
            title_match = bool(title_head) and title_head in revert_title and "revert" in revert_title
            if referenced or title_match:
                out.append({
                    "number": it.get("number"),
                    "title": it.get("title") or "",
                    "url": it.get("html_url") or "",
                })
        return out[:5]

    async def fetch_pr_commits(self, repo_full: str, number: int) -> tuple[list[dict], bool]:
        return await self._paginate(f"/repos/{repo_full}/pulls/{number}/commits", {})

    async def fetch_check_runs(self, repo_full: str, sha: str) -> tuple[list[dict], bool]:
        """Check runs for a commit (envelope endpoint)."""
        return await self._paginate(f"/repos/{repo_full}/commits/{sha}/check-runs", {}, envelope=True)

    async def fetch_commit_status(self, repo_full: str, sha: str) -> Optional[dict]:
        """Combined commit status (legacy Status API)."""
        return await self._get(f"/repos/{repo_full}/commits/{sha}/status")

    # ---------- review evidence ----------

    @staticmethod
    def summarize_reviews(reviews: list[dict]) -> dict:
        states: dict[str, int] = {}
        reviewers: set[str] = set()
        for r in reviews:
            user = (r.get("user") or {}).get("login")
            if user:
                reviewers.add(user)
            st = (r.get("state") or "").upper()
            states[st] = states.get(st, 0) + 1
        return {
            "review_count": len(reviews),
            "approvals": states.get("APPROVED", 0),
            "change_requests": states.get("CHANGES_REQUESTED", 0),
            "commented_reviews": states.get("COMMENTED", 0),
            "dismissed_reviews": states.get("DISMISSED", 0),
            "reviewers": len(reviewers),
        }

    async def fetch_authored_pr_review_stats(
        self, repo_full: str, prs: list[dict], login: str, budget: int = 10_000
    ) -> tuple[dict[int, dict], int]:
        """Review stats for authored PRs in one repo (kept for compatibility)."""
        candidates = prs[:budget]
        sem = asyncio.Semaphore(REVIEW_FETCH_CONCURRENCY)

        async def one(pr: dict):
            async with sem:
                try:
                    reviews = await self.fetch_pr_reviews(repo_full, pr["number"])
                except (httpx.HTTPError, GitHubAPIError) as exc:
                    logger.warning("reviews fetch failed for %s#%s: %s", repo_full, pr.get("number"), exc)
                    return pr["number"], None
                return pr["number"], self.summarize_reviews(reviews)

        pairs = await asyncio.gather(*[one(p) for p in candidates])
        return {num: stats for num, stats in pairs if stats is not None}, len(candidates)

    async def fetch_reviewed_prs_reviews(
        self, entries: list[dict], login: str, budget: int = 10_000
    ) -> list[dict]:
        """Reviews the user submitted on other people's PRs (from reviewed-by search)."""
        sem = asyncio.Semaphore(REVIEW_FETCH_CONCURRENCY)
        out: list[dict] = []

        async def one(entry: dict):
            async with sem:
                try:
                    reviews = await self.fetch_pr_reviews(entry["repo"], entry["number"])
                except (httpx.HTTPError, GitHubAPIError) as exc:
                    logger.warning("reviewed-PR fetch failed for %s#%s: %s", entry["repo"], entry.get("number"), exc)
                    return []
                mine = [r for r in reviews if (r.get("user") or {}).get("login") == login]
                for r in mine:
                    r["_repo_full"] = entry["repo"]
                    r["_pr_number"] = entry["number"]
                    r["_pr_title"] = entry.get("title") or ""
                    r["_pr_author"] = entry.get("author") or ""
                return mine

        results = await asyncio.gather(*[one(e) for e in entries[:budget]])
        for mine in results:
            out.extend(mine)
        return out
