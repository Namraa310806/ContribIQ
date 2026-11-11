"""Deterministic, explainable contribution scoring.

The LLM never decides engineering value — it classifies category/complexity and writes
summaries. impact_score and the dimension subscores here are pure functions of GitHub
facts (kind, size, merge state, review activity, repo ownership), so they are
reproducible and auditable.
"""

import math

KIND_BASE = {"pr": 50, "issue": 25, "commit": 10, "review": 30}

# Skill aggregation weights — PRs are primary evidence, reviews second, issues third,
# commits supporting only (they explain implementation, they don't prove collaboration).
KIND_WEIGHT = {"pr": 4, "review": 3, "issue": 2, "commit": 1}


def _clamp(v: float) -> int:
    return max(0, min(100, round(v)))


def score_contribution(item: dict) -> dict:
    """item must already carry classification fields (complexity) when available.

    Returns {"impact_score": int, "dimensions": {substance, collaboration, acceptance,
    context, complexity_problem}} — each 0-100.
    """
    kind = item.get("kind", "pr")
    size = (item.get("additions") or 0) + (item.get("deletions") or 0)
    own_repo = bool(item.get("is_own_repo"))
    state = (item.get("state") or "").lower()
    review_count = item.get("review_count") or 0
    approvals = item.get("approvals") or 0
    change_requests = item.get("change_requests") or 0
    comments = item.get("comments") or 0

    # 1 — Technical substance: how much engineering work the artifact represents.
    substance = KIND_BASE.get(kind, 20)
    if kind == "pr":
        substance += min(25, math.log10(size + 1) * 9)
        substance += min(10, (item.get("changed_files") or 0) // 10)
        substance += min(10, (item.get("commits_count") or 0) // 5)
    elif kind == "commit":
        substance += min(15, math.log10(size + 1) * 6)
    elif kind == "review":
        substance += 10
    substance = _clamp(substance)

    # 2 — Collaboration: meaningful interaction with a codebase/team.
    collab = 0
    if kind == "pr":
        collab += 5 if own_repo else 20  # external maintained codebase is stronger evidence
        collab += min(20, review_count * 4)
        collab += min(15, approvals * 7)
        collab += min(15, change_requests * 8)  # requested-changes cycles = real review engagement
        collab += min(10, comments * 2)
    elif kind == "review":
        st = state.upper()
        collab += {"APPROVED": 30, "CHANGES_REQUESTED": 22, "COMMENTED": 14}.get(st, 12)
    elif kind == "issue":
        collab += min(20, comments * 3)
    collab = _clamp(collab)

    # 3 — Acceptance: was the work merged / the review decisive / the issue resolved?
    if kind == "pr":
        acc = {"merged": 90, "open": 45, "closed": 15}.get(state, 30)
        if item.get("draft"):
            acc = min(acc, 30)
        if state == "merged" and change_requests > 0:
            acc = min(100, acc + 5)  # absorbed feedback and still landed
    elif kind == "review":
        acc = {"approved": 80, "changes_requested": 60, "commented": 40, "dismissed": 25}.get(state, 40)
    elif kind == "issue":
        acc = 70 if state == "closed" else 35
    else:
        acc = 50
    acc = _clamp(acc)

    # 4 — Codebase context: independently maintained project > own repo > unknown.
    if kind in ("pr", "issue", "review"):
        ctx = 45 if own_repo else 80
        if (item.get("author_association") or "").upper() in ("MEMBER", "OWNER", "COLLABORATOR"):
            ctx = min(100, ctx + 10)
    else:
        ctx = 40 if own_repo else 55
    ctx = _clamp(ctx)

    # 5 — Problem complexity: deterministic proxy until the classifier's grade lands;
    #     callers pass the LLM complexity through `item["complexity"]` when known.
    comp = (item.get("complexity") or "Medium")
    cplx = {"Low": 30, "Medium": 55, "High": 80}.get(comp, 55)

    # Headline score — weighted so acceptance and collaboration carry real weight,
    # but a huge diff alone can never dominate.
    impact = _clamp(0.30 * substance + 0.25 * collab + 0.30 * acc + 0.15 * ctx)

    return {
        "impact_score": impact,
        "dimensions": {
            "substance": substance,
            "collaboration": collab,
            "acceptance": acc,
            "context": ctx,
            "problem_complexity": cplx,
        },
    }
