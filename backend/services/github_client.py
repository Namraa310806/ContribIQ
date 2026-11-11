"""Rate-limit aware GitHub REST fetcher used by the analysis pipeline.

Coverage model (Phase 1 — data accuracy):
- Repo discovery combines /user/repos (owned + collaborator + org repos, paginated)
  with search-based discovery, so repos the user contributed to but doesn't belong
  to are still analyzed.
- Every list endpoint is paginated to exhaustion (or the API/search 1000-item cap),
  and truncation is reported so partial coverage is never silent.
- Authored PRs get a per-PR review lookup (bounded) so review cycles, approvals and
  change requests become evidence. Reviews the user *wrote* on other people's PRs
  come from the `reviewed-by:` search qualifier.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 10  # 1000 items — also the hard cap of the search API
MAX_REPOS = 100
MAX_PR_REVIEW_FETCHES = 250  # authored-PR review lookups per run, most recent first
MAX_REVIEWED_PR_FETCHES = 150  # others' PRs to inspect for the user's reviews
REVIEW_FETCH_CONCURRENCY = 4


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

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: Optional[dict] = None):
        resp = await self._client.get(path, params=params or {})
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if remaining is not None and remaining.isdigit() and int(remaining) <= 5 and reset:
            wait = max(1, min(90, int(reset) - int(datetime.now(timezone.utc).timestamp()) + 1))
            logger.warning("GitHub rate limit low — sleeping %ss", wait)
            await asyncio.sleep(wait)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    async def _paginate(self, path: str, params: Optional[dict] = None) -> tuple[list, bool]:
        """Fetch every page. Returns (items, truncated) — truncated means a cap was hit."""
        items: list = []
        truncated = False
        for page in range(1, MAX_PAGES + 1):
            data = await self._get(path, {**(params or {}), "page": page, "per_page": PER_PAGE})
            if not data:
                break
            items.extend(data)
            if len(data) < PER_PAGE:
                break
            if page == MAX_PAGES:
                truncated = True
        return items, truncated

    async def _search(self, query: str) -> tuple[list[dict], bool]:
        """Paginate /search/issues (issues + PRs share this endpoint).

        Unlike list endpoints, search returns an envelope {"total_count", "items",
        "incomplete_results"} — unwrap it here rather than in _paginate.
        """
        items: list[dict] = []
        truncated = False
        for page in range(1, MAX_PAGES + 1):
            data = await self._get(
                "/search/issues",
                {"q": query, "sort": "updated", "order": "desc", "page": page, "per_page": PER_PAGE},
            )
            batch = (data or {}).get("items") or []
            items.extend(batch)
            if (data or {}).get("incomplete_results"):
                truncated = True
            if len(batch) < PER_PAGE:
                break
            if page == MAX_PAGES:
                truncated = True
        return items, truncated

    @staticmethod
    def _repo_from_search_item(item: dict) -> Optional[str]:
        url = item.get("repository_url") or ""
        # https://api.github.com/repos/owner/name
        parts = url.rstrip("/").split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 and parts[-2] else None

    # ---------- identity / discovery ----------

    async def authenticated_login(self) -> str:
        me = await self._get("/user")
        return me["login"]

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
        return repos[:MAX_REPOS], truncated or len(repos) > MAX_REPOS

    async def discover_activity(self, login: str) -> dict:
        """Search-based coverage: repos + item numbers where the user has activity,
        including repos they neither own nor collaborate on."""
        out = {"repos": set(), "authored_prs": [], "authored_issues": [], "reviewed_prs": []}
        searches = [
            (f"is:pr author:{login}", "authored_prs"),
            (f"is:issue author:{login}", "authored_issues"),
            (f"is:pr reviewed-by:{login}", "reviewed_prs"),
        ]
        truncated_any = False
        for query, bucket in searches:
            items, truncated = await self._search(query)
            truncated_any = truncated_any or truncated
            for item in items:
                repo = self._repo_from_search_item(item)
                if not repo:
                    continue
                out["repos"].add(repo)
                entry = {
                    "repo": repo,
                    "number": item.get("number"),
                    "author": (item.get("user") or {}).get("login"),
                    "title": item.get("title") or "",
                }
                if bucket == "reviewed_prs" and entry["author"] == login:
                    continue  # self-authored PRs are covered by the authored-PR path
                out[bucket].append(entry)
        out["truncated"] = truncated_any
        return out

    # ---------- per-repo fetches (all paginated) ----------

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

    async def fetch_commits(self, repo_full: str, login: str) -> tuple[list[dict], bool]:
        return await self._paginate(
            f"/repos/{repo_full}/commits", {"author": login}
        )

    async def fetch_pr_reviews(self, repo_full: str, number: int) -> list[dict]:
        reviews, _ = await self._paginate(f"/repos/{repo_full}/pulls/{number}/reviews", {})
        return reviews

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
            "reviewers": len(reviewers),
        }

    async def fetch_authored_pr_review_stats(
        self, repo_full: str, prs: list[dict], login: str, budget: int = MAX_PR_REVIEW_FETCHES
    ) -> tuple[dict[int, dict], int]:
        """Review stats for the user's authored PRs in one repo. Returns ({number: stats}, fetched_count)."""
        # Most recently updated first — the pulls list already arrives sorted that way.
        candidates = prs[:budget]
        sem = asyncio.Semaphore(REVIEW_FETCH_CONCURRENCY)

        async def one(pr: dict):
            async with sem:
                try:
                    reviews = await self.fetch_pr_reviews(repo_full, pr["number"])
                except httpx.HTTPError as exc:
                    logger.warning("reviews fetch failed for %s#%s: %s", repo_full, pr.get("number"), exc)
                    return pr["number"], None
                return pr["number"], self.summarize_reviews(reviews)

        pairs = await asyncio.gather(*[one(p) for p in candidates])
        return {num: stats for num, stats in pairs if stats is not None}, len(candidates)

    async def fetch_reviewed_prs_reviews(
        self, entries: list[dict], login: str, budget: int = MAX_REVIEWED_PR_FETCHES
    ) -> list[dict]:
        """Reviews the user submitted on other people's PRs (from reviewed-by search)."""
        sem = asyncio.Semaphore(REVIEW_FETCH_CONCURRENCY)
        out: list[dict] = []

        async def one(entry: dict):
            async with sem:
                try:
                    reviews = await self.fetch_pr_reviews(entry["repo"], entry["number"])
                except httpx.HTTPError as exc:
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
