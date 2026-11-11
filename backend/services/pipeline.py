"""Background analysis pipeline: fetch → classify → skills → insights.

Jobs run as managed asyncio tasks with progress persisted to Mongo so the frontend
can poll /api/analysis/status. Offline mode (no GitHub token — e.g. the demo
profile) re-uses already-stored contributions and re-runs aggregation + insights.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from pymongo.errors import BulkWriteError

from lib.db import db
from services import github_client as gh
from services.classifier import BATCH_SIZE, classify_batch
from services.insights_gen import generate_insights
from services.scoring import KIND_WEIGHT, score_contribution

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}
STALE_AFTER = 15 * 60  # a "running" job older than this died with a server restart

STAGE_RANGES = {
    "fetch": (5, 35),
    "classify": (35, 70),
    "skills": (70, 85),
    "insights": (85, 99),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aw(dt: Optional[datetime]) -> Optional[datetime]:
    """Motor hands naive datetimes back — normalise before any arithmetic."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def get_latest_job(user_id: str) -> Optional[dict]:
    job = await db.jobs.find_one({"user_id": user_id}, sort=[("created_at", -1)])
    if job and job.get("status") in ("queued", "running"):
        updated = _aw(job.get("updated_at")) or _aw(job.get("created_at"))
        if updated and (_now() - updated).total_seconds() > STALE_AFTER:
            await db.jobs.update_one(
                {"id": job["id"]},
                {"$set": {
                    "status": "failed",
                    "error": "Analysis was interrupted (server restart). Start it again.",
                    "updated_at": _now(),
                    "completed_at": _now(),
                }},
            )
            job = await db.jobs.find_one({"id": job["id"]})
    return job


async def start_job(user: dict, mode: str = "full") -> dict:
    existing = await db.jobs.find_one({"user_id": user["id"], "status": {"$in": ["queued", "running"]}})
    if existing:
        return existing
    job = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "mode": mode,
        "status": "running",
        "stage": "queued" if mode == "full" else "insights",
        "stage_label": "Queued",
        "progress": 0,
        "error": None,
        "stats": {},
        "created_at": _now(),
        "updated_at": _now(),
        "completed_at": None,
    }
    await db.jobs.insert_one(dict(job))
    task = asyncio.create_task(_run_job(job["id"], user["id"], mode))
    _tasks[job["id"]] = task
    task.add_done_callback(lambda _t: _tasks.pop(job["id"], None))
    return job


async def _set_stage(job_id: str, stage: str, label: str, progress: int, stats: dict) -> None:
    await db.jobs.update_one(
        {"id": job_id},
        {"$set": {"stage": stage, "stage_label": label, "progress": min(99, progress), "stats": stats, "updated_at": _now()}},
    )


# ---------- normalisers (GitHub payload → contribution dict) ----------

def _parse_gh_time(value: Optional[str]) -> datetime:
    if not value:
        return _now()
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _repo_context(repo_full: str, login: str) -> dict:
    """Ownership context: own repo vs independently maintained codebase."""
    owner = repo_full.split("/", 1)[0] if "/" in repo_full else ""
    return {
        "repo_owner": owner,
        "is_own_repo": owner.lower() == (login or "").lower(),
    }


def _base(item: dict, kind: str, repo_full: str, title: str, base_techs: list[str], **kw) -> dict:
    return {
        "dedupe_key": kw.pop("dedupe_key"),
        "kind": kind,
        "repo": repo_full,
        "title": title[:300],
        "body": kw.pop("body", "") or "",
        "number": kw.pop("number", None),
        "url": kw.pop("url", ""),
        "state": kw.pop("state", ""),
        "labels": kw.pop("labels", []),
        "additions": kw.pop("additions", 0) or 0,
        "deletions": kw.pop("deletions", 0) or 0,
        "comments": kw.pop("comments", 0) or 0,
        "occurred_at": kw.pop("occurred_at"),
        "base_technologies": [t for t in base_techs if t][:6],
        **kw,
    }


