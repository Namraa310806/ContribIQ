"""Account settings: weekly auto-sync switch and the privacy purge."""

from fastapi import APIRouter, Request

from lib.db import db
from lib.session import require_user, to_public
from models.contribiq import AutoSyncRequest, DeleteDataResponse, UserPublic

router = APIRouter(tags=["settings"])

# Derived collections only — the account itself survives so the session stays valid.
_DERIVED = ("contributions", "skills", "insights", "jobs", "share_tokens", "tailored_sets")


@router.put("/settings/auto-sync", response_model=UserPublic)
async def set_auto_sync(body: AutoSyncRequest, request: Request):
    user = await require_user(request)
    await db.users.update_one({"id": user["id"]}, {"$set": {"auto_sync": body.enabled}})
    user["auto_sync"] = body.enabled
    return UserPublic(**to_public(user))


@router.delete("/user/data", response_model=DeleteDataResponse)
async def delete_my_data(request: Request):
    """Explicit, user-triggered purge: every GitHub-derived document for this user."""
    user = await require_user(request)
    uid = user["id"]
    deleted: dict[str, int] = {}
    for coll in _DERIVED:
        result = await db[coll].delete_many({"user_id": uid})
        deleted[coll] = result.deleted_count
    await db.users.update_one({"id": uid}, {"$set": {"last_synced_at": None}})
    return DeleteDataResponse(user_id=uid, deleted=deleted)
