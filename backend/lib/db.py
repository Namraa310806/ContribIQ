"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
INDEXES: dict[str, list[IndexModel]] = {
    "status_checks": [IndexModel([("timestamp", DESCENDING)], name="timestamp_desc")],
    "users": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel(
            [("github_id", ASCENDING)],
            name="github_id_unique",
            unique=True,
            partialFilterExpression={"github_id": {"$type": "string"}},
        ),
        IndexModel([("is_demo", ASCENDING)], name="is_demo"),
        IndexModel([("auto_sync", ASCENDING), ("last_synced_at", ASCENDING)], name="auto_sync_due"),
    ],
    "sessions": [
        IndexModel([("session_hash", ASCENDING)], name="session_hash", unique=True),
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("expires_at", ASCENDING)], name="expires_at_ttl", expireAfterSeconds=0),
    ],
    "contributions": [
        IndexModel([("user_id", ASCENDING), ("dedupe_key", ASCENDING)], name="user_dedupe", unique=True),
        IndexModel([("user_id", ASCENDING), ("occurred_at", DESCENDING)], name="user_occurred"),
        IndexModel([("user_id", ASCENDING), ("category", ASCENDING)], name="user_category"),
        IndexModel([("user_id", ASCENDING), ("kind", ASCENDING), ("state", ASCENDING)], name="user_kind_state"),
        IndexModel([("user_id", ASCENDING), ("eligibility_status", ASCENDING)], name="user_eligibility"),
    ],
    # ---- PR-centric evidence collections ----
    "pull_requests": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key", unique=True),
        IndexModel([("user_id", ASCENDING), ("repo", ASCENDING)], name="user_repo"),
        IndexModel([("user_id", ASCENDING), ("occurred_at", DESCENDING)], name="user_occurred"),
        IndexModel([("user_id", ASCENDING), ("evidence_status", ASCENDING)], name="user_evidence"),
    ],
    "pr_files": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
    ],
    "pr_reviews": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
        IndexModel([("pr_key", ASCENDING), ("reviewer_login", ASCENDING)], name="pr_reviewer"),
    ],
    "pr_review_comments": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
    ],
    "pr_comments": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
    ],
    "pr_commits": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
        IndexModel([("user_id", ASCENDING), ("sha", ASCENDING)], name="user_sha"),
    ],
    "pr_checks": [
        IndexModel([("user_id", ASCENDING), ("pr_key", ASCENDING)], name="user_pr_key"),
    ],
    "repo_eligibility": [
        IndexModel([("user_id", ASCENDING), ("repo", ASCENDING)], name="user_repo", unique=True),
    ],
    "sync_coverage": [
        IndexModel([("user_id", ASCENDING), ("kind", ASCENDING), ("window_start", ASCENDING)], name="user_kind_window", unique=True),
        IndexModel([("user_id", ASCENDING), ("updated_at", DESCENDING)], name="user_updated"),
    ],
    "skills": [
        IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], name="user_name", unique=True),
        IndexModel([("user_id", ASCENDING), ("score", DESCENDING)], name="user_score"),
    ],
    "insights": [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("kind", ASCENDING)], name="user_kind"),
    ],
    "jobs": [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=7 * 24 * 3600),
    ],
    "share_tokens": [
        IndexModel([("token", ASCENDING)], name="token", unique=True),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
    "tailored_sets": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
    ],
    "cron_runs": [
        IndexModel([("run_id", ASCENDING)], name="run_id", unique=True),
        IndexModel([("received_at", ASCENDING)], name="received_ttl", expireAfterSeconds=30 * 24 * 3600),
    ],
}


async def ensure_indexes() -> None:
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
