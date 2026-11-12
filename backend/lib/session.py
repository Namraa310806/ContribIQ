"""httpOnly-cookie sessions. The browser only ever holds an opaque random id.

Mirrors the auth playbook: session ids are hashed before storage, cookies are
HttpOnly + SameSite=Lax, and no token ever appears in a JSON body.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, Response

from lib.db import db

SESSION_COOKIE = "contribiq_session"
SESSION_TTL = timedelta(days=30)
_TTL_SECONDS = int(SESSION_TTL.total_seconds())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def create_session(response: Response, user_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await db.sessions.insert_one(
        {
            "id": str(uuid.uuid4()),
            "session_hash": _hash(sid),
            "user_id": user_id,
            "created_at": now,
            "expires_at": now + SESSION_TTL,
        }
    )
    response.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # TLS terminates at the ingress; the pod sees plain HTTP
        path="/",
    )


async def current_user(request: Request) -> Optional[dict]:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    sess = await db.sessions.find_one({"session_hash": _hash(sid)})
    if not sess:
        return None
    expires = sess["expires_at"]
    if expires.tzinfo is None:  # motor returns naive UTC datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return None
    return await db.users.find_one({"id": sess["user_id"]})


async def require_user(request: Request) -> dict:
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


async def destroy_session(request: Request, response: Response) -> None:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await db.sessions.delete_one({"session_hash": _hash(sid)})
    response.delete_cookie(SESSION_COOKIE, path="/")


def to_public(user: dict) -> dict:
    """Projection of a user document that is safe to serialize to any client."""
    return {
        "id": user["id"],
        "is_demo": bool(user.get("is_demo")),
        "login": user.get("login") or "",
        "name": user.get("name") or user.get("login") or "",
        "avatar_url": user.get("avatar_url") or "",
        "profile_url": user.get("profile_url") or "",
        "has_github_token": bool(user.get("github_token")),
        "last_synced_at": user.get("last_synced_at"),
        "excluded_repos": list(user.get("excluded_repos") or []),
        "auto_sync": bool(user.get("auto_sync")),
        "oss_only": bool(user.get("oss_only")),
    }
