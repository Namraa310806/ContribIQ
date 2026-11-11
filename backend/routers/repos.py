"""Repo picker: list the user's repositories with include/exclude state, save exclusions.

Exclusions only affect future GitHub fetches — already-analyzed work stays visible.
"""

import logging

import httpx
from fastapi import APIRouter, Request

from lib.db import db
from lib.session import require_user
from models.contribiq import RepoOption, ReposResponse, UpdateExcludedRequest
from services import github_client as gh

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repos", tags=["repos"])


async def _build(user: dict) -> ReposResponse:
    excluded = set(user.get("excluded_repos") or [])
    counts: dict[str, int] = {}
    async for doc in db.contributions.find({"user_id": user["id"]}, {"repo": 1, "_id": 0}):
        counts[doc.get("repo", "")] = counts.get(doc.get("repo", ""), 0) + 1

    options: dict[str, RepoOption] = {}
    live = False
    if user.get("github_token"):
        client = gh.GitHubClient(user["github_token"])
        try:
            login = await client.authenticated_login()
            owned, _truncated = await client.fetch_repos(login)
            for repo in owned:
                name = repo["full_name"]
                options[name] = RepoOption(full_name=name, language=repo.get("language") or "")
            live = True
        except httpx.HTTPError as exc:  # fall back to stored repos rather than failing the picker
            logger.warning("repo list from GitHub failed: %s", exc)
        finally:
            await client.close()
    for name in counts:
        if name and name not in options:
            options[name] = RepoOption(full_name=name)
    for name in excluded:  # keep excluded repos visible so they can be re-included
        if name not in options:
            options[name] = RepoOption(full_name=name)

    items = []
    for name in sorted(options):
        opt = options[name]
        opt.included = name not in excluded
        opt.contribution_count = counts.get(name, 0)
        items.append(opt)
    return ReposResponse(items=items, live=live)


@router.get("", response_model=ReposResponse)
async def list_repos(request: Request):
    user = await require_user(request)
    return await _build(user)


@router.put("/excluded", response_model=ReposResponse)
async def update_excluded(body: UpdateExcludedRequest, request: Request):
    user = await require_user(request)
    cleaned = sorted({r.strip() for r in body.excluded if r and r.strip() and len(r) <= 200})
    await db.users.update_one({"id": user["id"]}, {"$set": {"excluded_repos": cleaned}})
    user["excluded_repos"] = cleaned
    return await _build(user)
