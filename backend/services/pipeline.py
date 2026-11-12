"""Background analysis pipeline: discover → evidence → classify → score → insights.

PR-centric model (Phase 1+):
- Discovery is search-driven (`is:pr author:`, `reviewed-by:`, `is:issue author:`,
  `author:` commits) with recursive date partitioning around the 1,000-result
  search ceiling. Per-window coverage is persisted to `sync_coverage` so partial
  history is never reported as complete.
- Every authored PR gets a detail fetch plus files / reviews / comments / CI
  evidence persisted to dedicated collections; ingestion is incremental
  (unchanged PRs are not re-fetched) and idempotent.
- Repository ownership is verified into `repo_eligibility`; own/controlled-org
  repos are excluded from open-source collaboration credit but keep their
  technical evidence (personal portfolio).
- `contributions` remains the denormalized projection the UI reads; PR rows are
  upserted so merge state and scores stay fresh instead of frozen at first sight.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from pymongo.errors import BulkWriteError

from lib.db import db
from services import eligibility as elig
from services import evidence as ev
from services import github_client as gh
from services.classifier import BATCH_SIZE, classify_batch
from services.insights_gen import generate_insights
from services.scoring import KIND_WEIGHT, score_contribution

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task] = {}
STALE_AFTER = 15 * 60  # a "running" job older than this died with a server restart
EVIDENCE_CONCURRENCY = 4
ISSUE_FETCH_CONCURRENCY = 4

STAGE_RANGES = {
    "fetch": (5, 55),
    "classify": (55, 80),
    "skills": (80, 92),
    "insights": (92, 99),
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
    """Legacy normaliser for list-endpoint PR payloads (kept for compatibility)."""
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


def norm_commit_search(item: dict, login: str, base_techs: list[str] = ()) -> Optional[dict]:
    """Normalise a /search/commits item (author:{login} query)."""
    repo = ((item.get("repository") or {}).get("full_name")) or ""
    sha = item.get("sha") or ""
    if not repo or not sha:
        return None
    commit = item.get("commit") or {}
    msg = commit.get("message") or "Commit"
    author_login = (item.get("author") or {}).get("login") or (commit.get("author") or {}).get("name") or ""
    return _base(
        {}, "commit", repo, msg.splitlines()[0], list(base_techs),
        dedupe_key=f"commit:{repo}:{sha}",
        body=msg[len(msg.splitlines()[0]):].strip(), url=item.get("html_url") or "",
        state="committed",
        occurred_at=_parse_gh_time((commit.get("author") or {}).get("date")),
        author_login=author_login,
        **_repo_context(repo, login),
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


# ---------- PR evidence ingestion ----------

CHILD_LABELS = {
    "files": "pr_files",
    "reviews": "pr_reviews",
    "review_comments": "pr_review_comments",
    "conversation_comments": "pr_comments",
    "commits": "pr_commits",
    "timeline": "pr_timeline",
}


async def _fetch_children(gc: gh.GitHubClient, repo_full: str, number: int) -> tuple[dict, dict, list[str]]:
    """Fetch all PR child evidence concurrently.

    Returns (payloads, statuses, errors) where statuses maps each child label to
    "ok" | "failed" | "truncated". Callers must only persist collections whose
    status is "ok" (or "truncated" — partial data is still real evidence, marked
    as such); failed collections keep their previously stored snapshot.
    """
    errors: list[str] = []
    statuses: dict[str, str] = {}

    async def guarded(coro, label: str):
        try:
            return await coro
        except Exception as exc:
            statuses[label] = "failed"
            errors.append(f"{label}: {str(exc)[:120]}")
            logger.warning("PR evidence %s failed for %s#%s: %s", label, repo_full, number, exc)
            return None

    files_res, reviews_res, rcomments_res, ccomments_res, commits_res, timeline_res = await asyncio.gather(
        guarded(gc.fetch_pr_files(repo_full, number), "files"),
        guarded(gc.fetch_pr_reviews(repo_full, number), "reviews"),
        guarded(gc.fetch_pr_review_comments(repo_full, number), "review_comments"),
        guarded(gc.fetch_pr_conversation_comments(repo_full, number), "conversation_comments"),
        guarded(gc.fetch_pr_commits(repo_full, number), "commits"),
        guarded(gc.fetch_issue_timeline(repo_full, number), "timeline"),
    )

    files_raw, files_trunc = files_res if files_res else (None, True)
    reviews_raw = reviews_res
    rcomments_raw = rcomments_res
    ccomments_raw = ccomments_res
    commits_raw, commits_trunc = commits_res if commits_res else (None, True)
    timeline_raw, timeline_trunc = timeline_res if timeline_res else (None, True)

    trunc_flags = {"files": files_trunc, "commits": commits_trunc, "timeline": timeline_trunc}
    for label, res in (
        ("files", files_res), ("reviews", reviews_res), ("review_comments", rcomments_res),
        ("conversation_comments", ccomments_res), ("commits", commits_res), ("timeline", timeline_res),
    ):
        if label in statuses:
            continue  # already "failed"
        statuses[label] = "truncated" if trunc_flags.get(label) else "ok"
    if any(trunc_flags.values()):
        errors.append("child pagination truncated")

    return {
        "_files_raw": files_raw,
        "_reviews_raw": reviews_raw,
        "_rcomments_raw": rcomments_raw,
        "_ccomments_raw": ccomments_raw,
        "_commits_raw": commits_raw,
        "_timeline_raw": timeline_raw,
    }, statuses, errors


async def ingest_pr(
    gc: gh.GitHubClient,
    user_id: str,
    entry: dict,
    stats: dict,
) -> Optional[dict]:
    """Fetch + persist one authored PR's evidence. Returns the stored doc."""
    repo_full, number = entry["repo"], entry["number"]
    key = ev.pr_key(repo_full, number)
    try:
        detail = await gc.fetch_pr_detail(repo_full, number)
    except gh.GitHubAPIError as exc:
        if exc.status == 404:
            stats["prs_deleted"] = stats.get("prs_deleted", 0) + 1
        else:
            stats["prs_failed"] = stats.get("prs_failed", 0) + 1
            logger.warning("PR detail failed %s: %s", key, exc)
        return None
    except httpx.HTTPError as exc:
        stats["prs_failed"] = stats.get("prs_failed", 0) + 1
        logger.warning("PR detail failed %s: %s", key, exc)
        return None
    if not detail:
        stats["prs_deleted"] = stats.get("prs_deleted", 0) + 1
        return None

    stats["prs_detailed"] = stats.get("prs_detailed", 0) + 1
    existing = await ev.get_pr(user_id, key)
    doc = ev.normalize_pr(repo_full, detail, user_id)

    if await ev.pr_needs_evidence(existing, detail):
        errors: list[str] = []
        gathered, child_status, child_errors = await _fetch_children(gc, repo_full, number)
        errors.extend(child_errors)

        # ---- evidence integrity: only successfully fetched collections are
        # replaced; failed collections keep their previous snapshot. ----
        children: dict[str, list[dict]] = {}
        files_docs = reviews_docs = rcomments_docs = ccomments_docs = commits_docs = []
        files_raw = gathered.get("_files_raw") or []
        reviews_raw = gathered.get("_reviews_raw") or []
        rcomments_raw = gathered.get("_rcomments_raw") or []
        ccomments_raw = gathered.get("_ccomments_raw") or []
        commits_raw = gathered.get("_commits_raw") or []
        timeline_raw = gathered.get("_timeline_raw") or []

        if child_status.get("files") in ("ok", "truncated"):
            files_docs = [ev.normalize_file(user_id, key, f) for f in files_raw]
            children["pr_files"] = files_docs
        if child_status.get("reviews") in ("ok", "truncated"):
            reviews_docs = [ev.normalize_review(user_id, key, r) for r in reviews_raw]
            children["pr_reviews"] = reviews_docs
        if child_status.get("review_comments") in ("ok", "truncated"):
            rcomments_docs = [ev.normalize_review_comment(user_id, key, c) for c in rcomments_raw]
            children["pr_review_comments"] = rcomments_docs
        if child_status.get("conversation_comments") in ("ok", "truncated"):
            ccomments_docs = [ev.normalize_conversation_comment(user_id, key, c) for c in ccomments_raw]
            children["pr_comments"] = ccomments_docs
        if child_status.get("commits") in ("ok", "truncated"):
            commits_docs = ev.normalize_commits(user_id, key, commits_raw)
            children["pr_commits"] = commits_docs

        if children:
            await ev.replace_pr_children(user_id, key, children)
        else:
            stats["prs_evidence_all_failed"] = stats.get("prs_evidence_all_failed", 0) + 1

        # Summaries: freshly fetched data wins; failed collections fall back to
        # the previously stored summary so a bad refresh can't erase knowledge.
        prev = existing or {}
        if child_status.get("files") in ("ok", "truncated"):
            doc["files_summary"] = ev.summarize_files(files_raw)
            # Bounded patch excerpts for the classifier — source files first,
            # hard-capped so the LLM context stays small.
            samples = []
            for f in sorted(files_raw, key=lambda x: 0 if ev.categorize_file(x.get("filename") or "") == "source" else 1):
                patch = (f.get("patch") or "").strip()
                if patch:
                    samples.append(patch[:600])
                if len(samples) >= 2:
                    break
            doc["patch_samples"] = samples
        else:
            doc["files_summary"] = prev.get("files_summary") or {}
            doc["patch_samples"] = prev.get("patch_samples") or []
        if child_status.get("reviews") in ("ok", "truncated"):
            doc["review_summary"] = ev.review_summary(reviews_docs)
        else:
            doc["review_summary"] = prev.get("review_summary") or {}

        # Integration outcome from the timeline (revert / superseded evidence).
        outcome = prev.get("outcome") or {}
        if child_status.get("timeline") in ("ok", "truncated") and timeline_raw is not None:
            outcome = ev.parse_timeline(timeline_raw)
            outcome["fetched_at"] = _now().isoformat()
        doc["outcome"] = outcome

        # Fallback: the timeline API can miss `reverted` events. For merged PRs,
        # look for same-repo `Revert "..."` PRs referencing this one. Recorded
        # with its detection source so a search heuristic is never mistaken
        # for a timeline event.
        if not outcome.get("reverted") and doc.get("merged"):
            try:
                revert_prs = await gc.find_revert_prs(repo_full, number, doc.get("title") or "")
                if revert_prs:
                    outcome["reverted"] = True
                    outcome["revert_detected_via"] = "search"
                    outcome["revert_prs"] = revert_prs
                    doc["outcome"] = outcome
            except Exception as exc:
                errors.append(f"revert_search: {str(exc)[:120]}")

        # Linked issues resolved from closing-keyword references in the PR body.
        try:
            doc["linked_issues"] = await ev.fetch_linked_issues(gc, repo_full, detail.get("body") or "")
        except Exception as exc:
            errors.append(f"linked_issues: {str(exc)[:120]}")
            doc["linked_issues"] = prev.get("linked_issues") or []

        # CI on the head commit — independent fetch, same preserve-on-failure rule.
        head_sha = doc.get("head_sha") or ""
        checks_status = "skipped"
        checks: list[dict] = []
        if head_sha:
            try:
                check_runs, check_trunc = await gc.fetch_check_runs(repo_full, head_sha)
                combined = await gc.fetch_commit_status(repo_full, head_sha)
                checks = ev.normalize_checks(user_id, key, head_sha, check_runs or [], combined)
                await ev.replace_pr_children(user_id, key, {"pr_checks": checks})
                checks_status = "truncated" if check_trunc else "ok"
            except Exception as exc:
                checks_status = "failed"
                errors.append(f"checks: {str(exc)[:120]}")
        doc["evidence_children"] = {**{k: v for k, v in child_status.items()}, "checks": checks_status}
        if checks_status in ("ok", "truncated"):
            doc["ci_status"] = ev.checks_summary(checks)
        elif checks_status == "failed":
            doc["ci_status"] = prev.get("ci_status") or "unknown"
        else:
            doc["ci_status"] = prev.get("ci_status") or "none"

        if child_status.get("review_comments") in ("ok", "truncated") or child_status.get("conversation_comments") in ("ok", "truncated"):
            doc["author_replied"] = ev.author_replied(
                doc.get("author") or "", reviews_docs or [], rcomments_docs, ccomments_docs
            )
        else:
            doc["author_replied"] = prev.get("author_replied", False)

        failed = [k for k, v in doc["evidence_children"].items() if v == "failed"]
        ok_any = any(v in ("ok", "truncated") for v in doc["evidence_children"].values())
        doc["evidence_status"] = (
            "complete" if not failed and ok_any
            else ("partial" if ok_any or prev.get("evidence_status") == "complete" else "failed")
        )
        doc["evidence_errors"] = errors[:10]
        doc["evidence_fetched_at"] = _now()
        doc["evidence_version"] = int(prev.get("evidence_version") or 0) + (1 if ok_any else 0)
        if doc["evidence_status"] == "complete":
            stats["prs_evidence_complete"] = stats.get("prs_evidence_complete", 0) + 1
        elif doc["evidence_status"] == "partial":
            stats["prs_evidence_partial"] = stats.get("prs_evidence_partial", 0) + 1
        else:
            stats["prs_evidence_failed"] = stats.get("prs_evidence_failed", 0) + 1
    else:
        # Incremental sync: PR unchanged — reuse stored evidence summaries.
        stats["prs_reused"] = stats.get("prs_reused", 0) + 1
        for k in (
            "files_summary", "review_summary", "ci_status", "linked_issues",
            "author_replied", "evidence_status", "evidence_errors", "outcome",
            "evidence_children", "evidence_version", "patch_samples",
        ):
            doc[k] = (existing or {}).get(k)

    await ev.upsert_pr(doc)
    return doc


