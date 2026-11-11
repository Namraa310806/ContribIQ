"""Job-tailored insights: rewrite bullets + STAR answers for one job description.

Same evidence rules as insights_gen — every claim must trace to a stored contribution.
LLM first; keyword-overlap template fallback so the feature never hard-fails.
"""

import json
import logging
import re
import uuid
from typing import List

from lib.llm import chat as llm_chat, is_configured as llm_configured
from services.insights_gen import _link_evidence, _top

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a technical recruiter and career coach tailoring a developer's verified GitHub evidence "
    "to one specific job description. Produce: "
    "1) match_summary — 2-3 honest sentences on how the evidence fits the role, naming any clear gaps; "
    "2) bullets — 5 resume bullets rewritten in the job's language and priorities, each 'title' (short) + "
    "'content' (one Action-Context-Result bullet, max 220 chars) + evidence_idx (1-3 indexes into contributions); "
    "3) star_answers — 3 interview stories most relevant to this role, each 'title' + situation/task/action/result "
    "+ evidence_idx (1-3 indexes). Use only facts present in the contributions — never invent metrics, "
    "employers or technologies. "
    'Respond with ONLY JSON: {"match_summary": str, "bullets": [...], "star_answers": [...]}.'
)

_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have", "has", "this", "that",
    "from", "who", "what", "work", "team", "role", "years", "experience", "strong", "ability", "about",
    "into", "they", "their", "can", "all", "any", "not", "but", "use", "using", "including", "etc",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]{3,}", (text or "").lower()) if t not in _STOP}


def _payload(job_description: str, contributions: List[dict], skills: List[dict]) -> dict:
    return {
        "job_description": job_description[:6000],
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
            }
            for i, c in enumerate(contributions)
        ],
        "skills": [{"name": s.get("name"), "confidence": s.get("confidence")} for s in skills[:12]],
    }


def _bullet(title: str, content: str, evidence: list) -> dict:
    return {"id": str(uuid.uuid4()), "kind": "bullet", "title": title[:90], "content": content[:300], "evidence": evidence}


def _star(s: dict, evidence: list) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "kind": "star",
        "title": str(s.get("title", "Interview story"))[:90],
        "content": "",
        "situation": str(s.get("situation", ""))[:500],
        "task": str(s.get("task", ""))[:500],
        "action": str(s.get("action", ""))[:800],
        "result": str(s.get("result", ""))[:500],
        "evidence": evidence,
    }


def _fallback(job_description: str, pool: List[dict], skills: List[dict]) -> dict:
    jd = _tokens(job_description)

    def score(c: dict) -> int:
        text = f"{c.get('title', '')} {c.get('summary', '')} {' '.join(c.get('technologies', []))} {c.get('category', '')}"
        return len(jd & _tokens(text)) * 10 + c.get("impact_score", 0) // 10

    ranked = sorted(range(len(pool)), key=lambda i: score(pool[i]), reverse=True)
    matched_skills = [s["name"] for s in skills if s.get("name", "").lower() in job_description.lower()]
    summary = (
        f"Strongest overlap with this role: {', '.join(matched_skills[:5])}. "
        if matched_skills
        else "The role's keywords overlap only lightly with the analyzed evidence. "
    ) + f"The {min(5, len(ranked))} contributions below are ranked by relevance to the job description."
    bullets = []
    for i in ranked[:5]:
        c = pool[i]
        bullets.append(
            _bullet(c.get("title", ""), f"{c.get('summary') or c.get('title', '')} ({c.get('category')}, impact {c.get('impact_score')}/100)", _link_evidence([i], pool))
        )
    stars = []
    for i in ranked[:3]:
        c = pool[i]
        stars.append(
            _star(
                {
                    "title": c.get("title", ""),
                    "situation": f"The team needed this change in {c.get('repo', 'the codebase')}.",
                    "task": "Own the change end-to-end in a way that matches what this role asks for.",
                    "action": c.get("summary") or "Designed, implemented, tested and shipped the change.",
                    "result": f"Landed as a {c.get('state') or 'completed'} {str(c.get('kind', 'pr')).upper()} with impact score {c.get('impact_score')}/100.",
                },
                _link_evidence([i], pool),
            )
        )
    return {"match_summary": summary, "bullets": bullets, "stars": stars}


async def generate_tailored(job_description: str, contributions: List[dict], skills: List[dict]) -> dict:
    """Returns {match_summary, bullets, stars}. Never raises."""
    pool = _top(contributions, 25)
    if llm_configured():
        try:
            raw = await llm_chat(_SYSTEM, json.dumps(_payload(job_description, pool, skills)))
            text = re.sub(r"```(?:json)?", "", raw if isinstance(raw, str) else str(raw)).strip()
            start, end = text.find("{"), text.rfind("}")
            parsed = json.loads(text[start : end + 1]) if start != -1 and end != -1 else {}
            bullets = [
                _bullet(str(b.get("title", "Resume bullet")), str(b["content"]), _link_evidence(b.get("evidence_idx"), pool))
                for b in (parsed.get("bullets") or [])[:6]
                if isinstance(b, dict) and b.get("content")
            ]
            stars = [
                _star(s, _link_evidence(s.get("evidence_idx"), pool))
                for s in (parsed.get("star_answers") or [])[:4]
                if isinstance(s, dict) and s.get("result")
            ]
            if bullets or stars:
                return {
                    "match_summary": str(parsed.get("match_summary") or "")[:800],
                    "bullets": bullets,
                    "stars": stars,
                }
        except Exception as exc:
            logger.warning("tailor LLM call failed (%s) — keyword fallback", exc)
    return _fallback(job_description, pool, skills)
