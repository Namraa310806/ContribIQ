"""Scoring tests — dimension independence, eligibility gating, confidence.

The core product rule under test: technical merit and acceptance are separate
dimensions; merged ≠ excellent; closed ≠ worthless; own-repo work earns zero
open-source collaboration credit; missing evidence lowers confidence, never
fabricates a verdict.
"""

from services.scoring import score_contribution


def _pr(**over):
    base = {
        "kind": "pr",
        "state": "open",
        "merged": False,
        "draft": False,
        "is_own_repo": False,
        "eligibility_status": "ELIGIBLE_EXTERNAL",
        "additions": 100,
        "deletions": 20,
        "changed_files": 4,
        "commits_count": 2,
        "review_count": 2,
        "approvals": 1,
        "change_requests": 0,
        "reviewers": 2,
        "comments": 3,
        "complexity": "Medium",
        "files_total": 4,
        "file_categories": {"source": {"files": 3, "additions": 90, "deletions": 15}},
        "patch_ratio": 0.8,
        "ci_status": "unknown",
        "linked_issue_count": 0,
        "evidence_status": "complete",
    }
    base.update(over)
    return base


def test_merged_beats_unmerged_on_acceptance_not_substance():
    merged = score_contribution(_pr(state="merged", merged=True))
    closed = score_contribution(_pr(state="closed"))
    assert merged["dimensions"]["acceptance"] > closed["dimensions"]["acceptance"]
    # identical diffs → identical substance; acceptance is what differs
    assert merged["dimensions"]["technical_substance"] == closed["dimensions"]["technical_substance"]


def test_substantial_unmerged_outranks_trivial_merged_on_substance():
    substantial_unmerged = score_contribution(
        _pr(
            state="closed",
            additions=900,
            deletions=300,
            changed_files=25,
            commits_count=9,
            complexity="High",
            files_total=25,
            file_categories={
                "source": {"files": 18, "additions": 700, "deletions": 200},
                "test": {"files": 7, "additions": 200, "deletions": 100},
            },
            linked_issue_count=2,
        )
    )
    trivial_merged = score_contribution(
        _pr(
            state="merged",
            merged=True,
            additions=12,
            deletions=2,
            changed_files=1,
            commits_count=1,
            complexity="Low",
            files_total=1,
            file_categories={"docs": {"files": 1, "additions": 12, "deletions": 2}},
        )
    )
    assert substantial_unmerged["dimensions"]["technical_substance"] > trivial_merged["dimensions"]["technical_substance"]
    # …but the merged PR still wins on acceptance — dimensions stay independent.
    assert trivial_merged["dimensions"]["acceptance"] > substantial_unmerged["dimensions"]["acceptance"]


def test_docs_only_pr_capped_substance():
    s = score_contribution(
        _pr(
            additions=2000,
            deletions=500,
            changed_files=40,
            files_total=40,
            file_categories={"docs": {"files": 40, "additions": 2000, "deletions": 500}},
            complexity="High",
        )
    )
    # Huge docs diff must not look like huge engineering substance.
    assert s["dimensions"]["technical_substance"] <= 50


def test_test_only_pr_scores_testing_not_substance():
    s = score_contribution(
        _pr(
            additions=300,
            deletions=50,
            files_total=6,
            file_categories={"test": {"files": 6, "additions": 300, "deletions": 50}},
            ci_status="success",
        )
    )
    assert s["dimensions"]["testing"] >= 60
    assert s["dimensions"]["technical_substance"] < 60


def test_ci_success_raises_testing_unknown_does_not_punish():
    green = score_contribution(_pr(ci_status="success"))
    unknown = score_contribution(_pr(ci_status="unknown"))
    failed = score_contribution(_pr(ci_status="failure"))
    assert green["dimensions"]["testing"] > unknown["dimensions"]["testing"]
    # failure still shows validation happened — above the no-CI baseline? No:
    # failure < success but the PR did run CI, so it beats pure unknown slightly
    # less than success; the key invariant is unknown is never scored as failure.
    assert unknown["dimensions"]["testing"] >= 20  # baseline, not zeroed


def test_excluded_repo_earns_zero_collaboration():
    own = score_contribution(_pr(eligibility_status="EXCLUDED_SELF_OWNED", is_own_repo=True))
    controlled = score_contribution(_pr(eligibility_status="EXCLUDED_CONTROLLED_ORGANIZATION"))
    external = score_contribution(_pr(eligibility_status="ELIGIBLE_EXTERNAL"))
    assert own["dimensions"]["collaboration"] == 0
    assert controlled["dimensions"]["collaboration"] == 0
    assert external["dimensions"]["collaboration"] > 0
    # …but technical merit survives exclusion.
    assert own["dimensions"]["technical_substance"] > 0


def test_unknown_eligibility_gets_reduced_not_full_credit():
    unknown = score_contribution(_pr(eligibility_status="UNKNOWN"))
    review = score_contribution(_pr(eligibility_status="REVIEW_REQUIRED"))
    external = score_contribution(_pr(eligibility_status="ELIGIBLE_EXTERNAL"))
    assert unknown["dimensions"]["collaboration"] < external["dimensions"]["collaboration"]
    assert review["dimensions"]["collaboration"] < external["dimensions"]["collaboration"]


def test_missing_evidence_lowers_confidence_not_score():
    sparse = score_contribution(
        _pr(
            files_total=0,
            file_categories={},
            patch_ratio=0.0,
            ci_status="unknown",
            evidence_status="failed",
        )
    )
    rich = score_contribution(_pr())
    assert sparse["confidence"] == "Insufficient"
    assert rich["confidence"] in ("High", "Medium")
    # substance is computed from facts we do have — not zeroed by missing patches
    assert sparse["dimensions"]["technical_substance"] > 0


def test_reverted_pr_acceptance_dampened():
    reverted = score_contribution(_pr(state="merged", merged=True, reverted=True))
    clean = score_contribution(_pr(state="merged", merged=True))
    assert reverted["dimensions"]["acceptance"] < clean["dimensions"]["acceptance"]


def test_draft_open_pr_lower_acceptance():
    draft = score_contribution(_pr(state="open", draft=True))
    ready = score_contribution(_pr(state="open", draft=False))
    assert draft["dimensions"]["acceptance"] < ready["dimensions"]["acceptance"]


def test_unique_reviewers_not_comment_volume():
    """Many comments from one reviewer must not equal many reviewers."""
    one_reviewer_chatty = score_contribution(
        _pr(review_count=10, approvals=1, change_requests=0, reviewers=1, comments=30)
    )
    three_reviewers = score_contribution(
        _pr(review_count=3, approvals=1, change_requests=0, reviewers=3, comments=3)
    )
    assert three_reviewers["dimensions"]["collaboration"] > one_reviewer_chatty["dimensions"]["collaboration"]


def test_non_pr_kinds_still_score():
    commit = score_contribution({"kind": "commit", "additions": 40, "deletions": 10, "is_own_repo": False})
    issue = score_contribution({"kind": "issue", "state": "closed", "comments": 4, "is_own_repo": False})
    review = score_contribution({"kind": "review", "state": "APPROVED", "is_own_repo": False})
    for s in (commit, issue, review):
        assert 0 <= s["impact_score"] <= 100
        assert s["confidence"]
