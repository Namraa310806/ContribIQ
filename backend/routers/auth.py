"""GitHub OAuth login, demo session, /auth/me and logout — httpOnly cookies only."""

import base64
import hashlib
import hmac
import os
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from lib.db import db
from lib.demo import ensure_demo_profile
from lib.session import create_session, current_user, destroy_session, to_public
from models.contribiq import AuthUrlResponse, MeResponse, UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_KW = dict(httponly=True, samesite="lax", secure=False, path="/")
OAUTH_STATE_TTL = 600  # 10 minutes — authorization codes expire just as fast


def _oauth_configured() -> bool:
    return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))


def _redirect_uri(request: Request) -> str:
    # Prefer APP_URL so the OAuth round-trip lands on the frontend origin (the Vite
    # proxy forwards /api to the backend); request.base_url is the backend's own
    # origin behind the proxy, which would strand the post-login redirect on :8001.
    app_url = (os.environ.get("APP_URL") or "").rstrip("/")
    if app_url:
        return f"{app_url}/api/auth/github/callback"
    root = str(request.base_url).rstrip("/")
    return f"{root}/api/auth/github/callback"


@router.get("/github-url", response_model=AuthUrlResponse)
async def github_url(request: Request):
    """Probe the browser makes before bouncing: returns the authorize URL (and stashes
    the OAuth transaction in short-lived cookies) or `configured: false`."""
    if not _oauth_configured():
        return AuthUrlResponse(configured=False)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = urllib.parse.urlencode(
        {
            "client_id": os.environ["GITHUB_CLIENT_ID"],
            "redirect_uri": _redirect_uri(request),
            "scope": "read:user",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    response = JSONResponse({"configured": True, "url": f"https://github.com/login/oauth/authorize?{params}"})
    now = datetime.now(timezone.utc)
    response.set_cookie("oauth_state", state, max_age=OAUTH_STATE_TTL, expires=now + timedelta(seconds=OAUTH_STATE_TTL), **COOKIE_KW)
    response.set_cookie("oauth_verifier", verifier, max_age=OAUTH_STATE_TTL, expires=now + timedelta(seconds=OAUTH_STATE_TTL), **COOKIE_KW)
    return response


@router.get("/github/callback")
async def github_callback(request: Request):
    fail = RedirectResponse("/?auth_error=github", status_code=303)
    if request.query_params.get("error"):
        return fail
    code = request.query_params.get("code")
    returned_state = request.query_params.get("state")
    saved_state = request.cookies.get("oauth_state")
    verifier = request.cookies.get("oauth_verifier")
    if not code or not returned_state or not saved_state or not verifier:
        return fail
    if not hmac.compare_digest(returned_state, saved_state):
        return fail

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": os.environ["GITHUB_CLIENT_ID"],
                "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": _redirect_uri(request),
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token")
        if not token:
            return fail
        me_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        me_resp.raise_for_status()
        profile = me_resp.json()

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"github_id": str(profile["id"])},
        {
            "$set": {
                "github_id": str(profile["id"]),
                "login": profile.get("login") or "github-user",
                "name": profile.get("name") or profile.get("login") or "GitHub user",
                "avatar_url": profile.get("avatar_url") or "",
                "profile_url": profile.get("html_url") or "",
                "github_token": token,
                "last_synced_at": None,
            },
            "$setOnInsert": {"id": str(uuid.uuid4()), "is_demo": False, "created_at": now},
        },
        upsert=True,
    )
    user = await db.users.find_one({"github_id": str(profile["id"])})
    response = RedirectResponse("/dashboard", status_code=303)
    await create_session(response, user["id"])
    response.delete_cookie("oauth_state", path="/")
    response.delete_cookie("oauth_verifier", path="/")
    return response


@router.post("/demo", response_model=UserPublic)
async def demo_login(response: Response):
    user = await ensure_demo_profile()
    await create_session(response, user["id"])
    return UserPublic(**to_public(user))


@router.get("/me", response_model=MeResponse)
async def me(request: Request):
    user = await current_user(request)
    return MeResponse(user=UserPublic(**to_public(user)) if user else None)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    await destroy_session(request, response)
    return Response(status_code=204)
