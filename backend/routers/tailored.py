"""Job-tailored insight sets: create (LLM), list, delete — each job saved as its own set."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from lib.db import db
from lib.session import require_user
from models.contribiq import CreateTailoredRequest, Insight, TailoredListResponse, TailoredSet
from services.tailor_gen import generate_tailored

router = APIRouter(prefix="/tailored", tags=["tailored"])


def _to_model(doc: dict) -> TailoredSet:
    uid = doc["user_id"]
    created = doc.get("created_at")
    fill = lambda items: [  # noqa: E731
        Insight(**{**i, "user_id": uid, "created_at": created, "pinned": False}) for i in items
    ]
    return TailoredSet(
        id=doc["id"],
        user_id=uid,
        title=doc["title"],
        job_description=doc["job_description"],
        match_summary=doc.get("match_summary", ""),
        bullets=fill(doc.get("bullets", [])),
        stars=fill(doc.get("stars", [])),
        created_at=created,
    )


@router.get("", response_model=TailoredListResponse)
async def list_sets(request: Request):
    user = await require_user(request)
    docs = await db.tailored_sets.find({"user_id": user["id"]}).sort("created_at", -1).to_list(100)
    return TailoredListResponse(items=[_to_model(d) for d in docs])


@router.post("", response_model=TailoredSet)
async def create_set(body: CreateTailoredRequest, request: Request):
    user = await require_user(request)
    uid = user["id"]
    contributions = await db.contributions.find({"user_id": uid}).to_list(500)
    if not contributions:
        raise HTTPException(status_code=400, detail="Run an analysis first — there is no evidence to tailor yet")
    skills = await db.skills.find({"user_id": uid}).sort("score", -1).to_list(30)
    result = await generate_tailored(body.job_description, contributions, skills)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "title": body.title.strip(),
        "job_description": body.job_description.strip(),
        "match_summary": result["match_summary"],
        "bullets": result["bullets"],
        "stars": result["stars"],
        "created_at": datetime.now(timezone.utc),
    }
    await db.tailored_sets.insert_one(dict(doc))
    return _to_model(doc)


@router.delete("/{set_id}", status_code=204)
async def delete_set(set_id: str, request: Request):
    """Explicit user action: removes one saved set, scoped to its owner."""
    user = await require_user(request)
    result = await db.tailored_sets.delete_one({"id": set_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tailored set not found")
    return None
