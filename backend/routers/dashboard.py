"""Dashboard reads: overview stats, contributions, skills, insights (pin / regenerate)."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi import Query as QueryParam

from lib.db import db
from lib.session import require_user
from models.contribiq import (
    AnalysisJob,
    Contribution,
    ContributionPage,
    Insight,
    InsightsResponse,
    OverviewStats,
    PinRequest,
    Skill,
    SkillsResponse,
    StartAnalysisResponse,
)
from services import pipeline

router = APIRouter(tags=["dashboard"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aw(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/overview", response_model=OverviewStats)
async def overview(request: Request):
    user = await require_user(request)
    uid = user["id"]
    contributions = await db.contributions.find({"user_id": uid}).to_list(5000)
    skills = await db.skills.find({"user_id": uid}).sort("score", -1).to_list(50)
    last_job = await db.jobs.find_one({"user_id": uid, "status": "completed"}, sort=[("completed_at", -1)])
    last_analyzed = (last_job or {}).get("completed_at") or user.get("last_synced_at")
    merged = sum(1 for c in contributions if c.get("state") == "merged")
    reviews = sum(1 for c in contributions if c.get("kind") == "review")
    authored_prs = [c for c in contributions if c.get("kind") == "pr"]
    merged_prs = sum(1 for c in authored_prs if c.get("merged") or c.get("state") == "merged")
    external_prs = sum(1 for c in authored_prs if c.get("is_own_repo") is False)
    # Collaboration index: mean of the collaboration dimension over PR + review evidence.
    collab_vals = [
        (c.get("dimensions") or {}).get("collaboration")
        for c in contributions
        if c.get("kind") in ("pr", "review") and (c.get("dimensions") or {}).get("collaboration") is not None
    ]
    collaboration_score = round(sum(collab_vals) / len(collab_vals)) if collab_vals else 0
    # Consistency: sustained cadence across repos and time (deterministic, explainable).
    dates = sorted(_aw(c.get("occurred_at")) for c in contributions if _aw(c.get("occurred_at")))
    consistency_score = 0
    if dates:
        span_days = max(1, (dates[-1] - dates[0]).days)
        span_weeks = span_days / 7
        repos_n = len({c.get("repo") for c in contributions})
        weekly_cadence = len(contributions) / max(1, span_weeks)
        consistency_score = min(100, round(repos_n * 8 + min(50, weekly_cadence * 10) + min(20, span_weeks)))
    avg = round(sum(c.get("impact_score", 0) for c in contributions) / len(contributions)) if contributions else 0
    return OverviewStats(
        total_contributions=len(contributions),
        authored_prs=len(authored_prs),
        merged_prs=merged_prs,
        external_prs=external_prs,
        prs_reviewed=reviews,
        top_skill=skills[0]["name"] if skills else "",
        avg_impact=avg,
        collaboration_score=collaboration_score,
        consistency_score=consistency_score,
        categories_used=len({c.get("category") for c in contributions}),
        evidence_count=merged + reviews,
        repos_count=len({c.get("repo") for c in contributions}),
        last_analyzed_at=_aw(last_analyzed),
        has_data=bool(contributions),
    )


@router.get("/contributions", response_model=ContributionPage)
async def contributions(
    request: Request,
    kind: Optional[str] = QueryParam(None),
    category: Optional[str] = QueryParam(None),
    q: Optional[str] = QueryParam(None),
    limit: int = QueryParam(500, ge=1, le=1000),
):
    user = await require_user(request)
    uid = user["id"]
    all_docs = await db.contributions.find({"user_id": uid}).sort("occurred_at", -1).to_list(5000)
    facets = {
        "kinds": sorted({d.get("kind", "pr") for d in all_docs}),
        "categories": sorted({d.get("category", "Other") for d in all_docs}),
        "repos": sorted({d.get("repo", "") for d in all_docs if d.get("repo")}),
    }
    needle = (q or "").strip().lower()
    items = []
    for d in all_docs:
        if kind and d.get("kind") != kind:
            continue
        if category and d.get("category") != category:
            continue
        if needle and needle not in f"{d.get('title', '')} {d.get('summary', '')} {d.get('repo', '')}".lower():
            continue
        items.append(d)
    total = len(items)
    return ContributionPage(
        items=[Contribution(**d) for d in items[:limit]],
        total=total,
        facets=facets,
    )


@router.get("/skills", response_model=SkillsResponse)
async def skills(request: Request):
    user = await require_user(request)
    docs = await db.skills.find({"user_id": user["id"]}).sort("score", -1).to_list(200)
    return SkillsResponse(items=[Skill(**d) for d in docs])


@router.get("/insights", response_model=InsightsResponse)
async def insights(request: Request):
    user = await require_user(request)
    docs = await db.insights.find({"user_id": user["id"]}).sort("created_at", -1).to_list(200)
    order = {"recruiter_summary": 0, "bullet": 1, "star": 2}
    docs.sort(key=lambda d: (order.get(d.get("kind"), 3), -(d.get("pinned", False))))
    return InsightsResponse(items=[Insight(**d) for d in docs])


@router.post("/insights/{insight_id}/pin", response_model=Insight)
async def pin_insight(insight_id: str, body: PinRequest, request: Request):
    user = await require_user(request)
    doc = await db.insights.find_one_and_update(
        {"id": insight_id, "user_id": user["id"]},
        {"$set": {"pinned": body.pinned}},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Insight not found")
    doc["pinned"] = body.pinned
    return Insight(**doc)


@router.post("/insights/regenerate", response_model=StartAnalysisResponse)
async def regenerate_insights(request: Request):
    """Re-run the pipeline in insights-only mode (skips fetching/classifying)."""
    user = await require_user(request)
    job = await pipeline.start_job(user, mode="insights")
    return StartAnalysisResponse(job=AnalysisJob(**job))
