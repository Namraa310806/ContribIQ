"""PR evidence reads: per-PR detail (files, reviews, comments, checks) and sync coverage."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from lib.db import db
from lib.session import require_user
from models.contribiq import (
    CoverageResponse,
    PrCheck,
    PrComment,
    PrDetailResponse,
    PrFile,
    PrReview,
    PullRequestEvidence,
    RepoEligibilityInfo,
    SyncWindow,
)

router = APIRouter(tags=["prs"])


def _aw(dt):
    if dt is None:
        return None
    from datetime import timezone
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/prs", response_model=PrDetailResponse)
async def pr_detail(request: Request, repo: str = Query(..., min_length=3, max_length=200), number: int = Query(..., ge=1)):
    """Full evidence for one authored PR: metadata + files + reviews + checks.

    `repo` is "owner/name"; `number` is the PR number.
    """
    user = await require_user(request)
    key = f"{repo}#{number}"
    pr = await db.pull_requests.find_one({"user_id": user["id"], "pr_key": key})
    if not pr:
        raise HTTPException(status_code=404, detail="PR evidence not found — run an analysis first")

    elig_doc = await db.repo_eligibility.find_one({"user_id": user["id"], "repo": repo})
    eligibility_status = None
    eligibility_reason = None
    if elig_doc:
        eligibility_status = elig_doc.get("status")
        eligibility_reason = elig_doc.get("reason")
    pr = dict(pr)
    pr["eligibility_status"] = eligibility_status
    pr["eligibility_reason"] = eligibility_reason
    for k in ("created_at", "updated_at", "closed_at", "merged_at", "occurred_at", "evidence_fetched_at"):
        pr[k] = _aw(pr.get(k))

    files = await db.pr_files.find({"user_id": user["id"], "pr_key": key}).sort("path", 1).to_list(500)
    reviews = await db.pr_reviews.find({"user_id": user["id"], "pr_key": key}).sort("submitted_at", 1).to_list(500)
    checks = await db.pr_checks.find({"user_id": user["id"], "pr_key": key}).to_list(200)
    rcomments = await db.pr_review_comments.find({"user_id": user["id"], "pr_key": key}).to_list(500)
    ccomments = await db.pr_comments.find({"user_id": user["id"], "pr_key": key}).to_list(500)
    for r in reviews:
        r["submitted_at"] = _aw(r.get("submitted_at"))
    for c in checks:
        c["completed_at"] = _aw(c.get("completed_at"))
        c["started_at"] = _aw(c.get("started_at"))

    # Unified discussion thread: inline review comments + PR conversation,
    # chronological — the "maintainer feedback" surface.
    comment_docs = []
    for c in rcomments:
        comment_docs.append({**c, "kind": "review"})
    for c in ccomments:
        comment_docs.append({**c, "kind": "conversation"})
    comment_docs.sort(key=lambda c: (_aw(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp())
    for c in comment_docs:
        c["created_at"] = _aw(c.get("created_at"))

    return PrDetailResponse(
        pr=PullRequestEvidence(**{k: v for k, v in pr.items() if k != "_id"}),
        files=[PrFile(**{k: v for k, v in f.items() if k not in ("_id", "user_id", "fetched_at")}) for f in files],
        reviews=[PrReview(**{k: v for k, v in r.items() if k not in ("_id", "user_id", "fetched_at")}) for r in reviews],
        comments=[
            PrComment(**{k: v for k, v in c.items() if k not in ("_id", "user_id", "fetched_at", "comment_id", "updated_at")})
            for c in comment_docs
        ],
        checks=[PrCheck(**{k: v for k, v in c.items() if k not in ("_id", "user_id", "fetched_at")}) for c in checks],
    )


@router.get("/prs/eligibility", response_model=list[RepoEligibilityInfo])
async def repo_eligibility(request: Request):
    """All verified repository-ownership decisions for this user."""
    user = await require_user(request)
    docs = await db.repo_eligibility.find({"user_id": user["id"]}).sort("repo", 1).to_list(1000)
    return [
        RepoEligibilityInfo(
            repo=d.get("repo", ""),
            status=d.get("status", "UNKNOWN"),
            reason=d.get("reason", ""),
            confidence=d.get("confidence", 0.0),
            owner=d.get("owner", ""),
            owner_type=d.get("owner_type", ""),
            is_fork=bool(d.get("is_fork")),
            upstream=d.get("upstream", ""),
            user_is_org_member=bool(d.get("user_is_org_member")),
            verified_at=_aw(d.get("verified_at")),
        )
        for d in docs
    ]


@router.get("/coverage", response_model=CoverageResponse)
async def coverage(request: Request):
    """Honest data-coverage report: search windows, eligibility verdicts,
    evidence completeness. Incomplete coverage is surfaced, never hidden."""
    user = await require_user(request)
    uid = user["id"]

    windows_docs = await db.sync_coverage.find({"user_id": uid}).sort("kind", 1).to_list(2000)
    windows = [
        SyncWindow(
            kind=w.get("kind", ""),
            window_start=w.get("window_start", ""),
            window_end=w.get("window_end", ""),
            total_count=w.get("total_count", 0),
            fetched=w.get("fetched", 0),
            status=w.get("status", ""),
            error=w.get("error"),
            updated_at=_aw(w.get("updated_at")),
        )
        for w in windows_docs
    ]
    # "split" windows are internal bisection nodes — resolved via their children.
    complete = sum(1 for w in windows if w.status in ("complete", "split"))
    incomplete = sum(1 for w in windows if w.status in ("partial", "error"))

    elig_counts: dict[str, int] = {}
    async for d in db.repo_eligibility.find({"user_id": uid}, {"status": 1, "_id": 0}):
        s = d.get("status") or "UNKNOWN"
        elig_counts[s] = elig_counts.get(s, 0) + 1

    prs_by_evidence: dict[str, int] = {}
    prs_total = 0
    async for d in db.pull_requests.find({"user_id": uid}, {"evidence_status": 1, "_id": 0}):
        prs_total += 1
        s = d.get("evidence_status") or "pending"
        prs_by_evidence[s] = prs_by_evidence.get(s, 0) + 1

    user_doc = await db.users.find_one({"id": uid}, {"last_synced_at": 1})
    note = ""
    if incomplete:
        note = f"{incomplete} search window(s) did not complete — historical coverage may be partial."
    elif windows:
        note = "Search coverage complete within GitHub API limits."
    else:
        note = "No sync coverage recorded yet — run an analysis."

    return CoverageResponse(
        last_synced_at=_aw((user_doc or {}).get("last_synced_at")),
        windows=windows,
        windows_complete=complete,
        windows_incomplete=incomplete,
        eligibility=elig_counts,
        prs_by_evidence=prs_by_evidence,
        prs_total=prs_total,
        coverage_note=note,
    )
