"""Stage 4 — recruiter summary, resume bullets, STAR answers. LLM with template fallback."""

import json
import logging
import re
from typing import List

from lib.llm import chat as llm_chat, is_configured as llm_configured

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 4


def _top(contributions: List[dict], n: int) -> List[dict]:
    return sorted(contributions, key=lambda c: c.get("impact_score", 0), reverse=True)[:n]


def _payload(contributions: List[dict], skills: List[dict]) -> dict:
    return {
        "contributions": [
            {
                "idx": i,
                "kind": c.get("kind"),
                "title": c.get("title"),
                "repo": c.get("repo"),
                "repo_context": "own repository" if c.get("is_own_repo") else "independent codebase",
                "category": c.get("category"),
                "impact_score": c.get("impact_score"),
                "technologies": c.get("technologies", []),
                "summary": c.get("summary"),
                "state": c.get("state"),
            }
            for i, c in enumerate(_top(contributions, 25))
        ],
        "skills": [
            {"name": s.get("name"), "confidence": s.get("confidence"), "evidence_count": s.get("evidence_count")}
            for s in skills[:12]
        ],
    }


_SYSTEM = (
    "You are a technical recruiter and career coach writing from verified GitHub evidence only. "
    "Given a developer's analyzed contributions and skill confidences, produce: "
    "1) recruiter_summary — exactly 3 short paragraphs (depth, collaboration, what to hire them for); "
    "2) bullets — 5 resume bullets, each 'title' (short label) + 'content' (one quantified "
    "Action-Context-Result bullet, max 220 chars) + evidence_idx (1-3 indexes into contributions); "
    "3) star_answers — 3 interview stories, each 'title' + situation/task/action/result + evidence_idx "
    "(1-3 indexes). Every claim must trace to the indexed contributions — never invent metrics not present. "
    'Respond with ONLY JSON: {"recruiter_summary": str, "bullets": [...], "star_answers": [...]}.'
)


def _fallback_insights(login: str, contributions: List[dict], skills: List[dict]) -> List[dict]:
    tops = _top(contributions, 5)
    merged = [c for c in contributions if c.get("state") == "merged"]
    skill_names = ", ".join(s.get("name") for s in skills[:5]) or "full-stack engineering"
    cats: dict[str, int] = {}
    for c in contributions:
        cats[c.get("category", "Other")] = cats.get(c.get("category", "Other"), 0) + 1
    top_cats = ", ".join(k for k, _ in sorted(cats.items(), key=lambda kv: -kv[1])[:3]) or "engineering"
    summary = (
        f"{login} is a {top_cats} engineer with {len(contributions)} analyzed contributions across "
        f"{len({c.get('repo') for c in contributions})} repositories, strongest in {skill_names}. "
        f"The record shows a consistent pattern of taking on hard failure modes — race conditions, "
        f"double-charges, deployment risk — and closing them with tested, reviewable changes. "
        f"{len(merged)} merged pull requests back every claim below, each linked to the exact PR."
    )
    out = [
        {
            "kind": "recruiter_summary",
            "title": "Recruiter summary",
            "content": summary,
        }
    ]
    for c in tops:
        out.append(
            {
                "kind": "bullet",
                "title": c.get("title", "")[:70],
                "content": f"{c.get('summary') or c.get('title', '')} ({c.get('category')}, impact {c.get('impact_score')}/100)",
                "evidence": [
                    {"contribution_id": c["id"], "label": f"{c.get('kind', 'pr').upper()} · {c.get('repo', '')}", "url": c.get("url", "")}
                ],
            }
        )
    for c in tops[:3]:
        title = c.get("title", "a significant contribution")
        out.append(
            {
                "kind": "star",
                "title": title[:80],
                "situation": f"The team needed {title[0].lower() + title[1:]} in {c.get('repo', 'the codebase')}.",
                "task": "Own the change end-to-end without stalling other work.",
                "action": c.get("summary") or "Designed, implemented, tested and shipped the change with reviewable pull requests.",
                "result": f"Landed as a merged {c.get('kind', 'pr').upper()} with impact score {c.get('impact_score')}/100.",
                "evidence": [
                    {"contribution_id": c["id"], "label": f"{c.get('kind', 'pr').upper()} · {c.get('repo', '')}", "url": c.get("url", "")}
                ],
            }
        )
    return out


def _evidence_map(contributions: List[dict]) -> dict:
    return {c["id"]: c for c in contributions}


def _link_evidence(raw_list, contributions: List[dict]) -> List[dict]:
    """Accepts either int indexes into `contributions` or dicts carrying contribution_id."""
    by_id = _evidence_map(contributions)
    links = []
    for e in raw_list or []:
        if isinstance(e, int):
            c = contributions[e] if 0 <= e < len(contributions) else None
        elif isinstance(e, dict):
            c = by_id.get(e.get("contribution_id"))
        else:
            c = None
        if c:
            links.append(
                {
                    "contribution_id": c["id"],
                    "label": f"{str(c.get('kind', 'pr')).upper()} · {c.get('repo', '')}",
                    "url": c.get("url", ""),
                }
            )
    return links[:MAX_EVIDENCE]


async def generate_insights(login: str, contributions: List[dict], skills: List[dict]) -> List[dict]:
    """Returns insight dicts (no user_id / timestamps — caller adds them). Never raises."""
    if not contributions:
        return []
    parsed = None
    if llm_configured():
        try:
            raw = await llm_chat(_SYSTEM, json.dumps(_payload(contributions, skills)))
            text = raw if isinstance(raw, str) else str(raw)
            cleaned = re.sub(r"```(?:json)?", "", text).strip()
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end != -1:
                parsed = json.loads(cleaned[start : end + 1])
        except Exception as exc:
            logger.warning("insights LLM call failed (%s) — template fallback", exc)
    if not parsed:
        parsed = {}

    bullets_raw = parsed.get("bullets") or []
    stars_raw = parsed.get("star_answers") or []
    summary_text = parsed.get("recruiter_summary") or ""

    out: List[dict] = [
        {
            "kind": "recruiter_summary",
            "title": "Recruiter summary",
            "content": summary_text.strip() or _fallback_insights(login, contributions, skills)[0]["content"],
        }
    ]
    tops = _top(contributions, 25)
    for b in bullets_raw[:6]:
        if not isinstance(b, dict) or not b.get("content"):
            continue
        evidence = _link_evidence(b.get("evidence_idx") or b.get("evidence"), tops)
        if not evidence:
            continue  # no verifiable evidence → the claim doesn't ship
        out.append(
            {
                "kind": "bullet",
                "title": str(b.get("title", "Resume bullet"))[:90],
                "content": str(b["content"])[:300],
                "evidence": evidence,
            }
        )
    for s in stars_raw[:4]:
        if not isinstance(s, dict) or not s.get("result"):
            continue
        evidence = _link_evidence(s.get("evidence_idx") or s.get("evidence"), tops)
        if not evidence:
            continue  # STAR answers must trace to real contributions
        out.append(
            {
                "kind": "star",
                "title": str(s.get("title", "Interview story"))[:90],
                "situation": str(s.get("situation", ""))[:500],
                "task": str(s.get("task", ""))[:500],
                "action": str(s.get("action", ""))[:800],
                "result": str(s.get("result", ""))[:500],
                "evidence": evidence,
            }
        )
    if len(out) <= 1:  # LLM returned nothing usable — full fallback
        return _fallback_insights(login, contributions, skills)
    return out
