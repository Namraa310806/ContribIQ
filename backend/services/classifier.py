"""Batched LLM classification of contributions (~10 per call) with a heuristic fallback.

Falls back to keyword heuristics whenever the LLM is unavailable, so the pipeline
never hard-fails on a model outage.
"""

import json
import logging
import re
from typing import List

from lib.llm import chat as llm_chat, is_configured as llm_configured

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Security", "Backend", "Frontend", "DevOps", "Database", "API",
    "Testing", "Performance", "Documentation", "Refactoring", "Feature",
    "Bug Fix", "Other",
]
COMPLEXITIES = {"Low", "Medium", "High"}
BATCH_SIZE = 10

CANON_TECH = {
    "fastapi": "FastAPI", "react": "React", "typescript": "TypeScript", "ts": "TypeScript",
    "python": "Python", "redis": "Redis", "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "kubernetes": "Kubernetes", "k8s": "Kubernetes", "terraform": "Terraform", "stripe": "Stripe",
    "go": "Go", "golang": "Go", "aws": "AWS", "docker": "Docker", "prometheus": "Prometheus",
    "webpack": "Webpack", "javascript": "JavaScript", "orjson": "orjson", "hypothesis": "Hypothesis",
}

_SYSTEM = (
    "You are a precise senior engineering manager triaging a developer's public GitHub work. "
    "You are given structured PR evidence: changed-file categories (source/test/docs/config), "
    "CI status, merge state, review counts, and repository eligibility. Classify the engineering "
    "substance — a small concurrency fix is not 'Low' just because it is small, and a docs-only "
    "PR is not 'High' just because it is large. For each item you output: category (exactly one of: "
    + ", ".join(CATEGORIES)
    + "), complexity (Low, Medium or High), impact_score (0-100 integer, 90+ means outage-level or "
    "money-critical work, 70+ means significant system change, 50+ meaningful improvement, below is routine), "
    "technologies (0-6 canonical names like FastAPI, React, Kubernetes), and summary (one plain-language "
    "sentence, max 160 chars, stating what was done and why it matters). "
    "Respond with ONLY a JSON array aligned to the input order — no prose, no code fences."
)

_KEYWORDS = [
    ("security", "Security"), ("cve", "Security"), ("vulnerab", "Security"), ("idempoten", "Security"),
    ("auth", "Security"), ("signature", "Security"), ("race", "Bug Fix"), ("leak", "Bug Fix"),
    ("fix", "Bug Fix"), ("bug", "Bug Fix"), ("crash", "Bug Fix"), ("deadlock", "Bug Fix"),
    ("k8s", "DevOps"), ("kubernetes", "DevOps"), ("deploy", "DevOps"), ("terraform", "DevOps"),
    ("infra", "DevOps"), ("docker", "DevOps"), ("ci", "DevOps"), ("failover", "DevOps"),
    ("perf", "Performance"), ("latency", "Performance"), ("cache", "Performance"), ("bundle", "Performance"),
    ("optimi", "Performance"), ("virtuali", "Performance"), ("fast", "Performance"),
    ("test", "Testing"), ("coverage", "Testing"), ("migration", "Database"), ("schema", "Database"),
    ("ledger", "Database"), ("partition", "Database"), ("sql", "Database"),
    ("ui", "Frontend"), ("react", "Frontend"), ("css", "Frontend"), ("grid", "Frontend"),
    ("aria", "Frontend"), ("accessib", "Frontend"), ("api", "API"), ("webhook", "API"),
    ("endpoint", "API"), ("doc", "Documentation"), ("rfc", "Documentation"), ("readme", "Documentation"),
    ("refactor", "Refactoring"), ("clean", "Refactoring"),
]


def _fallback(item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('body', '')} {item.get('repo', '')}".lower()
    category = next((cat for frag, cat in _KEYWORDS if frag in text), "Feature" if item.get("kind") == "pr" else "Other")
    impact = min(
        95,
        35
        + item.get("comments", 0) * 4
        + min(30, (item.get("additions", 0) + item.get("deletions", 0)) // 40)
        + (15 if item.get("state") == "merged" else 0),
    )
    complexity = "High" if impact >= 80 else ("Medium" if impact >= 55 else "Low")
    return {"category": category, "complexity": complexity, "impact_score": impact, "technologies": [], "summary": ""}


def _extract_json_array(text: str) -> list:
    cleaned = re.sub(r"```(?:json)?", "", text or "").strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in model output")
    return json.loads(cleaned[start : end + 1])


def _canon(name: str) -> str:
    return CANON_TECH.get(name.strip().lower(), name.strip().title())


def _norm_result(res: dict, item: dict) -> dict:
    category = res.get("category") if res.get("category") in CATEGORIES else _fallback(item)["category"]
    complexity = res.get("complexity") if res.get("complexity") in COMPLEXITIES else "Medium"
    try:
        impact = max(0, min(100, int(res.get("impact_score", 0))))
    except (TypeError, ValueError):
        impact = _fallback(item)["impact_score"]
    techs = [_canon(t) for t in (res.get("technologies") or []) if isinstance(t, str) and t.strip()][:6]
    summary = str(res.get("summary") or "")[:200]
    return {"category": category, "complexity": complexity, "impact_score": impact, "technologies": techs, "summary": summary}


async def classify_batch(items: List[dict]) -> List[dict]:
    """Classify one batch. Never raises — heuristics cover LLM failures."""
    if not items:
        return []
    if not llm_configured():
        logger.warning("LLM_API_KEY not set — using heuristic classification")
        return [_fallback(it) for it in items]

    payload = [
        {
            "idx": i,
            "kind": it.get("kind"),
            "repo": it.get("repo"),
            "repo_context": "own repository" if it.get("is_own_repo") else "independent codebase",
            "eligibility": it.get("eligibility_status") or ("own" if it.get("is_own_repo") else "external/unverified"),
            "title": it.get("title"),
            "body": (it.get("body") or "")[:400],
            "labels": it.get("labels", []),
            "state": it.get("state", ""),
            "merged": it.get("merged", False),
            "ci_status": it.get("ci_status") or "unknown",
            "file_categories": {
                cat: (info or {}).get("files", 0)
                for cat, info in (it.get("file_categories") or {}).items()
            } or None,
            # Bounded patch excerpts — real implementation evidence, capped so
            # the context window stays small. Absent patches mean "unavailable",
            # never "bad code".
            "patch_samples": (it.get("patch_samples") or [])[:2] or None,
            "linked_issues": it.get("linked_issue_count") or 0,
            "unique_reviewers": it.get("reviewers") or 0,
        }
        for i, it in enumerate(items)
    ]
    prompt = (
        "Classify these GitHub contributions. Return a JSON array with one object per idx "
        "having keys: category, complexity, impact_score, technologies, summary.\n\n"
        + json.dumps(payload)
    )
    try:
        raw = await llm_chat(_SYSTEM, prompt)
        parsed = _extract_json_array(raw if isinstance(raw, str) else str(raw))
        out = []
        for i, item in enumerate(items):
            res = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else {}
            out.append(_norm_result(res, item))
        return out
    except Exception as exc:
        logger.warning("classify_batch LLM call failed (%s) — heuristic fallback", exc)
        return [_fallback(it) for it in items]