# ---------- contribution projection ----------

def pr_doc_to_item(pr: dict, repo_meta: dict, eligibility_status: Optional[str], login: str) -> dict:
    """pull_requests doc → contribution-shaped dict for classify/score."""
    repo_full = pr.get("repo") or ""
    files_summary = pr.get("files_summary") or {}
    review_summary = pr.get("review_summary") or {}
    outcome = pr.get("outcome") or {}
    test_cat = (files_summary.get("categories") or {}).get("test") or {}
    number = pr.get("number")
    merged = bool(pr.get("merged")) or pr.get("state") == "merged"
    # Integration outcome: reverted/superseded are independent of technical merit.
    reverted = bool(outcome.get("reverted"))
    superseded = (not merged) and bool(outcome.get("superseded_by"))
    return {
        "dedupe_key": f"pr:{repo_full}:{number}",
        "kind": "pr",
        "repo": repo_full,
        "title": pr.get("title") or "Untitled pull request",
        "body": pr.get("body") or "",
        "number": number,
        "url": pr.get("html_url") or "",
        "state": "merged" if merged else (pr.get("state") or ""),
        "merged": merged,
        "draft": bool(pr.get("draft")),
        "labels": pr.get("labels") or [],
        "additions": pr.get("additions") or 0,
        "deletions": pr.get("deletions") or 0,
        "comments": pr.get("comment_count") or 0,
        "author_association": pr.get("author_association") or "",
        "changed_files": pr.get("changed_files") or files_summary.get("files_total") or 0,
        "commits_count": pr.get("commits_count") or 0,
        "review_count": review_summary.get("review_count", 0),
        "approvals": review_summary.get("approvals", 0),
        "change_requests": review_summary.get("change_requests", 0),
        "reviewers": review_summary.get("reviewers", 0),
        "occurred_at": _aw(pr.get("occurred_at")) or _now(),
        "pr_key": pr.get("pr_key"),
        "eligibility_status": eligibility_status,
        # --- scoring evidence ---
        "files_total": files_summary.get("files_total") or 0,
        "file_categories": files_summary.get("categories") or {},
        "patch_ratio": files_summary.get("patch_ratio") or 0.0,
        "ci_status": pr.get("ci_status") or "unknown",
        "linked_issue_count": len(pr.get("linked_issues") or []),
        "author_replied": bool(pr.get("author_replied")),
        "evidence_status": pr.get("evidence_status") or "pending",
        "reverted": reverted,
        "superseded": superseded,
        "head_repo": pr.get("head_repo") or "",
        "is_cross_repo": bool(pr.get("is_cross_repo")),
        # test change-status evidence: added > modified > removed
        "test_files_added": test_cat.get("added", 0),
        "test_files_modified": test_cat.get("modified", 0),
        "test_files_removed": test_cat.get("removed", 0),
        "patch_samples": pr.get("patch_samples") or [],
        "base_technologies": [t for t in [(repo_meta or {}).get("language") or "", *((repo_meta or {}).get("topics") or [])] if t][:6],
        **_repo_context(repo_full, login),
    }


