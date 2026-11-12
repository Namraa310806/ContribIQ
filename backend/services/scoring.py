"""Deterministic, explainable contribution scoring — PR-centric edition.

Architecture (Phase 5):
- Objective GitHub facts live in the evidence documents; this module is a pure
  function of those facts plus the classifier's category/complexity grade.
- Six independent dimensions (A–F) plus repository context and an evidence
  completeness/confidence rating. Technical merit and acceptance are scored
  separately: a merged trivial PR cannot outrank a substantial unmerged one on
  substance, and a closed PR is never treated as worthless.
- Eligibility gating: EXCLUDED_* repositories contribute zero collaboration
  credit; REVIEW_REQUIRED/UNKNOWN get reduced (never full) credit. Exclusion
  never deletes the underlying technical evidence.
- Raw additions/deletions/commit/comment/reviewer counts are log-dampened
  signals, never direct quality proxies.
- Missing evidence lowers confidence; it is never scored as a negative.
"""

import math
from typing import Optional

KIND_BASE = {"pr": 50, "issue": 25, "commit": 10, "review": 30}

# Skill aggregation weights — PRs are primary evidence, reviews second, issues
# third, commits supporting only (they explain implementation inside a PR).
KIND_WEIGHT = {"pr": 5, "review": 3, "issue": 2, "commit": 1}

# Collaboration credit multiplier by repository eligibility. Own-repo and
# controlled-org work must not inflate the open-source collaboration score.
ELIGIBILITY_COLLAB_FACTOR = {
    "ELIGIBLE_EXTERNAL": 1.0,
    "REVIEW_REQUIRED": 0.4,
    "UNKNOWN": 0.3,
    None: 0.5,  # legacy records without an eligibility verdict
}
ELIGIBILITY_COLLAB_FACTOR_EXCLUDED = 0.0  # EXCLUDED_SELF_OWNED / EXCLUDED_CONTROLLED_ORGANIZATION

# impact_score weights — acceptance and substance lead; volume signals are absent by design.
WEIGHTS = {
    "technical_substance": 0.22,
    "code_quality": 0.13,
    "testing": 0.12,
    "problem_significance": 0.13,
    "collaboration": 0.15,
    "acceptance": 0.15,
    "context": 0.10,
}

_CI_SUCCESS = {"success"}
_CI_FAILURE = {"failure", "error", "cancelled", "timed_out", "action_required"}


def _clamp(v: float) -> int:
    return max(0, min(100, round(v)))


def _log_size(additions: int, deletions: int) -> float:
    return math.log10((additions or 0) + (deletions or 0) + 1)


def _file_categories(item: dict) -> dict:
    return (item.get("file_categories") or {})


def _ci_status(item: dict) -> str:
    return (item.get("ci_status") or "unknown").lower()


