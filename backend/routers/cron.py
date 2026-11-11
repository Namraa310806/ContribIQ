"""Platform cron webhook: daily check that re-analyzes opted-in users due for their weekly sync."""

import asyncio
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pymongo.errors import DuplicateKeyError

from lib.db import db
from services import pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cron", tags=["cron"])

SYNC_EVERY = timedelta(days=7)
_running: set[asyncio.Task] = set()


def _authorized(request: Request) -> bool:
    secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
    header = request.headers.get("authorization") or ""
    if not secret or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer "):].encode(), secret.encode())


async def run_weekly_sync() -> int:
    """Sequentially re-analyze every opted-in GitHub user whose last sync is 7+ days old."""
    cutoff = datetime.now(timezone.utc) - SYNC_EVERY
    query = {
        "auto_sync": True,
        "github_token": {"$type": "string"},
        "$or": [{"last_synced_at": None}, {"last_synced_at": {"$lt": cutoff}}],
    }
    started = 0
    async for user in db.users.find(query):
        try:
            job = await pipeline.start_job(user, mode="full")
            task = pipeline._tasks.get(job["id"])
            if task:
                await task  # one at a time keeps GitHub + LLM usage gentle
            started += 1
        except Exception:
            logger.exception("weekly sync failed for user %s", user.get("id"))
    logger.info("weekly sync: %s users re-analyzed", started)
    return started


@router.post("/weekly-sync")
async def weekly_sync(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        envelope = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid body")
    if not isinstance(envelope, dict):
        raise HTTPException(status_code=400, detail="Invalid body")
    run_id = request.headers.get("x-webhook-id") or envelope.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run id")
    try:
        await db.cron_runs.insert_one(
            {"run_id": str(run_id), "name": "weekly-sync", "received_at": datetime.now(timezone.utc)}
        )
    except DuplicateKeyError:
        return JSONResponse({"status": "duplicate"}, status_code=200)
    task = asyncio.create_task(run_weekly_sync())
    _running.add(task)
    task.add_done_callback(_running.discard)
    return JSONResponse({"status": "accepted"}, status_code=202)
