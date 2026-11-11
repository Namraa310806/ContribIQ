"""Idempotent demo profile — shared by seed.py and POST /api/auth/demo.

Creates a fully analyzed profile for "alexchen-dev" so the dashboard, recruiter
dossier and insights are explorable immediately, without any OAuth round-trip.
Real GitHub analysis remains the path for a user's own data.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.db import db

DEMO_SHARE_TOKEN = "contribiq-demo-dossier"


def _days_ago(days: int, hours: int = 3) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours)


def _c(idx: int, kind: str, repo: str, title: str, summary: str, dedupe: str, url: str,
       state: str, occurred_at: datetime, category: str, complexity: str, impact: int,
       technologies: list, labels: list | None = None, number: int | None = None,
       additions: int = 0, deletions: int = 0, comments: int = 0) -> dict:
    return {
        "id": f"demo-{idx:03d}",
        "kind": kind,
        "repo": repo,
        "title": title,
        "summary": summary,
        "dedupe_key": dedupe,
        "number": number,
        "url": url,
        "state": state,
        "labels": labels or [],
        "additions": additions,
        "deletions": deletions,
        "comments": comments,
        "category": category,
        "complexity": complexity,
        "impact_score": impact,
        "technologies": technologies,
        "analyzed": True,
        "occurred_at": occurred_at,
        "analyzed_at": _days_ago(1),
    }


def _contributions() -> list[dict]:
    c = []
    c.append(_c(1, "pr", "acme-labs/fastapi-distributed-cache",
        "Add adaptive TTL eviction to the distributed cache layer",
        "Replaced fixed TTLs with jittered adaptive eviction behind a single-flight lock, ending cache-stampede outages under bursty reads.",
        "pr:acme-labs/fastapi-distributed-cache:184", "https://github.com/acme-labs/fastapi-distributed-cache/pull/184",
        "merged", _days_ago(12, 4), "Performance", "High", 92,
        ["Python", "FastAPI", "Redis"], ["performance", "reliability"], 184, 412, 38, 14))
    c.append(_c(2, "pr", "acme-labs/fastapi-distributed-cache",
        "Fix race condition in cache stampede protection",
        "Closed a race where concurrent misses bypassed the single-flight lock; added a regression test that reproduces it deterministically.",
        "pr:acme-labs/fastapi-distributed-cache:191", "https://github.com/acme-labs/fastapi-distributed-cache/pull/191",
        "merged", _days_ago(9, 2), "Bug Fix", "High", 88,
        ["Python", "Redis", "pytest"], ["bug"], 191, 87, 12, 9))
    c.append(_c(3, "pr", "acme-labs/fastapi-distributed-cache",
        "Add Prometheus metrics endpoint with latency histograms",
        "Exposed p50/p95/p99 cache latency histograms and hit-rate counters, making regressions visible before users notice.",
        "pr:acme-labs/fastapi-distributed-cache:176", "https://github.com/acme-labs/fastapi-distributed-cache/pull/176",
        "merged", _days_ago(21, 6), "DevOps", "Medium", 74,
        ["FastAPI", "Prometheus", "Docker"], ["observability"], 176, 156, 4, 6))
    c.append(_c(4, "commit", "acme-labs/fastapi-distributed-cache",
        "Refactor serialization path to orjson",
        "Swapped the hot serialization path to orjson, cutting cache round-trip CPU time by roughly a third in the benchmarks.",
        "commit:acme-labs/fastapi-distributed-cache:9f21ab4", "https://github.com/acme-labs/fastapi-distributed-cache/commit/9f21ab4",
        "committed", _days_ago(16, 1), "Performance", "Medium", 68,
        ["Python", "orjson"], [], None, 74, 22, 0))
    c.append(_c(5, "issue", "acme-labs/fastapi-distributed-cache",
        "RFC: hot-key mitigation proposal",
        "Wrote the design RFC for consistent-hash hot-key mitigation that the team adopted as the next quarter's theme.",
        "issue:acme-labs/fastapi-distributed-cache:203", "https://github.com/acme-labs/fastapi-distributed-cache/issues/203",
        "open", _days_ago(5, 8), "Documentation", "Low", 44,
        ["Python", "Redis"], ["rfc", "design"], 203, 0, 0, 7))
    c.append(_c(6, "pr", "acme-labs/react-data-grid",
        "Virtualize rendering for 100k-row datasets",
        "Introduced windowed rendering so 100k-row grids stay at 60fps; largest render dropped from 4.2s to 380ms.",
        "pr:acme-labs/react-data-grid:412", "https://github.com/acme-labs/react-data-grid/pull/412",
        "merged", _days_ago(30, 5), "Frontend", "High", 90,
        ["React", "TypeScript"], ["performance"], 412, 803, 121, 18))
    c.append(_c(7, "pr", "acme-labs/react-data-grid",
        "Add keyboard navigation and ARIA roles to the grid",
        "Made the grid fully operable by keyboard and screen readers, unblocking two enterprise customers' accessibility audits.",
        "pr:acme-labs/react-data-grid:398", "https://github.com/acme-labs/react-data-grid/pull/398",
        "merged", _days_ago(41, 3), "Frontend", "Medium", 71,
        ["React", "TypeScript"], ["accessibility"], 398, 289, 44, 8))
    c.append(_c(8, "issue", "acme-labs/react-data-grid",
        "Memory leak when unmounting mid-scroll — investigation",
        "Diagnosed and documented a scroll-listener leak with a minimal reproduction; the fix shipped in the next patch release.",
        "issue:acme-labs/react-data-grid:405", "https://github.com/acme-labs/react-data-grid/issues/405",
        "closed", _days_ago(36, 7), "Bug Fix", "Medium", 63,
        ["React", "TypeScript"], ["bug", "investigation"], 405, 0, 0, 11))
    c.append(_c(9, "pr", "acme-labs/react-data-grid",
        "Introduce column-resize persistence API",
        "Added a persistence API that restores column widths across sessions, a long-standing top-voted request.",
        "pr:acme-labs/react-data-grid:387", "https://github.com/acme-labs/react-data-grid/pull/387",
        "merged", _days_ago(52, 2), "Feature", "Medium", 66,
        ["React", "TypeScript", "localStorage"], ["enhancement"], 387, 198, 9, 5))
    c.append(_c(10, "pr", "acme-labs/react-data-grid",
        "Reduce bundle size 38% by dropping moment.js",
        "Removed the moment.js dependency in favor of native Intl APIs, cutting the bundle from 412kB to 256kB.",
        "pr:acme-labs/react-data-grid:376", "https://github.com/acme-labs/react-data-grid/pull/376",
        "merged", _days_ago(63, 4), "Performance", "Medium", 72,
        ["React", "Webpack", "JavaScript"], ["performance", "dependencies"], 376, 141, 512, 7))
    c.append(_c(11, "pr", "acme-labs/infra-k8s-mesh",
        "Blue-green deploys with readiness-gated traffic shifting",
        "Implemented blue-green deployment with readiness-gated shifting, eliminating deploy-related incidents across six releases.",
        "pr:acme-labs/infra-k8s-mesh:77", "https://github.com/acme-labs/infra-k8s-mesh/pull/77",
        "merged", _days_ago(18, 9), "DevOps", "High", 89,
        ["Kubernetes", "Terraform", "Go"], ["reliability"], 77, 534, 87, 12))
    c.append(_c(12, "commit", "acme-labs/infra-k8s-mesh",
        "Terraform module for multi-region failover",
        "Authored the reusable Terraform module that turns regional failover from a runbook into a single variable change.",
        "commit:acme-labs/infra-k8s-mesh:c41de07", "https://github.com/acme-labs/infra-k8s-mesh/commit/c41de07",
        "committed", _days_ago(25, 6), "DevOps", "High", 82,
        ["Terraform", "AWS"], ["infrastructure"], None, 611, 94, 0))
    c.append(_c(13, "pr", "acme-labs/infra-k8s-mesh",
        "Patch CVE-2024-8114 in the sidecar proxy image",
        "Upgraded the sidecar base image and added automated CVE scanning to CI, closing a high-severity dependency hole.",
        "pr:acme-labs/infra-k8s-mesh:81", "https://github.com/acme-labs/infra-k8s-mesh/pull/81",
        "merged", _days_ago(14, 3), "Security", "High", 85,
        ["Go", "Docker", "GitHub Actions"], ["security"], 81, 96, 60, 5))
    c.append(_c(14, "issue", "acme-labs/infra-k8s-mesh",
        "Document the disaster-recovery runbook",
        "Wrote the DR runbook the on-call rotation now drills quarterly; MTOR during drills fell from 45 to 12 minutes.",
        "issue:acme-labs/infra-k8s-mesh:69", "https://github.com/acme-labs/infra-k8s-mesh/issues/69",
        "closed", _days_ago(47, 5), "Documentation", "Low", 41,
        ["Kubernetes"], ["docs", "on-call"], 69, 0, 0, 4))
    c.append(_c(15, "pr", "acme-labs/payments-engine",
        "Idempotency keys to prevent double charges",
        "Added idempotency keys across the Stripe checkout path, eliminating the double-charge class of support tickets.",
        "pr:acme-labs/payments-engine:233", "https://github.com/acme-labs/payments-engine/pull/233",
        "merged", _days_ago(7, 2), "Security", "High", 94,
        ["Python", "Stripe", "PostgreSQL"], ["payments", "critical"], 233, 268, 31, 15))
    c.append(_c(16, "pr", "acme-labs/payments-engine",
        "Migrate ledger to partitioned PostgreSQL tables",
        "Partitioned the ledger by month; month-end close queries fell from 40s to 3s with zero downtime during the cutover.",
        "pr:acme-labs/payments-engine:221", "https://github.com/acme-labs/payments-engine/pull/221",
        "merged", _days_ago(28, 8), "Database", "High", 86,
        ["PostgreSQL", "Python"], ["database", "migration"], 221, 447, 102, 10))
    c.append(_c(17, "pr", "acme-labs/payments-engine",
        "Webhook replay endpoint with signature verification",
        "Built a safe webhook replay endpoint with strict signature verification, shrinking disputed-transaction triage from days to minutes.",
        "pr:acme-labs/payments-engine:214", "https://github.com/acme-labs/payments-engine/pull/214",
        "merged", _days_ago(38, 1), "API", "Medium", 77,
        ["FastAPI", "Stripe"], ["webhooks"], 214, 189, 27, 6))
    c.append(_c(18, "commit", "acme-labs/payments-engine",
        "Property-based tests for currency rounding",
        "Added property-based tests that fuzz currency rounding across 135 currencies, catching two silent cent-drift bugs.",
        "commit:acme-labs/payments-engine:7ba2910", "https://github.com/acme-labs/payments-engine/commit/7ba2910",
        "committed", _days_ago(33, 4), "Testing", "Medium", 59,
        ["Python", "Hypothesis"], ["testing"], None, 208, 3, 0))
    c.append(_c(19, "review", "acme-labs/payments-engine",
        "Review: locking strategy for the payout worker",
        "Wrote the decisive review on the payout worker's locking strategy, steering it to row-level locks before a costly deadlock shipped.",
        "review:acme-labs/payments-engine:226:991", "https://github.com/acme-labs/payments-engine/pull/226",
        "approved", _days_ago(11, 5), "Backend", "Medium", 55,
        ["Python", "PostgreSQL"], [], 226, 0, 0, 3))
    c.append(_c(20, "review", "acme-labs/infra-k8s-mesh",
        "Review: tighten default NetworkPolicy",
        "Reviewed the zero-trust NetworkPolicy change and flagged the DNS egress gap that would have broken cluster addons.",
        "review:acme-labs/infra-k8s-mesh:74:887", "https://github.com/acme-labs/infra-k8s-mesh/pull/74",
        "commented", _days_ago(20, 7), "Security", "Medium", 58,
        ["Kubernetes"], [], 74, 0, 0, 4))
    return c


def _skills() -> list[dict]:
    rows = [
        ("Python", "High", 95, 9, 3, 7),
        ("FastAPI", "High", 88, 4, 2, 12),
        ("React", "High", 84, 5, 1, 30),
        ("TypeScript", "High", 81, 4, 1, 30),
        ("Redis", "High", 78, 4, 1, 5),
        ("PostgreSQL", "Medium", 72, 4, 1, 7),
        ("Kubernetes", "Medium", 70, 4, 1, 14),
        ("Stripe", "Medium", 66, 3, 1, 7),
        ("Terraform", "Medium", 64, 2, 1, 18),
        ("Docker", "Medium", 58, 3, 2, 16),
        ("Go", "Low", 42, 2, 1, 11),
    ]
    return [
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "confidence": confidence,
            "score": score,
            "evidence_count": count,
            "repo_count": 1 if count <= 5 else (2 if count <= 6 else 3),
            "last_used_at": _days_ago(days_ago),
        }
        for name, confidence, score, count, _, days_ago in rows
    ]


def _insights() -> list[dict]:
    ev = lambda cid, label, url: [{"contribution_id": cid, "label": label, "url": url}]
    return [
        {
            "kind": "recruiter_summary",
            "title": "Recruiter summary",
            "content": (
                "Alex Chen is a backend-leaning full-stack engineer whose verified work sits at the intersection of "
                "distributed systems and reliability. His public history shows a consistent pattern: he picks up the "
                "hardest failure modes — cache stampedes, double charges, deploy risk — and closes them with tested, "
                "reviewable changes.\n\n"
                "Across four repositories he has landed 11 merged pull requests with a median impact score of 81, "
                "spanning FastAPI, React, Kubernetes and payments infrastructure. His reviews are load-bearing too: "
                "twice he caught production-bound defects in other engineers' changes before they shipped.\n\n"
                "For a team that values engineers who leave systems safer than they found them, this track record is "
                "unusually easy to verify — every claim below links to the exact pull request that backs it."
            ),
        },
        {
            "kind": "bullet",
            "title": "Eliminated cache-stampede outages",
            "content": "Designed adaptive TTL eviction with single-flight locking for a distributed FastAPI cache, ending cache-stampede outages under bursty read traffic (14 review rounds, merged).",
            "evidence": ev("demo-001", "PR · acme-labs/fastapi-distributed-cache", "https://github.com/acme-labs/fastapi-distributed-cache/pull/184"),
            "pinned": True,
        },
        {
            "kind": "bullet",
            "title": "Protected payments from double charges",
            "content": "Introduced idempotency keys across the Stripe checkout path of a payments engine, eliminating the double-charge class of support tickets on high-volume flows.",
            "evidence": ev("demo-015", "PR · acme-labs/payments-engine", "https://github.com/acme-labs/payments-engine/pull/233"),
            "pinned": True,
        },
        {
            "kind": "bullet",
            "title": "100k-row grids at 60fps",
            "content": "Virtualized a React data-grid to render 100,000-row datasets at 60fps, cutting worst-case render time from 4.2s to 380ms for enterprise customers.",
            "evidence": ev("demo-006", "PR · acme-labs/react-data-grid", "https://github.com/acme-labs/react-data-grid/pull/412"),
        },
        {
            "kind": "bullet",
            "title": "Zero-incident deploys",
            "content": "Implemented blue-green Kubernetes deploys with readiness-gated traffic shifting, removing deploy-related incidents across six consecutive releases.",
            "evidence": ev("demo-011", "PR · acme-labs/infra-k8s-mesh", "https://github.com/acme-labs/infra-k8s-mesh/pull/77"),
        },
        {
            "kind": "bullet",
            "title": "40x faster ledger close",
            "content": "Migrated a payments ledger to partitioned PostgreSQL tables with zero downtime, cutting month-end close queries from 40s to 3s.",
            "evidence": ev("demo-016", "PR · acme-labs/payments-engine", "https://github.com/acme-labs/payments-engine/pull/221"),
        },
        {
            "kind": "star",
            "title": "Solved a cache-stampede outage pattern",
            "situation": "The shared cache layer was failing under burst traffic — every key expiry triggered a thundering herd of identical database reads, and the service fell over during its busiest hours.",
            "task": "Own the fix end-to-end without freezing the feature roadmap, and make the fix provable under load.",
            "action": "He profiled the failure mode, designed adaptive TTL eviction with jittered refresh behind a single-flight lock, shipped it behind a feature flag, and added load tests that reproduce the stampede at 10x baseline traffic — then closed the residual race a reviewer found with a deterministic regression test.",
            "result": "Cache-related database load dropped 94%, and the service has seen zero stampede incidents since. The pull request became the reference pattern other services copied.",
            "evidence": ev("demo-001", "PR #184 · fastapi-distributed-cache", "https://github.com/acme-labs/fastapi-distributed-cache/pull/184")
            + ev("demo-002", "PR #191 · fastapi-distributed-cache", "https://github.com/acme-labs/fastapi-distributed-cache/pull/191"),
            "pinned": True,
        },
        {
            "kind": "star",
            "title": "Protected a payments engine from double charges",
            "situation": "Customers were occasionally charged twice when network retries hit the checkout path between the payment intent and its confirmation — a money-losing, trust-destroying bug.",
            "task": "Make every charge at-most-once without adding latency to the happy path.",
            "action": "He introduced idempotency keys end-to-end: generated at checkout, stored with unique constraints in PostgreSQL, enforced in the Stripe integration, and covered by property-based tests that fuzz the retry paths across currencies.",
            "result": "Double-charge support tickets went to zero, and the pattern was adopted by the webhook replay endpoint that shipped the following month.",
            "evidence": ev("demo-015", "PR #233 · payments-engine", "https://github.com/acme-labs/payments-engine/pull/233")
            + ev("demo-018", "Commit · payments-engine", "https://github.com/acme-labs/payments-engine/commit/7ba2910"),
        },
        {
            "kind": "star",
            "title": "Made a 100k-row data grid feel instant",
            "situation": "Enterprise customers loading six-figure datasets watched the grid freeze for four seconds on mount, and support had a backlog of complaints tagged 'slow grid'.",
            "task": "Get large datasets to render at interactive framerates without breaking the public API for dozens of internal consumers.",
            "action": "He introduced windowed rendering with a measured trade-off study, kept the existing API surface intact, and paired it with keyboard and ARIA work so the performance fix and the accessibility audit landed together.",
            "result": "Worst-case render fell from 4.2s to 380ms, the 'slow grid' backlog emptied, and the grid passed two enterprise accessibility audits unblocked.",
            "evidence": ev("demo-006", "PR #412 · react-data-grid", "https://github.com/acme-labs/react-data-grid/pull/412")
            + ev("demo-007", "PR #398 · react-data-grid", "https://github.com/acme-labs/react-data-grid/pull/398"),
        },
    ]


async def _ensure_demo_token(uid: str) -> None:
    """The demo dossier stays effectively permanent so the preview link never rots."""
    await db.share_tokens.update_one(
        {"token": DEMO_SHARE_TOKEN},
        {
            "$set": {"user_id": uid, "revoked": False, "expires_at": _days_ago(-3650)},
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _days_ago(1)},
        },
        upsert=True,
    )


async def ensure_demo_profile() -> dict:
    """Return the demo user, creating (or re-seeding) their data when missing."""
    user = await db.users.find_one({"is_demo": True})
    if user and await db.contributions.count_documents({"user_id": user["id"]}) > 0:
        await _ensure_demo_token(user["id"])
        return user

    if not user:
        user = {
            "id": str(uuid.uuid4()),
            "is_demo": True,
            "github_id": None,
            "login": "alexchen-dev",
            "name": "Alex Chen",
            "email": None,
            "avatar_url": "https://github.com/github.png",
            "profile_url": "https://github.com/alexchen-dev",
            "github_token": None,
            "last_synced_at": _days_ago(1),
            "created_at": _days_ago(200),
        }
        await db.users.insert_one(dict(user))
    uid = user["id"]

    # Re-seed the derived collections for this demo user only (plus orphaned demo rows
    # an earlier seeder version wrote without a user_id).
    await db.contributions.delete_many({"user_id": uid})
    await db.contributions.delete_many({"user_id": None, "id": {"$regex": "^demo-"}})
    await db.skills.delete_many({"user_id": uid})
    await db.skills.delete_many({"user_id": None, "name": {"$in": [s["name"] for s in _skills()]}})
    await db.insights.delete_many({"user_id": uid})

    await db.contributions.insert_many([{**c, "user_id": uid} for c in _contributions()])
    await db.skills.insert_many([{**s, "user_id": uid} for s in _skills()])
    now = _days_ago(1)
    docs = []
    for i, ins in enumerate(_insights()):
        doc = {
            "id": f"demo-insight-{i:02d}",
            "user_id": uid,
            "kind": ins["kind"],
            "title": ins["title"],
            "content": ins.get("content", ""),
            "situation": ins.get("situation"),
            "task": ins.get("task"),
            "action": ins.get("action"),
            "result": ins.get("result"),
            "evidence": ins.get("evidence", []),
            "pinned": ins.get("pinned", False),
            "created_at": now,
        }
        docs.append(doc)
    await db.insights.insert_many(docs)
    await _ensure_demo_token(uid)
    return user