async def _record_coverage(user_id: str, activity: dict) -> dict:
    """Persist per-window search coverage; returns summary stats."""
    windows = 0
    incomplete = 0
    for bucket, result in (activity.get("coverage") or {}).items():
        for w in result.windows:
            # "split" windows are internal bisection nodes — their left child
            # shares window_start, which collides with the unique
            # (user_id, kind, window_start) index. Coverage lives in the leaves.
            if w.status == "split":
                continue
            windows += 1
            if w.status in ("partial", "error"):
                incomplete += 1
            # Filter matches the unique index (user_id, kind, window_start):
            # partition boundaries shift between runs, so window_end can't be
            # part of the key. Leaf windows have unique starts within a run.
            await db.sync_coverage.update_one(
                {
                    "user_id": user_id,
                    "kind": bucket,
                    "window_start": w.start.isoformat(),
                },
                {
                    "$set": {
                        "user_id": user_id,
                        "kind": bucket,
                        "window_start": w.start.isoformat(),
                        "window_end": w.end.isoformat(),
                        "total_count": w.total_count,
                        "fetched": w.fetched,
                        "status": w.status,
                        "error": w.error,
                        "updated_at": _now(),
                    }
                },
                upsert=True,
            )
    return {"search_windows": windows, "search_windows_incomplete": incomplete}


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