def norm_pr(p: dict, repo_full: str, base_techs: list[str], login: str, review_stats: Optional[dict] = None) -> dict:
    state = "merged" if p.get("merged_at") else (p.get("state") or "open")
    rs = review_stats or {}
    return _base(
        {}, "pr", repo_full, p.get("title") or "Untitled pull request", base_techs,
        dedupe_key=f"pr:{repo_full}:{p.get('number')}",
        body=p.get("body") or "", number=p.get("number"), url=p.get("html_url") or "",
        state=state, labels=[l.get("name", "") for l in (p.get("labels") or []) if l.get("name")],
        comments=p.get("comments") or 0,
        occurred_at=_parse_gh_time(p.get("merged_at") or p.get("closed_at") or p.get("updated_at")),
        merged=bool(p.get("merged_at")),
        draft=bool(p.get("draft")),
        author_association=p.get("author_association") or "",
        changed_files=p.get("changed_files") or 0,
        commits_count=p.get("commits") or 0,
        review_count=rs.get("review_count", 0),
        approvals=rs.get("approvals", 0),
        change_requests=rs.get("change_requests", 0),
        reviewers=rs.get("reviewers", 0),
        **_repo_context(repo_full, login),
    )


def norm_issue(i: dict, repo_full: str, base_techs: list[str], login: str) -> dict:
    return _base(
        {}, "issue", repo_full, i.get("title") or "Untitled issue", base_techs,
        dedupe_key=f"issue:{repo_full}:{i.get('number')}",
        body=i.get("body") or "", number=i.get("number"), url=i.get("html_url") or "",
        state=i.get("state") or "open",
        labels=[l.get("name", "") for l in (i.get("labels") or []) if l.get("name")],
        comments=i.get("comments") or 0,
        occurred_at=_parse_gh_time(i.get("closed_at") or i.get("updated_at") or i.get("created_at")),
        author_association=i.get("author_association") or "",
        **_repo_context(repo_full, login),
    )


def norm_commit(c: dict, repo_full: str, base_techs: list[str], login: str) -> dict:
    msg = (c.get("commit") or {}).get("message") or "Commit"
    return _base(
        {}, "commit", repo_full, msg.splitlines()[0], base_techs,
        dedupe_key=f"commit:{repo_full}:{c.get('sha')}",
        body=msg[len(msg.splitlines()[0]):].strip(), url=(c.get("html_url") or ""),
        state="committed",
        occurred_at=_parse_gh_time(((c.get("commit") or {}).get("author") or {}).get("date")),
        **_repo_context(repo_full, login),
    )


def norm_review(rv: dict, repo_full: str, pr_number: int, base_techs: list[str], login: str) -> dict:
    return _base(
        {}, "review", repo_full, f"Review on “{(rv.get('_pr_title') or f'PR #{pr_number}')}”", base_techs,
        dedupe_key=f"review:{repo_full}:{pr_number}:{rv.get('id')}",
        body=rv.get("body") or "", number=pr_number, url=rv.get("html_url") or "",
        state=rv.get("state") or "commented",
        occurred_at=_parse_gh_time(rv.get("submitted_at")),
        pr_author=rv.get("_pr_author") or "",
        **_repo_context(repo_full, login),
    )


# ---------- stages ----------

async def rebuild_skills(user_id: str) -> list[dict]:
    """Re-aggregate the user's skill profile from their stored contributions.

    Recompute-and-replace, narrowly scoped to this one user's derived rows.
    """
    docs = await db.contributions.find({"user_id": user_id}).to_list(5000)
    agg: dict[str, dict] = {}
    now = _now()
    for d in docs:
        occurred = _aw(d.get("occurred_at")) or now
        weight = KIND_WEIGHT.get(d.get("kind", "commit"), 1)
        for tech in d.get("technologies", []):
            name = str(tech).strip()
            if not name or len(name) > 40:
                continue
            a = agg.setdefault(name, {"count": 0, "weight": 0, "repos": set(), "last": occurred})
            a["count"] += 1
            a["weight"] += weight
            a["repos"].add(d.get("repo"))
            if occurred > a["last"]:
                a["last"] = occurred
    out = []
    for name, a in agg.items():
        recency_days = max(0, (now - a["last"]).days)
        score = (
            min(50, a["weight"] * 6)
            + min(30, len(a["repos"]) * 8)
            + (20 if recency_days <= 90 else (10 if recency_days <= 365 else 4))
        )
        out.append(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "name": name,
                "confidence": "High" if score >= 75 else ("Medium" if score >= 45 else "Low"),
                "score": min(100, score),
                "evidence_count": a["count"],
                "repo_count": len(a["repos"]),
                "last_used_at": a["last"],
            }
        )
    out.sort(key=lambda s: s["score"], reverse=True)
    await db.skills.delete_many({"user_id": user_id})  # derived rows only, this user only
    if out:
        await db.skills.insert_many(out)
    return out