def score_contribution(item: dict) -> dict:
    """Score one contribution. Returns {"impact_score", "dimensions", "confidence"}.

    Expected evidence fields on `item` (all optional — missing means unknown):
      kind, state, merged, draft, is_own_repo, eligibility_status,
      additions, deletions, changed_files, commits_count,
      review_count, approvals, change_requests, reviewers, comments,
      complexity (Low|Medium|High from classifier), category,
      file_categories {cat: {files, additions, deletions}}, files_total,
      patch_ratio, test_file_count, ci_status, linked_issue_count,
      author_replied (bool), reverted (bool)
    """
    kind = item.get("kind", "pr")
    state = (item.get("state") or "").lower()
    own_repo = bool(item.get("is_own_repo"))
    eligibility = item.get("eligibility_status")
    size = (item.get("additions") or 0) + (item.get("deletions") or 0)
    cats = _file_categories(item)
    src = cats.get("source") or {}
    test = cats.get("test") or {}
    docs = cats.get("docs") or {}
    files_total = item.get("files_total") or (item.get("changed_files") or 0)
    src_files = src.get("files", 0)
    test_files = test.get("files", 0)
    doc_files = docs.get("files", 0)
    src_changes = (src.get("additions") or 0) + (src.get("deletions") or 0)
    test_changes = (test.get("additions") or 0) + (test.get("deletions") or 0)
    ci = _ci_status(item)

    # ---------- A. Technical substance ----------
    if kind == "pr":
        substance = KIND_BASE["pr"]
        # Log-dampened engineering volume — a 30-line concurrency fix and a
        # 2,000-line docs change both stay in a sane band.
        substance += min(30, _log_size(size, 0) * 11)
        # Breadth across source files matters more than raw file count.
        substance += min(15, src_files * 2)
        # Layer spread: source + tests + config touched together suggests real work.
        layers = sum(1 for c in ("source", "test", "config") if (cats.get(c) or {}).get("files"))
        substance += min(10, layers * 4)
        # Non-source-only PRs (docs/config only) are inherently lower substance.
        if files_total and src_files == 0:
            substance = min(substance, 45)
        # Trivial diffs can't claim full PR substance — a typo fix is real work
        # but not architecturally significant. Threshold is deliberately small
        # so targeted critical fixes (30+ lines) are unaffected.
        if size <= 15:
            substance = min(substance, 50)
    elif kind == "commit":
        substance = KIND_BASE["commit"] + min(15, _log_size(size, 0) * 6)
    elif kind == "review":
        substance = KIND_BASE["review"] + 10
    elif kind == "issue":
        substance = KIND_BASE["issue"]
    else:
        substance = 20
    technical_substance = _clamp(substance)

    # ---------- B. Code quality & structure (deterministic proxy) ----------
    # Honest signals only: patch availability (we could inspect the diff),
    # scope discipline, test accompaniment, and config/docs hygiene.
    if kind == "pr":
        quality = 35
        quality += min(20, (item.get("patch_ratio") or 0) * 25)  # inspectable diff
        if test_files > 0 and src_files > 0:
            quality += 15  # code shipped with tests
        elif test_files > 0:
            quality += 8  # test-only change — still disciplined
        if src_files > 0 and doc_files == 0:
            quality += 5  # focused change, no doc churn
        if files_total and files_total <= 15:
            quality += 10  # tight scope
        elif files_total > 60:
            quality -= 10  # sprawling diff — reviewability cost
        # Large deletion-heavy refactors aren't auto-bad; neutral here.
    elif kind == "review":
        quality = 45
    else:
        quality = 40
    code_quality = _clamp(quality)

    # ---------- C. Testing & validation ----------
    # Test *files existing* proves nothing about execution; we score the
    # engineering practice (tests added/changed alongside source) and keep
    # CI execution as a separate, explicit signal.
    if kind == "pr":
        testing = 20
        test_added = item.get("test_files_added") or 0
        test_modified = item.get("test_files_modified") or 0
        test_removed = item.get("test_files_removed") or 0
        if test_files or test_added or test_modified:
            # New/changed tests accompanying source changes = real validation practice.
            practice = min(30, test_added * 10 + test_modified * 6)
            ratio = test_changes / max(1, src_changes)
            testing += min(35, practice + min(20, ratio * 30))
        if test_removed > test_added + test_modified and src_files > 0:
            testing -= 8  # net test removal alongside source changes is a smell
        if ci in _CI_SUCCESS:
            testing += 20
        elif ci in _CI_FAILURE:
            testing += 8  # CI ran and caught something — still evidence of validation
        # ci == "unknown"/"none": +0 — absence of CI is unknown, not failure.
    elif kind == "review":
        testing = 30
    else:
        testing = 25
    testing = _clamp(testing)

    # ---------- D. Problem significance ----------
    comp_grade = {"Low": 30, "Medium": 55, "High": 80}.get(item.get("complexity") or "Medium", 55)
    if kind == "pr":
        significance = comp_grade * 0.6
        significance += min(20, (item.get("linked_issue_count") or 0) * 10)  # traces to a reported problem
        labels = " ".join(item.get("labels") or []).lower()
        if any(k in labels for k in ("bug", "security", "critical", "regression")):
            significance += 12
        if (item.get("author_association") or "").upper() in ("MEMBER", "OWNER", "COLLABORATOR"):
            significance += 8  # maintainer-trusted contributor signal
        significance = min(100, significance)
    elif kind == "review":
        significance = comp_grade * 0.5 + 20
    else:
        significance = comp_grade * 0.4 + 15
    problem_significance = _clamp(significance)

    # ---------- E. Review & collaboration ----------
    # Effective exclusion: explicit verdict OR legacy own-repo flag with no verdict.
    effectively_excluded = eligibility in EXCLUDED_ALL or (eligibility is None and own_repo)
    if kind == "pr":
        collab = 0.0
        if effectively_excluded:
            pass  # own/controlled-org PRs earn zero OSS collaboration credit
        else:
            factor = ELIGIBILITY_COLLAB_FACTOR.get(eligibility, 0.5)
            review_count = item.get("review_count") or 0
            approvals = item.get("approvals") or 0
            change_requests = item.get("change_requests") or 0
            reviewers = item.get("reviewers") or 0
            comments = item.get("comments") or 0
            collab += 10  # baseline: proposing a change to a codebase
            collab += min(25, reviewers * 7)  # unique reviewers, not comment volume
            collab += min(20, approvals * 8)
            collab += min(18, change_requests * 9)  # iterative review engagement
            collab += min(10, comments * 1.5)
            if item.get("author_replied"):
                collab += 7  # responded to feedback
            collab *= factor
    elif kind == "review":
        st = state.upper()
        collab = {"APPROVED": 55, "CHANGES_REQUESTED": 45, "COMMENTED": 30, "DISMISSED": 15}.get(st, 25)
        # Reviews on own repos are weaker external-collaboration evidence.
        if own_repo:
            collab *= 0.5
    elif kind == "issue":
        collab = min(25, (item.get("comments") or 0) * 3)
    else:
        collab = 5
    collaboration = _clamp(collab)

    # ---------- F. Acceptance & integration ----------
    if kind == "pr":
        if state == "merged":
            acc = 88
            if item.get("draft"):
                acc = 70  # merged despite draft flag at fetch time — rare, dampen
            if item.get("reverted"):
                # Landed, then reverted: integration didn't stick. Not a verdict
                # on the engineering — substance/quality dimensions still count.
                acc = 55
            if (item.get("change_requests") or 0) > 0:
                acc = min(100, acc + 5)  # absorbed feedback and still landed
        elif state == "open":
            acc = 50 if not item.get("draft") else 30
        elif state == "closed":
            # Closed unmerged is NOT worthless — technical merit lives elsewhere.
            acc = 38
            if (item.get("review_count") or 0) > 0 or (item.get("approvals") or 0) > 0:
                acc = 48  # well-reviewed but not taken — maintainer choice, not failure
            if item.get("superseded"):
                # Work verifiably landed via another PR — partial acceptance credit.
                acc = 55
        else:
            acc = 40
    elif kind == "review":
        acc = {"approved": 80, "changes_requested": 62, "commented": 42, "dismissed": 25}.get(state, 40)
    elif kind == "issue":
        acc = 70 if state == "closed" else 35
    else:
        acc = 50
    acceptance = _clamp(acc)

    # ---------- Repository context ----------
    if kind in ("pr", "issue", "review"):
        if eligibility == "ELIGIBLE_EXTERNAL":
            ctx = 85
        elif eligibility in ("REVIEW_REQUIRED", "UNKNOWN"):
            ctx = 55
        elif eligibility in EXCLUDED_ALL or own_repo:
            ctx = 40
        else:
            ctx = 45 if own_repo else 75  # legacy records
        if (item.get("author_association") or "").upper() in ("MEMBER", "OWNER", "COLLABORATOR"):
            ctx = min(100, ctx + 10)
    else:
        ctx = 40 if own_repo else 55
    context = _clamp(ctx)

    # ---------- Confidence / evidence completeness ----------
    confidence = _confidence(item, kind)

    impact = _clamp(
        WEIGHTS["technical_substance"] * technical_substance
        + WEIGHTS["code_quality"] * code_quality
        + WEIGHTS["testing"] * testing
        + WEIGHTS["problem_significance"] * problem_significance
        + WEIGHTS["collaboration"] * collaboration
        + WEIGHTS["acceptance"] * acceptance
        + WEIGHTS["context"] * context
    )

    return {
        "impact_score": impact,
        "confidence": confidence,
        "dimensions": {
            "technical_substance": technical_substance,
            "code_quality": code_quality,
            "testing": testing,
            "problem_significance": problem_significance,
            "collaboration": collaboration,
            "acceptance": acceptance,
            "context": context,
        },
    }


EXCLUDED_ALL = {"EXCLUDED_SELF_OWNED", "EXCLUDED_CONTROLLED_ORGANIZATION"}


def _confidence(item: dict, kind: str) -> str:
    """Evidence completeness → confidence. Missing data is 'unknown', not bad."""
    if kind != "pr":
        return "Medium"
    score = 0
    if item.get("files_total"):
        score += 2
    if (item.get("patch_ratio") or 0) >= 0.6:
        score += 2
    elif (item.get("patch_ratio") or 0) > 0:
        score += 1
    if item.get("ci_status") not in (None, "", "unknown"):
        score += 1
    if (item.get("review_count") or 0) > 0 or item.get("evidence_status") == "complete":
        score += 1
    if item.get("evidence_status") == "partial":
        score -= 1
    if item.get("evidence_status") == "failed":
        return "Insufficient"
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"
