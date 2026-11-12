"""Recruiter share links: create / inspect / revoke (authed) and the public dossier view."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi import Query as QueryParam

from lib.db import db
from lib.demo import DEMO_SHARE_TOKEN
from lib.session import require_user
from models.contribiq import (
    CreateShareRequest,
    PublicRecruiterView,
    RecruiterHighlight,
    RecruiterSkill,
    ShareInfo,
    ShareStateResponse,
)

router = APIRouter(tags=["share"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aw(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _active_token_filter(user_id: str) -> dict:
    # The permanent demo dossier link is not user-managed — keep it out of share management.
    return {"user_id": user_id, "revoked": False, "expires_at": {"$gt": _now()}, "token": {"$ne": DEMO_SHARE_TOKEN}}


def _managed_filter(user_id: str) -> dict:
    return {"user_id": user_id, "revoked": False, "token": {"$ne": DEMO_SHARE_TOKEN}}


@router.get("/share", response_model=ShareStateResponse)
async def my_share(request: Request):
    user = await require_user(request)
    doc = await db.share_tokens.find_one(
        _active_token_filter(user["id"]), sort=[("created_at", -1)]
    )
    if not doc:
        return ShareStateResponse(share=None)
    return ShareStateResponse(
        share=ShareInfo(token=doc["token"], path=f"/r/{doc['token']}", expires_at=_aw(doc["expires_at"]), revoked=False)
    )


@router.post("/share", response_model=ShareInfo)
async def create_share(body: CreateShareRequest, request: Request):
    user = await require_user(request)
    days = body.days if body.days in (7, 30, 90) else 30
    await db.share_tokens.update_many(_managed_filter(user["id"]), {"$set": {"revoked": True}})  # one active link at a time
    token = secrets.token_urlsafe(18)
    now = _now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "token": token,
        "created_at": now,
        "expires_at": now + timedelta(days=days),
        "revoked": False,
    }
    await db.share_tokens.insert_one(doc)
    return ShareInfo(token=token, path=f"/r/{token}", expires_at=doc["expires_at"], revoked=False)


@router.delete("/share", status_code=204)
async def revoke_share(request: Request):
    user = await require_user(request)
    await db.share_tokens.update_many(_managed_filter(user["id"]), {"$set": {"revoked": True}})
    return None


@router.get("/share/{token}", response_model=PublicRecruiterView)
async def public_dossier(token: str, request: Request):
    """Public, view-only recruiter dossier — no auth. 410 when expired, 404 when revoked/unknown."""
    doc = await db.share_tokens.find_one({"token": token})
    if not doc or doc.get("revoked"):
        raise HTTPException(status_code=404, detail="This dossier link is not available")
    expires = _aw(doc.get("expires_at"))
    if expires is None or expires < _now():
        raise HTTPException(status_code=410, detail="This dossier link has expired")

    uid = doc["user_id"]
    user = await db.users.find_one({"id": uid})
    if not user:
        raise HTTPException(status_code=404, detail="This dossier link is not available")

    summary_doc = await db.insights.find_one(
        {"user_id": uid, "kind": "recruiter_summary"}, sort=[("created_at", -1)]
    )
    skill_docs = await db.skills.find({"user_id": uid}).sort("score", -1).to_list(8)
    contributions = await db.contributions.find({"user_id": uid}).sort("impact_score", -1).to_list(100)
    by_id = {c["id"]: c for c in contributions}

    pinned_ids: list[str] = []
    pinned_docs = await db.insights.find({"user_id": uid, "pinned": True}).to_list(50)
    for p in pinned_docs:
        for ev in p.get("evidence", []):
            cid = ev.get("contribution_id")
            if cid in by_id and cid not in pinned_ids:
                pinned_ids.append(cid)

    highlights: list[RecruiterHighlight] = []
    seen: set[str] = set()
    for cid in pinned_ids + [c["id"] for c in contributions]:
        if len(highlights) >= 8:
            break
        c = by_id.get(cid)
        if not c or c["id"] in seen:
            continue
        seen.add(c["id"])
        highlights.append(
            RecruiterHighlight(
                contribution_id=c["id"],
                kind=c.get("kind", "pr"),
                title=c.get("title", ""),
                repo=c.get("repo", ""),
                summary=c.get("summary", ""),
                category=c.get("category", "Other"),
                impact_score=c.get("impact_score", 0),
                url=c.get("url", ""),
            )
        )

    # Rank highlights: merged external PRs first (strongest collaboration evidence),
    # then other high-impact items — pinned evidence still takes precedence via pinned_ids.
    def _hl_rank(c: dict) -> tuple:
        is_external_merged_pr = (
            c.get("kind") == "pr"
            and c.get("merged")
            and (
                c.get("eligibility_status") == "ELIGIBLE_EXTERNAL"
                or (not c.get("eligibility_status") and c.get("is_own_repo") is False)
            )
        )
        return (0 if is_external_merged_pr else 1, -(c.get("impact_score") or 0))

    contributions.sort(key=_hl_rank)

    total = len(contributions)
    prs = [c for c in contributions if c.get("kind") == "pr"]
    merged = sum(1 for c in prs if c.get("merged") or c.get("state") == "merged")
    external = sum(
        1 for c in prs
        if (c.get("eligibility_status") == "ELIGIBLE_EXTERNAL")
        or (not c.get("eligibility_status") and c.get("is_own_repo") is False)
    )
    reviewed = sum(1 for c in contributions if c.get("kind") == "review")
    collab_vals = [
        (c.get("dimensions") or {}).get("collaboration")
        for c in contributions
        if c.get("kind") in ("pr", "review") and (c.get("dimensions") or {}).get("collaboration") is not None
    ]
    avg = round(sum(c.get("impact_score", 0) for c in contributions) / total) if total else 0
    return PublicRecruiterView(
        name=user.get("name") or user.get("login") or "Developer",
        login=user.get("login") or "",
        avatar_url=user.get("avatar_url") or "",
        profile_url=user.get("profile_url") or "",
        is_demo=bool(user.get("is_demo")),
        summary=(summary_doc or {}).get("content", ""),
        skills=[
            RecruiterSkill(
                name=s.get("name", ""),
                confidence=s.get("confidence", "Low"),
                score=s.get("score", 0),
                evidence_count=s.get("evidence_count", 0),
            )
            for s in skill_docs
        ],
        highlights=highlights,
        stats={
            "total_contributions": total,
            "authored_prs": len(prs),
            "merged_prs": merged,
            "external_prs": external,
            "prs_reviewed": reviewed,
            "collaboration_score": round(sum(collab_vals) / len(collab_vals)) if collab_vals else 0,
            "avg_impact": avg,
            "repos": len({c.get("repo") for c in contributions}),
            "categories": len({c.get("category") for c in contributions}),
        },
        expires_at=_aw(doc["expires_at"]),
    )
