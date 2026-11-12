"""Scoring calibration — labelled PR fixtures ranked by the deterministic scorer.

Methodology (see backend/CALIBRATION.md): each fixture encodes the evidence a
real PR would produce (file categories, test statuses, CI, reviews, outcome).
We assert *ordering invariants* a competent evaluator would agree with, not
exact scores — the weights are engineering judgement, not validated psychometrics.
"""

from services.scoring import score_contribution
from tests.fixtures.pr_eval_cases import CASES, EXPECTATIONS

CONF_RANK = {"Insufficient": 0, "Low": 1, "Medium": 2, "High": 3}


def _score(name):
    return score_contribution(CASES[name])


def test_all_cases_produce_bounded_scores():
    for name in CASES:
        s = _score(name)
        assert 0 <= s["impact_score"] <= 100, name
        assert all(0 <= v <= 100 for v in s["dimensions"].values()), name
        assert s["confidence"] in CONF_RANK, name


def test_expectation_bands_hold():
    for name, (min_sub, max_sub, min_testing, conf_floor) in EXPECTATIONS.items():
        s = _score(name)
        d = s["dimensions"]
        assert min_sub <= d["technical_substance"] <= max_sub, (
            f"{name}: substance {d['technical_substance']} outside [{min_sub},{max_sub}]"
        )
        assert d["testing"] >= min_testing, f"{name}: testing {d['testing']} < {min_testing}"
        assert CONF_RANK[s["confidence"]] >= CONF_RANK[conf_floor], name


def test_security_and_race_fix_outrank_docs_only():
    docs = _score("docs_only")
    for name in ("critical_race_fix", "security_fix", "concurrency_fix"):
        s = _score(name)
        assert s["dimensions"]["problem_significance"] > docs["dimensions"]["problem_significance"], name
        assert s["impact_score"] > docs["impact_score"], name


def test_substance_is_independent_of_acceptance():
    """The concurrency fix is closed-unmerged but substantial; the trivial
    merged typo is the opposite. Substance must rank the real work higher even
    though acceptance ranks the merged one higher."""
    substantial = _score("concurrency_fix")
    trivial = _score("minimal_review_merged")
    assert substantial["dimensions"]["technical_substance"] > trivial["dimensions"]["technical_substance"]
    assert substantial["dimensions"]["acceptance"] < trivial["dimensions"]["acceptance"]


def test_unmerged_substantial_work_keeps_technical_credit():
    s = _score("heavy_review_unmerged")
    assert s["dimensions"]["technical_substance"] >= 55
    assert s["dimensions"]["collaboration"] > 40  # real review engagement counts
    assert s["dimensions"]["acceptance"] < 88   # but it didn't land


def test_reverted_pr_keeps_merit_but_loses_acceptance():
    s = _score("reverted_pr")
    assert s["dimensions"]["acceptance"] < _score("api_change")["dimensions"]["acceptance"]
    assert s["dimensions"]["technical_substance"] >= 50  # merit preserved


def test_own_repo_earns_no_oss_collaboration():
    s = _score("own_repo_feature")
    assert s["dimensions"]["collaboration"] == 0
    assert s["dimensions"]["context"] <= 45
    # …but the engineering evidence itself is still scored.
    assert s["dimensions"]["technical_substance"] >= 40


def test_test_only_pr_scores_testing_not_inflated_substance():
    s = _score("test_only")
    assert s["dimensions"]["testing"] >= 50
    assert s["dimensions"]["technical_substance"] < 80


def test_docs_only_never_looks_like_engineering_substance():
    s = _score("docs_only")
    assert s["dimensions"]["technical_substance"] <= 50
    # 2,500 changed lines of docs must not produce a high substance score.
    assert s["impact_score"] < _score("api_change")["impact_score"]


def test_large_refactor_does_not_beat_targeted_fix_on_significance():
    refactor = _score("large_routine_refactor")
    fix = _score("critical_race_fix")
    assert fix["dimensions"]["problem_significance"] > refactor["dimensions"]["problem_significance"]
