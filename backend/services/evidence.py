"""PR evidence ingestion: fetch GitHub detail for each discovered PR and persist
normalized evidence documents (files, reviews, comments, checks, linked issues).

Design rules:
- The PR is the primary engineering-evidence object; everything here hangs off
  `pr_key = "{repo_full}#{number}"`.
- Writes are idempotent: children are replaced per PR on refresh, parents are
  upserted on (user_id, pr_key).
- Missing data is recorded, never invented: a failed sub-fetch downgrades
  `evidence_status` to "partial" and the error is stored on the PR document.
- Patches are stored truncated (PATCH_MAX_CHARS) with `patch_available` /
  `patch_truncated` flags so downstream scoring can distinguish "no patch"
  from "bad code".
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from lib.db import db

logger = logging.getLogger(__name__)

PATCH_MAX_CHARS = 6000
BODY_MAX_CHARS = 4000
PR_KEY_SEP = "#"

# ---------- file categorisation ----------

_TEST_DIRS = ("test", "tests", "spec", "specs", "__tests__", "e2e", "integration_tests")
_TEST_SUFFIXES = ("_test.", ".test.", ".spec.", "_spec.", "test_", "conftest.py")
_DOC_EXTS = {".md", ".rst", ".txt", ".adoc", ".pdf"}
_CONFIG_NAMES = {
    "dockerfile", "makefile", "procfile", "gemfile", "podfile", "brewfile",
    ".gitignore", ".gitattributes", ".editorconfig", ".prettierrc", ".eslintrc",
}
_CONFIG_EXTS = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".lock", ".json"}


def categorize_file(path: str) -> str:
    """Coarse engineering category for a changed file path."""
    p = (path or "").lower()
    name = p.rsplit("/", 1)[-1]
    parts = p.split("/")
    if any(part in _TEST_DIRS for part in parts) or any(s in name for s in _TEST_SUFFIXES):
        return "test"
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if name in _CONFIG_NAMES or ext in _CONFIG_EXTS or p.startswith((".github/", "ci/", ".circleci/", ".buildkite/")):
        return "config"
    if ext in _DOC_EXTS or p.startswith(("docs/", "doc/")):
        return "docs"
    return "source"


def file_extension(path: str) -> str:
    name = (path or "").rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def summarize_files(files: list[dict]) -> dict:
    """Aggregate changed-file evidence into scoring-friendly counts.

    Returns category buckets with file counts, line deltas and change-status
    counts (added/modified/removed/renamed), plus patch availability — never
    raw line totals as a quality proxy.
    """
    cats: dict[str, dict] = {}
    statuses: dict[str, int] = {}
    total = 0
    patch_available = 0
    for f in files or []:
        path = f.get("filename") or ""
        cat = categorize_file(path)
        bucket = cats.setdefault(
            cat, {"files": 0, "additions": 0, "deletions": 0, "added": 0, "removed": 0, "modified": 0}
        )
        bucket["files"] += 1
        bucket["additions"] += f.get("additions") or 0
        bucket["deletions"] += f.get("deletions") or 0
        status = (f.get("status") or "modified").lower()
        statuses[status] = statuses.get(status, 0) + 1
        if status == "added":
            bucket["added"] += 1
        elif status == "removed":
            bucket["removed"] += 1
        else:
            bucket["modified"] += 1
        total += 1
        if f.get("patch"):
            patch_available += 1
    return {
        "files_total": total,
        "patch_available": patch_available,
        "patch_ratio": round(patch_available / total, 3) if total else 0.0,
        "categories": cats,
        "statuses": statuses,
    }


# ---------- normalisers ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def pr_key(repo_full: str, number: int) -> str:
    return f"{repo_full}{PR_KEY_SEP}{number}"


def normalize_pr(repo_full: str, detail: dict, user_id: str) -> dict:
    """GitHub PR detail payload → pull_requests document."""
    number = detail.get("number")
    head = detail.get("head") or {}
    base = detail.get("base") or {}
    merged = bool(detail.get("merged_at")) or bool(detail.get("merged"))
    state = "merged" if merged else (detail.get("state") or "open")
    head_repo = ((head.get("repo") or {}).get("full_name") or "")
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "pr_key": pr_key(repo_full, number),
        "repo": repo_full,
        "number": number,
        "github_id": detail.get("id"),
        "node_id": detail.get("node_id"),
        "title": (detail.get("title") or "")[:300],
        "body": (detail.get("body") or "")[:BODY_MAX_CHARS],
        "state": state,
        "merged": merged,
        "draft": bool(detail.get("draft")),
        "author": (detail.get("user") or {}).get("login") or "",
        "author_association": detail.get("author_association") or "",
        "labels": [l.get("name", "") for l in (detail.get("labels") or []) if isinstance(l, dict) and l.get("name")],
        "additions": detail.get("additions") or 0,
        "deletions": detail.get("deletions") or 0,
        "changed_files": detail.get("changed_files") or 0,
        "commits_count": detail.get("commits") or 0,
        # GitHub's own totals: `comments` = PR conversation comments,
        # `review_comments` = inline review comments. Sum = discussion evidence
        # for the collab dimension (issue comments alone undercount PRs).
        "comment_count": (detail.get("comments") or 0) + (detail.get("review_comments") or 0),
        "base_ref": base.get("ref") or "",
        "head_ref": head.get("ref") or "",
        "head_sha": head.get("sha") or "",
        "head_repo": head_repo,
        "is_cross_repo": bool(head_repo) and head_repo.lower() != repo_full.lower(),
        "merge_commit_sha": detail.get("merge_commit_sha") or "",
        "created_at": _parse_ts(detail.get("created_at")),
        "updated_at": _parse_ts(detail.get("updated_at")),
        "closed_at": _parse_ts(detail.get("closed_at")),
        "merged_at": _parse_ts(detail.get("merged_at")),
        "html_url": detail.get("html_url") or "",
        "github_updated_at": detail.get("updated_at"),
        "occurred_at": _parse_ts(detail.get("merged_at") or detail.get("closed_at") or detail.get("created_at")) or _now(),
        "source": "github_api",
        "fetched_at": _now(),
    }


def normalize_file(user_id: str, key: str, f: dict) -> dict:
    path = f.get("filename") or ""
    patch = f.get("patch")
    patch_truncated = bool(patch and len(patch) > PATCH_MAX_CHARS)
    return {
        "user_id": user_id,
        "pr_key": key,
        "path": path,
        "previous_path": f.get("previous_filename") or "",
        "status": f.get("status") or "modified",  # added|removed|modified|renamed|changed
        "additions": f.get("additions") or 0,
        "deletions": f.get("deletions") or 0,
        "changes": f.get("changes") or 0,
        "patch": patch[:PATCH_MAX_CHARS] if patch else None,
        "patch_available": bool(patch),
        "patch_truncated": patch_truncated,
        "extension": file_extension(path),
        "category": categorize_file(path),
        "fetched_at": _now(),
    }


def normalize_review(user_id: str, key: str, r: dict) -> dict:
    return {
        "user_id": user_id,
        "pr_key": key,
        "review_id": r.get("id"),
        "reviewer_login": (r.get("user") or {}).get("login") or "",
        "reviewer_id": (r.get("user") or {}).get("id"),
        "state": (r.get("state") or "").upper(),
        "submitted_at": _parse_ts(r.get("submitted_at")),
        "body": (r.get("body") or "")[:BODY_MAX_CHARS],
        "commit_id": r.get("commit_id") or "",
        "html_url": r.get("html_url") or "",
        "fetched_at": _now(),
    }


def normalize_review_comment(user_id: str, key: str, c: dict) -> dict:
    return {
        "user_id": user_id,
        "pr_key": key,
        "comment_id": c.get("id"),
        "kind": "review",
        "user_login": (c.get("user") or {}).get("login") or "",
        "path": c.get("path") or "",
        "line": c.get("line") or c.get("original_line"),
        "side": c.get("side") or "",
        "body": (c.get("body") or "")[:BODY_MAX_CHARS],
        "in_reply_to_id": c.get("in_reply_to_id"),
        "created_at": _parse_ts(c.get("created_at")),
        "updated_at": _parse_ts(c.get("updated_at")),
        "html_url": c.get("html_url") or "",
        "fetched_at": _now(),
    }


def normalize_conversation_comment(user_id: str, key: str, c: dict) -> dict:
    return {
        "user_id": user_id,
        "pr_key": key,
        "comment_id": c.get("id"),
        "user_login": (c.get("user") or {}).get("login") or "",
        "body": (c.get("body") or "")[:BODY_MAX_CHARS],
        "created_at": _parse_ts(c.get("created_at")),
        "updated_at": _parse_ts(c.get("updated_at")),
        "html_url": c.get("html_url") or "",
        "fetched_at": _now(),
    }


def normalize_commits(user_id: str, key: str, commits: list[dict]) -> list[dict]:
    """Commits are supporting evidence inside a PR — never independent contributions."""
    out = []
    for c in commits or []:
        sha = c.get("sha") or ""
        if not sha:
            continue
        out.append(
            {
                "user_id": user_id,
                "pr_key": key,
                "sha": sha,
                "author_login": ((c.get("author") or {}).get("login")) or ((c.get("commit") or {}).get("author") or {}).get("name") or "",
                "message": (((c.get("commit") or {}).get("message") or "").splitlines() or [""])[0][:300],
                "authored_at": _parse_ts(((c.get("commit") or {}).get("author") or {}).get("date")),
                "html_url": c.get("html_url") or "",
                "fetched_at": _now(),
            }
        )
    return out


def normalize_checks(user_id: str, key: str, sha: str, check_runs: list[dict], combined: Optional[dict]) -> list[dict]:
    """Merge check-runs + legacy commit statuses into one check list."""
    out = []
    for cr in check_runs or []:
        out.append(
            {
                "user_id": user_id,
                "pr_key": key,
                "sha": sha,
                "name": cr.get("name") or "",
                "source": "check_run",
                "status": (cr.get("status") or "").lower(),  # queued|in_progress|completed
                "conclusion": (cr.get("conclusion") or "").lower() or None,  # success|failure|...
                "started_at": _parse_ts(cr.get("started_at")),
                "completed_at": _parse_ts(cr.get("completed_at")),
                "url": cr.get("html_url") or cr.get("details_url") or "",
                "fetched_at": _now(),
            }
        )
    for st in ((combined or {}).get("statuses") or []):
        out.append(
            {
                "user_id": user_id,
                "pr_key": key,
                "sha": sha,
                "name": st.get("context") or st.get("name") or "",
                "source": "commit_status",
                "status": "completed",
                "conclusion": (st.get("state") or "").lower() or None,  # success|failure|pending|error
                "url": st.get("target_url") or "",
                "fetched_at": _now(),
            }
        )
    return out


_CI_FAILURE = {"failure", "error", "cancelled", "timed_out", "action_required"}


def checks_summary(checks: list[dict]) -> str:
    """Collapse check-run/status docs into one CI signal for scoring.

    "none"   — no checks exist on the head commit (unknown ≠ failed)
    "pending"— checks exist but none concluded
    "success"— at least one concluded successfully and none failed
    "failure"— at least one concluded unsuccessfully
    "unknown"— checks exist but conclusions are unreadable
    """
    if not checks:
        return "none"
    conclusions = [(c.get("conclusion") or "").lower() for c in checks]
    statuses = [(c.get("status") or "").lower() for c in checks]
    if any(c in _CI_FAILURE for c in conclusions):
        return "failure"
    if any(c in ("success", "neutral", "skipped") for c in conclusions):
        return "success"
    if any(c for c in conclusions):
        return "unknown"
    if any(s in ("queued", "in_progress", "pending", "waiting") for s in statuses):
        return "pending"
    return "unknown"


def review_summary(reviews: list[dict]) -> dict:
    """summarize_reviews over normalized review docs (reviewer_login/state)."""
    states: dict[str, int] = {}
    reviewers: set[str] = set()
    for r in reviews or []:
        if r.get("reviewer_login"):
            reviewers.add(r["reviewer_login"])
        st = (r.get("state") or "").upper()
        states[st] = states.get(st, 0) + 1
    return {
        "review_count": len(reviews or []),
        "approvals": states.get("APPROVED", 0),
        "change_requests": states.get("CHANGES_REQUESTED", 0),
        "commented_reviews": states.get("COMMENTED", 0),
        "dismissed_reviews": states.get("DISMISSED", 0),
        "reviewers": len(reviewers),
    }


def author_replied(pr_author: str, reviews: list[dict], review_comments: list[dict], conv_comments: list[dict]) -> bool:
    """Did the PR author respond after the first external review?

    A maintainer interaction signal — requires a review event first, then any
    author-authored comment (review comment or conversation) afterwards.
    """
    reviewer_times = [
        r.get("submitted_at")
        for r in reviews or []
        if r.get("reviewer_login") and r.get("reviewer_login") != pr_author and r.get("submitted_at")
    ]
    if not reviewer_times:
        return False
    first_review = min(reviewer_times)
    author_msgs = [
        c.get("created_at")
        for c in list(review_comments or []) + list(conv_comments or [])
        if c.get("user_login") == pr_author and c.get("created_at")
    ]
    return any(t > first_review for t in author_msgs)


# ---------- linked issues ----------

_LINK_RE = re.compile(r"(?<![\w/])(?:([\w.-]+/[\w.-]+))?#(\d+)\b")
_CLOSING_KEYWORD_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b", re.IGNORECASE)
MAX_LINKED_ISSUES = 5


def extract_issue_refs(body: str, repo_full: str) -> list[int]:
    """Same-repo issue references introduced by closing keywords.

    For each `#N` (or `owner/repo#N`) we inspect the text since the previous
    reference — a closing keyword must appear in that clause, so "fixes #12
    and also see #99" links only #12.
    """
    refs: list[int] = []
    prev_end = 0
    for m in _LINK_RE.finditer(body or ""):
        owner_repo = m.group(1)
        if owner_repo and owner_repo.lower() != repo_full.lower():
            prev_end = m.end()
            continue
        clause = (body or "")[prev_end : m.start()]
        prev_end = m.end()
        if not _CLOSING_KEYWORD_RE.search(clause[-80:]):
            continue
        num = int(m.group(2))
        if num not in refs:
            refs.append(num)
    return refs[:MAX_LINKED_ISSUES]


async def fetch_linked_issues(gc, repo_full: str, body: str) -> list[dict]:
    """Resolve closing-issue references to lightweight issue docs."""
    out = []
    for num in extract_issue_refs(body, repo_full):
        try:
            issue = await gc.fetch_issue(repo_full, num)
        except Exception as exc:
            logger.warning("linked issue fetch failed %s#%s: %s", repo_full, num, exc)
            continue
        if not issue or "pull_request" in issue:
            continue
        out.append(
            {
                "number": issue.get("number"),
                "title": (issue.get("title") or "")[:300],
                "state": issue.get("state") or "",
                "url": issue.get("html_url") or "",
                "labels": [l.get("name", "") for l in (issue.get("labels") or []) if isinstance(l, dict) and l.get("name")],
            }
        )
    return out


# ---------- evidence completeness ----------

def evidence_status(errors: list[str], fetched_any: bool) -> str:
    if errors and not fetched_any:
        return "failed"
    if errors:
        return "partial"
    return "complete"


# ---------- integration outcome (timeline) ----------

def parse_timeline(events: list[dict]) -> dict:
    """Extract integration-outcome signals from PR timeline events.

    Returns {"reverted": bool, "revert_refs": [...], "superseded_by": [...],
    "closed_unmerged": bool, "merged": bool}.

    - `reverted` events name the commit/PR that reverted this one.
    - `cross-referenced`/`referenced` events pointing at merged PRs that close
    the same issue are recorded as superseded candidates (verified upstream).
    """
    out = {"reverted": False, "revert_refs": [], "superseded_by": [], "merged": False, "closed_unmerged": False}
    for e in events or []:
        etype = e.get("event") or ""
        if etype == "merged":
            out["merged"] = True
        elif etype == "closed":
            out["closed_unmerged"] = True  # refined by caller using merged_at
        elif etype == "reverted":
            out["reverted"] = True
            commit = e.get("commit_id") or ""
            if commit:
                out["revert_refs"].append(commit)
        elif etype in ("cross-referenced", "referenced"):
            src = ((e.get("source") or {}).get("issue") or {})
            if src.get("pull_request"):
                num = src.get("number")
                state = (src.get("state") or "").lower()
                merged_at = ((src.get("pull_request") or {}).get("merged_at")) or ""
                # Only count as superseded evidence when the referencing PR verifiably merged.
                if num and (merged_at or state == "closed"):
                    out["superseded_by"].append({"number": num, "url": src.get("html_url") or ""})
    # A merged PR also emits a `closed` timeline event — closed_unmerged must
    # mean closed *without* merging.
    out["closed_unmerged"] = out["closed_unmerged"] and not out["merged"]
    return out


# ---------- persistence ----------

async def upsert_pr(doc: dict) -> None:
    await db.pull_requests.update_one(
        {"user_id": doc["user_id"], "pr_key": doc["pr_key"]},
        {"$set": doc},
        upsert=True,
    )


async def replace_pr_children(user_id: str, key: str, children: dict[str, list[dict]]) -> None:
    """Replace child evidence for one PR — keeps refreshes idempotent.

    IMPORTANT: callers must only include collections whose fetch *succeeded*.
    A failed fetch is simply absent from `children`, so previously stored
    evidence for that collection is preserved rather than destroyed by an
    empty replacement. Pass `children_status` separately for audit.
    """
    for collection, docs in children.items():
        coll = db[collection]
        await coll.delete_many({"user_id": user_id, "pr_key": key})
        if docs:
            await coll.insert_many(docs)


async def get_pr(user_id: str, key: str) -> Optional[dict]:
    return await db.pull_requests.find_one({"user_id": user_id, "pr_key": key})


async def pr_needs_evidence(pr_doc: Optional[dict], detail: dict) -> bool:
    """Incremental rule: refetch children only when the PR changed upstream or
    the previous evidence pass was incomplete."""
    if not pr_doc:
        return True
    if pr_doc.get("evidence_status") != "complete":
        return True
    stored = pr_doc.get("github_updated_at")
    incoming = detail.get("updated_at")
    return bool(incoming and stored and incoming > stored)