async def _run_job(job_id: str, user_id: str, mode: str) -> None:
    stats: dict[str, int] = {}
    try:
        user = await db.users.find_one({"id": user_id})
        if not user:
            raise RuntimeError("user vanished mid-job")
        login = user.get("login") or "developer"
        new_items: list[dict] = []

        if mode == "full":
            await _set_stage(job_id, "fetch", "Fetching GitHub activity", 5, stats)
            raw: list[dict] = []
            if user.get("github_token"):
                gc = gh.GitHubClient(user["github_token"])
                try:
                    login = await gc.authenticated_login()
                    excluded = set(user.get("excluded_repos") or [])

                    # --- discovery: repos the token can see + repos surfaced by search ---
                    owned, repos_trunc = await gc.fetch_repos(login)
                    activity = await gc.discover_activity(login)
                    repo_meta: dict[str, dict] = {r["full_name"]: r for r in owned if r.get("full_name")}
                    for name in activity["repos"]:
                        repo_meta.setdefault(name, {"full_name": name, "language": "", "topics": []})
                    stats["repos_discovered"] = len(repo_meta)
                    stats["search_truncated"] = 1 if (activity["truncated"] or repos_trunc) else 0

                    repos = [r for r in repo_meta.values() if r["full_name"] not in excluded]
                    # most recently pushed first; search-only repos (no pushed_at) sort last
                    repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
                    stats["repos_fetched"] = len(repos)
                    stats["repos_skipped"] = len(repo_meta) - len(repos)

                    # per-repo evidence: authored PRs (+ their review stats), issues, commits
                    total_prs_with_reviews = 0
                    for ri, repo in enumerate(repos):
                        repo_full = repo["full_name"]
                        base_techs = [t for t in [repo.get("language") or "", *(repo.get("topics") or [])] if t]
                        try:
                            prs, _ = await gc.fetch_prs(repo_full, login)
                            review_stats, fetched = await gc.fetch_authored_pr_review_stats(repo_full, prs, login)
                            total_prs_with_reviews += fetched
                            for p in prs:
                                raw.append(norm_pr(p, repo_full, base_techs, login, review_stats.get(p.get("number"))))
                            issues, _ = await gc.fetch_issues(repo_full, login)
                            for i in issues:
                                raw.append(norm_issue(i, repo_full, base_techs, login))
                            commits, _ = await gc.fetch_commits(repo_full, login)
                            for c in commits:
                                raw.append(norm_commit(c, repo_full, base_techs, login))
                        except httpx.HTTPError as exc:
                            # one inaccessible repo must not kill the whole run
                            logger.warning("repo fetch failed for %s: %s", repo_full, exc)
                            stats["repos_failed"] = stats.get("repos_failed", 0) + 1
                        await _set_stage(
                            job_id, "fetch", f"Fetching {repo_full}",
                            STAGE_RANGES["fetch"][0] + int(30 * (ri + 1) / max(1, len(repos))), stats,
                        )

                    # reviews the user wrote on other people's PRs (search-driven, bounded)
                    try:
                        reviewed = await gc.fetch_reviewed_prs_reviews(activity["reviewed_prs"], login)
                        for rv in reviewed:
                            repo_full = rv.get("_repo_full") or ""
                            meta = repo_meta.get(repo_full) or {}
                            base_techs = [t for t in [meta.get("language") or "", *(meta.get("topics") or [])] if t]
                            raw.append(norm_review(rv, repo_full, rv.get("_pr_number") or 0, base_techs, login))
                        stats["reviews_written"] = len(reviewed)
                    except httpx.HTTPError as exc:
                        logger.warning("reviewed-by fetch failed: %s", exc)
                    stats["prs_with_review_data"] = total_prs_with_reviews
                finally:
                    await gc.close()
            else:
                # Offline / demo mode: analysis re-uses what is already stored.
                stats["repos_fetched"] = 0
                await asyncio.sleep(0.8)  # let the stepper animate
            existing = {doc["dedupe_key"] async for doc in db.contributions.find({"user_id": user_id}, {"dedupe_key": 1, "_id": 0})}
            new_items = [r for r in raw if r["dedupe_key"] not in existing]
            stats["contributions_found"] = len(raw)
            stats["new_contributions"] = len(new_items)
        else:
            stats["repos_fetched"] = 0
            stats["new_contributions"] = 0

        if mode == "full":
            await _set_stage(job_id, "classify", "AI classification", 35, stats)
            classified = 0
            for i in range(0, len(new_items), BATCH_SIZE):
                chunk = new_items[i : i + BATCH_SIZE]
                results = await classify_batch(chunk)
                docs = []
                for item, res in zip(chunk, results):
                    techs = list(dict.fromkeys([*item.pop("base_technologies", []), *res["technologies"]]))[:6]
                    # Deterministic scoring owns impact_score + dimensions; the LLM only
                    # supplies category / complexity / technologies / summary.
                    scored = score_contribution({**item, "complexity": res["complexity"]})
                    docs.append(
                        {
                            **item,
                            "id": str(uuid.uuid4()),
                            "user_id": user_id,
                            "technologies": techs,
                            "category": res["category"],
                            "complexity": res["complexity"],
                            "impact_score": scored["impact_score"],
                            "dimensions": scored["dimensions"],
                            "summary": res["summary"] or item["title"],
                            "analyzed": True,
                            "analyzed_at": _now(),
                        }
                    )
                if docs:
                    try:
                        await db.contributions.insert_many(docs, ordered=False)
                    except BulkWriteError as bwe:
                        logger.warning("contribution batch partially deduped: %s", bwe.details.get("nInserted"))
                    classified += len(docs)
                stats["classified"] = classified
                await _set_stage(
                    job_id, "classify", "AI classification",
                    35 + int(35 * min(1, (i + len(chunk)) / max(1, len(new_items)))), stats,
                )
            await db.users.update_one({"id": user_id}, {"$set": {"last_synced_at": _now()}})
        else:
            await _set_stage(job_id, "classify", "Using cached classifications", 68, stats)

        await _set_stage(job_id, "skills", "Skill aggregation", 72, stats)
        skills = await rebuild_skills(user_id)
        stats["skills"] = len(skills)

        await _set_stage(job_id, "insights", "Generating insights", 88, stats)
        contributions = await db.contributions.find({"user_id": user_id}).to_list(200)
        skill_docs = await db.skills.find({"user_id": user_id}).sort("score", -1).to_list(30)
        generated = await generate_insights(login, contributions, skill_docs)
        await db.insights.delete_many({"user_id": user_id, "pinned": False})  # keep pinned
        await db.insights.delete_many({"user_id": user_id, "kind": "recruiter_summary"})
        if generated:
            for g in generated:
                g.setdefault("id", str(uuid.uuid4()))
                g["user_id"] = user_id
                g.setdefault("pinned", False)
                g.setdefault("created_at", _now())
                g.setdefault("content", "")
                g.setdefault("evidence", [])
            await db.insights.insert_many(generated)
        stats["insights"] = len(generated)

        await db.jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "completed", "stage": "done", "stage_label": "Completed", "progress": 100,
                      "stats": stats, "completed_at": _now(), "updated_at": _now()}},
        )
    except Exception as exc:
        logger.exception("analysis job %s failed", job_id)
        await db.jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "failed", "error": str(exc)[:300], "completed_at": _now(), "updated_at": _now()}},
        )
