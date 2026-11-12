"""Repository eligibility engine — decides whether a repo counts as an
independently maintained external codebase for open-source collaboration scoring.

Statuses:
  ELIGIBLE_EXTERNAL                — independent repo; may contribute to OSS score
  EXCLUDED_SELF_OWNED              — owned by the developer (account or fork upstream)
  EXCLUDED_CONTROLLED_ORGANIZATION — org the developer *administers* (verifiable control)
  REVIEW_REQUIRED                  — ownership evidence incomplete or contradictory
  UNKNOWN                          — repo inaccessible / ownership undeterminable

Evidence model (milestone 2):
- The assessed repository is the PR's *base* repository — the destination the
  contribution landed in. A PR authored from a personal fork but targeting an
  upstream project is judged on the upstream repo, which is correct: that is
  where the engineering collaboration happened.
- Org *membership* is no longer disqualifying. What matters is *control*:
  - role "admin" (org owner)     → EXCLUDED_CONTROLLED_ORGANIZATION
  - role "member"                → ELIGIBLE_EXTERNAL (independent org; lower confidence)
  - member but role unverifiable → REVIEW_REQUIRED (no unverified credit, not excluded)
- Forks are resolved through `parent.full_name`: a fork of the developer's own
  repo is self-owned; a fork of an external upstream is eligible with reduced
  confidence because the canonical codebase lives upstream.
- When ownership cannot be established the repo is UNKNOWN/REVIEW_REQUIRED and
  earns no unverified external-collaboration credit — evidence is preserved.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.db import db

logger = logging.getLogger(__name__)

ELIGIBLE_EXTERNAL = "ELIGIBLE_EXTERNAL"
EXCLUDED_SELF_OWNED = "EXCLUDED_SELF_OWNED"
EXCLUDED_CONTROLLED_ORGANIZATION = "EXCLUDED_CONTROLLED_ORGANIZATION"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
UNKNOWN = "UNKNOWN"

# Statuses that may contribute to the open-source collaboration assessment.
OSS_COUNTED = {ELIGIBLE_EXTERNAL}
# Statuses that earn no unverified external credit but aren't proven self-owned.
NEUTRAL = {REVIEW_REQUIRED, UNKNOWN}
EXCLUDED = {EXCLUDED_SELF_OWNED, EXCLUDED_CONTROLLED_ORGANIZATION}

ELIGIBILITY_TTL = timedelta(days=7)  # re-verify ownership weekly during syncs


def _norm(login: Optional[str]) -> str:
    return (login or "").strip().lower()


def _org_role(org_login: str, user_orgs: set[str], org_roles: Optional[dict[str, str]]) -> Optional[str]:
    """Resolve the developer's role in an org: "admin" | "member" | None.

    org_roles=None means the caller only has a membership set (legacy) —
    presence implies "member" but admin/member is indistinguishable.
    org_roles={} means roles were fetched and this org is absent → None.
    """
    key = _norm(org_login)
    if org_roles is not None:
        return org_roles.get(key)
    return "member" if key in {_norm(o) for o in user_orgs} else None


def classify_repo_ownership(
    repo: Optional[dict],
    *,
    login: str,
    user_orgs: set[str],
    org_roles: Optional[dict[str, str]] = None,
) -> dict:
    """Pure eligibility decision from a GitHub repo payload + user context.

    `repo` is the GET /repos/{owner}/{repo} response for the PR's *base* repo
    (may be None when deleted, renamed away, or inaccessible). Returns an
    auditable record: status, reason, confidence (0-1), and evidence fields.
    """
    user_login = _norm(login)
    base = {
        "repo_id": None,
        "owner": "",
        "owner_type": "",
        "is_fork": False,
        "upstream": "",
        "org_role": None,
        "is_collaborator": False,
        "permissions": {},
    }

    if not repo:
        return {
            **base,
            "status": UNKNOWN,
            "reason": "repository metadata unavailable (deleted, renamed, or inaccessible)",
            "confidence": 0.0,
        }

    owner = (repo.get("owner") or {}).get("login") or ""
    owner_type = (repo.get("owner") or {}).get("type") or ""
    is_fork = bool(repo.get("fork"))
    parent = ((repo.get("parent") or {}).get("full_name") or "") if is_fork else ""
    permissions = repo.get("permissions") or {}
    org_role = _org_role(owner, user_orgs, org_roles) if owner_type == "Organization" else None
    # Collaborator signal: write-ish permission on a repo the user doesn't own.
    is_collaborator = _norm(owner) != user_login and any(
        permissions.get(k) for k in ("admin", "maintain", "push", "triage")
    )

    base.update(
        {
            "repo_id": repo.get("id"),
            "owner": owner,
            "owner_type": owner_type,
            "is_fork": is_fork,
            "upstream": parent,
            "org_role": org_role,
            "permissions": {k: bool(v) for k, v in permissions.items() if isinstance(v, bool)},
        }
    )

    # 1 — the developer's own account.
    if _norm(owner) == user_login:
        return {
            **base,
            "status": EXCLUDED_SELF_OWNED,
            "reason": "repository is owned by the developer's own account",
            "confidence": 1.0,
        }

    # 2 — organization-owned repo: distinguish control from membership.
    if owner_type == "Organization":
        is_member = _norm(owner) in {_norm(o) for o in user_orgs} or _norm(owner) in {
            _norm(k) for k in (org_roles or {})
        }
        if not is_member:
            return {
                **base,
                "status": ELIGIBLE_EXTERNAL,
                "reason": "organization-owned repository; developer is not a member",
                "confidence": 0.9,
            }
        if org_role == "admin":
            return {
                **base,
                "status": EXCLUDED_CONTROLLED_ORGANIZATION,
                "reason": "developer is an admin of the owning organization",
                "confidence": 0.9,
            }
        if org_role == "member":
            return {
                **base,
                "status": ELIGIBLE_EXTERNAL,
                "reason": "organization-owned repository; developer is a member, not an admin",
                "confidence": 0.75,
            }
        # Member of the org but role unverifiable → no unverified credit.
        return {
            **base,
            "status": REVIEW_REQUIRED,
            "reason": "organization-owned repository; developer's org role could not be verified",
            "confidence": 0.4,
        }

    # 3 — forks: the base repo decides. A fork of the developer's own repo is
    #     self-owned; a fork of an external upstream is eligible at reduced
    #     confidence (canonical codebase lives upstream).
    if is_fork and parent:
        parent_owner = _norm(parent.split("/", 1)[0] if "/" in parent else "")
        if parent_owner == user_login:
            return {
                **base,
                "status": EXCLUDED_SELF_OWNED,
                "reason": f"fork of the developer's own repository ({parent})",
                "confidence": 0.95,
            }
        return {
            **base,
            "status": ELIGIBLE_EXTERNAL,
            "reason": f"fork of independently maintained upstream {parent}",
            "confidence": 0.6,
        }

    # 4 — different owner, not a fork, not a controlled org: independently maintained.
    if owner_type == "User":
        return {
            **base,
            "status": ELIGIBLE_EXTERNAL,
            "reason": "user-owned repository under a different account",
            "confidence": 0.85,
        }

    return {
        **base,
        "status": REVIEW_REQUIRED,
        "reason": f"unrecognised owner type '{owner_type}' — manual review advised",
        "confidence": 0.3,
    }


def eligibility_record(
    repo_full: str,
    repo: Optional[dict],
    *,
    login: str,
    user_orgs: set[str],
    user_id: str = "",
    org_roles: Optional[dict[str, str]] = None,
) -> dict:
    """Build the persisted RepositoryEligibility document."""
    decision = classify_repo_ownership(repo, login=login, user_orgs=user_orgs, org_roles=org_roles)
    now = datetime.now(timezone.utc)
    return {
        "id": f"{user_id}:{repo_full}".strip(":"),
        "user_id": user_id,
        "repo": repo_full,
        "status": decision["status"],
        "reason": decision["reason"],
        "confidence": decision["confidence"],
        "repo_id": decision["repo_id"],
        "owner": decision["owner"],
        "owner_type": decision["owner_type"],
        "is_fork": decision["is_fork"],
        "upstream": decision["upstream"],
        "org_role": decision["org_role"],
        "is_collaborator": decision["is_collaborator"],
        "user_is_org_member": decision["org_role"] is not None,
        "permissions": decision["permissions"],
        "verified_at": now,
        "created_at": now,
    }


def _aw(dt) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def ensure_repo_eligibility(
    gc,
    user_id: str,
    login: str,
    user_orgs: set[str],
    repo_full: str,
    org_roles: Optional[dict[str, str]] = None,
) -> str:
    """Return the eligibility status for a repo (the PR's base repo), verifying
    via the GitHub API at most once per ELIGIBILITY_TTL. Org admin vs member is
    resolved through the memberships API when roles are not already known."""
    existing = await db.repo_eligibility.find_one({"user_id": user_id, "repo": repo_full})
    if existing:
        verified = _aw(existing.get("verified_at"))
        if verified and (datetime.now(timezone.utc) - verified) < ELIGIBILITY_TTL:
            return existing.get("status") or UNKNOWN

    repo: Optional[dict] = None
    error: Optional[str] = None
    roles = org_roles
    try:
        repo = await gc.fetch_repo(repo_full)
        # For org-owned repos without a known role, ask the memberships API —
        # this is the only verifiable admin/member signal GitHub exposes.
        owner = ((repo or {}).get("owner") or {}).get("login") or ""
        owner_type = ((repo or {}).get("owner") or {}).get("type") or ""
        if owner_type == "Organization" and roles is not None and _norm(owner) not in {_norm(k) for k in roles}:
            try:
                m = await gc.fetch_org_membership(owner)
                if m and (m.get("state") or "active") == "active":
                    roles = {**roles, _norm(owner): (m.get("role") or "member").lower()}
            except Exception as exc:
                logger.warning("org membership check failed for %s: %s", owner, exc)
    except Exception as exc:  # deleted/renamed/private — record, don't crash the run
        error = str(exc)[:200]
        logger.warning("repo metadata fetch failed for %s: %s", repo_full, error)

    record = eligibility_record(
        repo_full, repo, login=login, user_orgs=user_orgs, user_id=user_id, org_roles=roles
    )
    if error:
        record["last_error"] = error
    await db.repo_eligibility.update_one(
        {"user_id": user_id, "repo": repo_full},
        {"$set": record},
        upsert=True,
    )
    return record["status"]