async def _upsert_contribution(user_id: str, doc: dict) -> str:
    """Idempotent contribution write: returns 'inserted' | 'updated'."""
    existing = await db.contributions.find_one(
        {"user_id": user_id, "dedupe_key": doc["dedupe_key"]}, {"id": 1}
    )
    if existing:
        doc["id"] = existing["id"]
        await db.contributions.update_one(
            {"user_id": user_id, "dedupe_key": doc["dedupe_key"]},
            {"$set": doc},
        )
        return "updated"
    doc.setdefault("id", str(uuid.uuid4()))
    await db.contributions.insert_one(doc)
    return "inserted"


async def _run_job(job_id: str, user_id: str, mode: str) -> None:
    stats: dict[str, int] = {}
    try:
        user = await db.users.find_one({"id": user_id})
        if not user:
            raise RuntimeError("user vanished mid-job")
        login = user.get("login") or "developer"
        raw: list[dict] = []
        pr_items: list[dict] = []

        if mode == "full":
            await _set_stage(job_id, "fetch", "Fetching GitHub activity", 5, stats)
            if user.get("github_token"):
                gc = gh.GitHubClient(user["github_token"])
                try:
                    me = await gc.authenticated_user()
                    login = me.get("login") or login
                    # Keep the numeric GitHub id fresh for ownership checks.
                    await db.users.update_one(
                        {"id": user_id},
                        {"$set": {"github_id": me.get("github_id"), "login": login}},
                    )
                    try:
                        # Role-aware org memberships: admin = controlled org,
                        # member = independent org the developer belongs to.
                        org_roles = await gc.list_org_memberships()
                        user_orgs = set(org_roles.keys())
                    except Exception as exc:
                        logger.warning("org membership list failed: %s", exc)
                        org_roles = {}
                        try:
                            user_orgs = set(await gc.list_user_orgs())
                        except Exception:
                            user_orgs = set()
                    excluded = set(user.get("excluded_repos") or [])

                    # --- discovery: partitioned search across all history ---
                    activity = await gc.discover_activity(login)
                    cov = await _record_coverage(user_id, activity)
                    stats.update(cov)
                    stats["prs_discovered"] = len(activity["authored_prs"])
                    stats["issues_discovered"] = len(activity["authored_issues"])
                    stats["reviewed_prs_discovered"] = len(activity["reviewed_prs"])
                    stats["search_incomplete"] = 1 if activity["truncated"] else 0

                    # repo metadata for language/topics context (best effort)
                    repo_meta: dict[str, dict] = {}
                    try:
                        owned, repos_trunc = await gc.fetch_repos(login)
                        for r in owned:
                            if r.get("full_name"):
                                repo_meta[r["full_name"]] = r
                        stats["repos_visible"] = len(owned)
                        stats["repos_truncated"] = 1 if repos_trunc else 0
                    except Exception as exc:
                        logger.warning("repo metadata fetch failed: %s", exc)
                    for name in activity["repos"]:
                        repo_meta.setdefault(name, {"full_name": name, "language": "", "topics": []})
                    stats["repos_discovered"] = len(repo_meta)

                    # --- eligibility for repos with authored PRs; under
                    # oss_only we must verify EVERY discovered repo ---
                    oss_only_pre = bool(user.get("oss_only"))
                    assess_repos = (
                        sorted(r for r in activity["repos"] if r not in excluded)
                        if oss_only_pre
                        else sorted({e["repo"] for e in activity["authored_prs"] if e.get("repo")})
                    )
                    pr_repos = sorted({e["repo"] for e in activity["authored_prs"] if e.get("repo")})
                    sem = asyncio.Semaphore(EVIDENCE_CONCURRENCY)

                    async def assess(repo_full: str):
                        async with sem:
                            return repo_full, await elig.ensure_repo_eligibility(
                                gc, user_id, login, user_orgs, repo_full, org_roles=org_roles
                            )

                    elig_results = await asyncio.gather(*[assess(r) for r in assess_repos])
                    repo_eligibility = dict(elig_results)
                    for status in repo_eligibility.values():
                        key = f"repos_{status.lower()}"
                        stats[key] = stats.get(key, 0) + 1

                    # --- open-source-only mode: keep only repos the user doesn't
                    # own, collaborate on, or belong to the owning org of ---
                    oss_only = oss_only_pre
                    oss_allowed: Optional[set[str]] = None
                    if oss_only:
                        allowed: set[str] = set()
                        async for d in db.repo_eligibility.find(
                            {"user_id": user_id, "repo": {"$in": assess_repos}},
                            {"repo": 1, "status": 1, "is_collaborator": 1, "user_is_org_member": 1, "_id": 0},
                        ):
                            if (
                                d.get("status") == elig.ELIGIBLE_EXTERNAL
                                and not d.get("is_collaborator")
                                and not d.get("user_is_org_member")
                            ):
                                allowed.add(d["repo"])
                        oss_allowed = allowed
                        stats["oss_only_repos"] = len(allowed)
                        stats["oss_only_skipped"] = len(assess_repos) - len(allowed)

                    # --- PR evidence ingestion (incremental) ---
                    total = len(activity["authored_prs"])
                    for i, entry in enumerate(activity["authored_prs"]):
                        if not entry.get("repo") or not entry.get("number"):
                            continue
                        if entry["repo"] in excluded:
                            stats["prs_skipped_excluded"] = stats.get("prs_skipped_excluded", 0) + 1
                            continue
                        if oss_allowed is not None and entry["repo"] not in oss_allowed:
                            stats["prs_skipped_oss_only"] = stats.get("prs_skipped_oss_only", 0) + 1
                            continue
                        doc = await ingest_pr(gc, user_id, entry, stats)
                        if doc:
                            meta = repo_meta.get(doc.get("repo") or "") or {}
                            pr_items.append(
                                pr_doc_to_item(doc, meta, repo_eligibility.get(doc.get("repo") or ""), login)
                            )
                        await _set_stage(
                            job_id, "fetch", f"PR evidence {i + 1}/{total}",
                            STAGE_RANGES["fetch"][0] + int(35 * (i + 1) / max(1, total)), stats,
                        )
                    raw.extend(pr_items)

                    # --- authored issues (detail fetch for full fidelity) ---
                    issue_sem = asyncio.Semaphore(ISSUE_FETCH_CONCURRENCY)

                    async def fetch_issue_item(entry: dict):
                        async with issue_sem:
                            repo_full = entry["repo"]
                            if repo_full in excluded or not entry.get("number"):
                                return None
                            if oss_allowed is not None and repo_full not in oss_allowed:
                                return None
                            try:
                                issue = await gc.fetch_issue(repo_full, entry["number"])
                            except Exception as exc:
                                logger.warning("issue fetch failed %s#%s: %s", repo_full, entry.get("number"), exc)
                                return None
                            if not issue or "pull_request" in issue:
                                return None
                            meta = repo_meta.get(repo_full) or {}
                            base_techs = [t for t in [meta.get("language") or "", *(meta.get("topics") or [])] if t]
                            return norm_issue(issue, repo_full, base_techs, login)

                    issue_items = [r for r in await asyncio.gather(*[fetch_issue_item(e) for e in activity["authored_issues"]]) if r]
                    raw.extend(issue_items)
                    stats["issues_ingested"] = len(issue_items)

                    # --- authored commits via commit search (default-branch coverage) ---
                    try:
                        commit_result = await gc.search_commits(login)
                        await _record_coverage_for(user_id, "commits", commit_result)
                        stats["commit_windows_incomplete"] = 1 if commit_result.truncated else 0
                        for item in commit_result.to_list():
                            repo_full = ((item.get("repository") or {}).get("full_name")) or ""
                            if not repo_full or repo_full in excluded:
                                continue
                            if oss_allowed is not None and repo_full not in oss_allowed:
                                continue
                            meta = repo_meta.get(repo_full) or {}
                            base_techs = [t for t in [meta.get("language") or "", *(meta.get("topics") or [])] if t]
                            c = norm_commit_search(item, login, base_techs)
                            if c:
                                raw.append(c)
                        stats["commits_found"] = len(raw) - len(pr_items) - len(issue_items)
                    except Exception as exc:
                        logger.warning("commit search failed: %s", exc)
                        stats["commits_failed"] = 1

                    # --- reviews the user wrote on others' PRs ---
                    try:
                        reviewed = await gc.fetch_reviewed_prs_reviews(activity["reviewed_prs"], login)
                        for rv in reviewed:
                            repo_full = rv.get("_repo_full") or ""
                            if oss_allowed is not None and repo_full not in oss_allowed:
                                continue
                            meta = repo_meta.get(repo_full) or {}
                            base_techs = [t for t in [meta.get("language") or "", *(meta.get("topics") or [])] if t]
                            raw.append(norm_review(rv, repo_full, rv.get("_pr_number") or 0, base_techs, login))
                        stats["reviews_written"] = len(reviewed)
                    except Exception as exc:
                        logger.warning("reviewed-by fetch failed: %s", exc)
                        stats["reviews_failed"] = 1
                finally:
                    await gc.close()
            else:
                # Offline / demo mode: analysis re-uses what is already stored.
                stats["repos_fetched"] = 0
                await asyncio.sleep(0.8)  # let the stepper animate
            stats["contributions_found"] = len(raw)
        else:
            stats["repos_fetched"] = 0
            stats["new_contributions"] = 0

        # ---------- classify new items, rescore everything ----------
        await _set_stage(job_id, "classify", "AI classification" if mode == "full" else "Using cached classifications", 60 if mode == "full" else 80, stats)
        existing_docs = {
            d["dedupe_key"]: d
            async for d in db.contributions.find({"user_id": user_id}, {"dedupe_key": 1, "category": 1, "complexity": 1, "technologies": 1, "summary": 1})
        }
        new_items = [r for r in raw if r["dedupe_key"] not in existing_docs]
        stats["new_contributions"] = len(new_items)
        stats["refreshed_contributions"] = len(raw) - len(new_items)

        classified = 0
        updated = 0
        if new_items:
            for i in range(0, len(new_items), BATCH_SIZE):
                chunk = new_items[i : i + BATCH_SIZE]
                results = await classify_batch(chunk)
                docs = []
                for item, res in zip(chunk, results):
                    techs = list(dict.fromkeys([*item.pop("base_technologies", []), *res["technologies"]]))[:6]
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
                            "confidence": scored["confidence"],
                            "dimensions": scored["dimensions"],
                            "summary": res["summary"] or item["title"],
                            "analyzed": True,
                            "analyzed_at": _now(),
                        }
                    )
                for d in docs:
                    try:
                        outcome = await _upsert_contribution(user_id, d)
                        classified += 1 if outcome == "inserted" else 0
                        updated += 1 if outcome == "updated" else 0
                    except Exception as exc:
                        logger.warning("contribution upsert failed %s: %s", d.get("dedupe_key"), exc)
                stats["classified"] = classified
                stats["refreshed"] = updated
                await _set_stage(
                    job_id, "classify", "AI classification",
                    60 + int(20 * min(1, (i + len(chunk)) / max(1, len(new_items)))), stats,
                )
        else:
            await _set_stage(job_id, "classify", "Rescoring existing contributions", 75, stats)

        # Refresh factual fields + rescore for contributions seen before (state
        # changes like merge/close must propagate without another LLM pass).
        if mode == "full" and raw:
            refreshed = 0
            for item in raw:
                prev = existing_docs.get(item["dedupe_key"])
                if not prev:
                    continue
                scored = score_contribution(
                    {**item, "complexity": prev.get("complexity") or "Medium", "category": prev.get("category")}
                )
                await db.contributions.update_one(
                    {"user_id": user_id, "dedupe_key": item["dedupe_key"]},
                    {
                        "$set": {
                            "state": item.get("state", ""),
                            "merged": item.get("merged", False),
                            "draft": item.get("draft", False),
                            "additions": item.get("additions", 0),
                            "deletions": item.get("deletions", 0),
                            "changed_files": item.get("changed_files", 0),
                            "review_count": item.get("review_count", 0),
                            "approvals": item.get("approvals", 0),
                            "change_requests": item.get("change_requests", 0),
                            "reviewers": item.get("reviewers", 0),
                            "comments": item.get("comments", 0),
                            "eligibility_status": item.get("eligibility_status"),
                            "files_total": item.get("files_total", 0),
                            "file_categories": item.get("file_categories") or {},
                            "patch_ratio": item.get("patch_ratio", 0.0),
                            "ci_status": item.get("ci_status") or "unknown",
                            "linked_issue_count": item.get("linked_issue_count", 0),
                            "author_replied": item.get("author_replied", False),
                            "evidence_status": item.get("evidence_status") or "pending",
                            "reverted": item.get("reverted", False),
                            "superseded": item.get("superseded", False),
                            "test_files_added": item.get("test_files_added", 0),
                            "test_files_modified": item.get("test_files_modified", 0),
                            "test_files_removed": item.get("test_files_removed", 0),
                            "impact_score": scored["impact_score"],
                            "confidence": scored["confidence"],
                            "dimensions": scored["dimensions"],
                            "occurred_at": item.get("occurred_at"),
                            "analyzed": True,
                            "analyzed_at": _now(),
                        }
                    },
                )
                refreshed += 1
            stats["rescored"] = refreshed

        if mode == "full":
            await db.users.update_one({"id": user_id}, {"$set": {"last_synced_at": _now()}})

        await _set_stage(job_id, "skills", "Skill aggregation", 85 if mode == "full" else 88, stats)
        skills = await rebuild_skills(user_id)
        stats["skills"] = len(skills)

        await _set_stage(job_id, "insights", "Generating insights", 95 if mode == "full" else 95, stats)
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


async def _record_coverage_for(user_id: str, kind: str, result: gh.PartitionedSearchResult) -> None:
    for w in result.windows:
        if w.status == "split":
            continue  # internal bisection node — see _record_coverage
        await db.sync_coverage.update_one(
            {"user_id": user_id, "kind": kind, "window_start": w.start.isoformat()},
            {
                "$set": {
                    "user_id": user_id,
                    "kind": kind,
                    "window_start": w.start.isoformat(),
                    "window_end": w.end.isoformat(),
                    "total_count": w.total_count,
                    "fetched": w.fetched,
                    "status": w.status,
                    "error": w.error,
                    "updated_at": _now(),
                }
            },
            upsert=True,
        )
