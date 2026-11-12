"""Manually labelled PR evaluation cases for scoring calibration.

Each case is a realistic PR evidence profile with a human-assigned expectation.
These are *illustrative fixtures*, not claims of statistical validation — see
backend/CALIBRATION.md for methodology and limitations.

Expectation tuples: (min_technical_substance, max_technical_substance,
min_testing, expected_confidence_floor) — used by test_calibration.py to check
that the deterministic scorer ranks representative work sensibly.
"""


def _base(**over):
    b = {
        "kind": "pr", "state": "open", "merged": False, "draft": False,
        "is_own_repo": False, "eligibility_status": "ELIGIBLE_EXTERNAL",
        "additions": 50, "deletions": 10, "changed_files": 3, "commits_count": 2,
        "review_count": 1, "approvals": 0, "change_requests": 0, "reviewers": 1,
        "comments": 2, "complexity": "Medium", "files_total": 3,
        "file_categories": {"source": {"files": 3, "additions": 50, "deletions": 10}},
        "patch_ratio": 0.8, "ci_status": "unknown", "linked_issue_count": 0,
        "evidence_status": "complete",
    }
    b.update(over)
    return b


CASES = {
    # --- small critical bug fix: tiny diff, huge significance ---
    "critical_race_fix": _base(
        title="Fix race condition in payment webhook handler",
        additions=34, deletions=8, changed_files=2, commits_count=1,
        complexity="High", files_total=2,
        file_categories={
            "source": {"files": 1, "additions": 28, "deletions": 6},
            "test": {"files": 1, "additions": 6, "deletions": 2, "added": 1},
        },
        test_files_added=1, linked_issue_count=1,
        state="merged", merged=True, ci_status="success",
        review_count=3, approvals=2, change_requests=1, reviewers=2, comments=6,
    ),
    # --- large routine refactor: big diff, routine substance ---
    "large_routine_refactor": _base(
        title="Rename internal helpers for consistency",
        additions=1400, deletions=900, changed_files=45, commits_count=12,
        complexity="Medium", files_total=45,
        file_categories={
            "source": {"files": 40, "additions": 1200, "deletions": 800},
            "test": {"files": 5, "additions": 200, "deletions": 100, "modified": 5},
        },
        test_files_modified=5, patch_ratio=0.4, ci_status="success",
        state="merged", merged=True, review_count=2, approvals=1, reviewers=1,
    ),
    # --- security fix ---
    "security_fix": _base(
        title="Patch SQL injection in search endpoint",
        additions=60, deletions=15, changed_files=3, commits_count=2,
        complexity="High", files_total=3,
        file_categories={
            "source": {"files": 2, "additions": 45, "deletions": 10},
            "test": {"files": 1, "additions": 15, "deletions": 5, "added": 1},
        },
        test_files_added=1, labels=["security"], linked_issue_count=1,
        state="merged", merged=True, ci_status="success",
        review_count=4, approvals=2, change_requests=1, reviewers=2,
    ),
    # --- concurrency fix ---
    "concurrency_fix": _base(
        title="Fix deadlock between cache eviction and writer",
        additions=85, deletions=22, changed_files=4, commits_count=3,
        complexity="High", files_total=4,
        file_categories={
            "source": {"files": 3, "additions": 70, "deletions": 18},
            "test": {"files": 1, "additions": 15, "deletions": 4, "added": 1},
        },
        test_files_added=1, linked_issue_count=1,
        state="closed",  # well-reviewed but maintainer chose another approach
        review_count=5, approvals=1, change_requests=2, reviewers=2, comments=10,
    ),
    # --- documentation only ---
    "docs_only": _base(
        title="Update API reference for v2 endpoints",
        additions=800, deletions=200, changed_files=12, commits_count=4,
        complexity="Low", files_total=12,
        file_categories={"docs": {"files": 12, "additions": 800, "deletions": 200}},
        state="merged", merged=True, ci_status="none",
        review_count=1, approvals=1, reviewers=1,
    ),
    # --- test only ---
    "test_only": _base(
        title="Add regression coverage for auth token refresh",
        additions=250, deletions=10, changed_files=5, commits_count=2,
        complexity="Medium", files_total=5,
        file_categories={"test": {"files": 5, "additions": 250, "deletions": 10, "added": 4}},
        test_files_added=4, ci_status="success",
        state="merged", merged=True, review_count=2, approvals=1, reviewers=1,
    ),
    # --- performance improvement ---
    "perf_improvement": _base(
        title="Reduce p99 latency in feed aggregation by 40%",
        additions=180, deletions=60, changed_files=6, commits_count=3,
        complexity="High", files_total=6,
        file_categories={
            "source": {"files": 4, "additions": 140, "deletions": 45},
            "test": {"files": 2, "additions": 40, "deletions": 15, "added": 1, "modified": 1},
        },
        test_files_added=1, test_files_modified=1, linked_issue_count=1,
        state="merged", merged=True, ci_status="success",
        labels=["performance"], review_count=3, approvals=2, reviewers=2,
    ),
    # --- API change ---
    "api_change": _base(
        title="Add cursor pagination to /repos endpoint",
        additions=220, deletions=40, changed_files=7, commits_count=4,
        complexity="High", files_total=7,
        file_categories={
            "source": {"files": 4, "additions": 170, "deletions": 30},
            "test": {"files": 2, "additions": 45, "deletions": 8, "added": 1, "modified": 1},
            "docs": {"files": 1, "additions": 5, "deletions": 2},
        },
        test_files_added=1, test_files_modified=1, linked_issue_count=1,
        state="merged", merged=True, ci_status="success",
        review_count=6, approvals=2, change_requests=2, reviewers=3, comments=14,
    ),
    # --- reverted PR: landed then reverted ---
    "reverted_pr": _base(
        title="Migrate session store to Redis cluster",
        additions=500, deletions=200, changed_files=15, commits_count=8,
        complexity="High", files_total=15,
        file_categories={
            "source": {"files": 11, "additions": 420, "deletions": 170},
            "config": {"files": 2, "additions": 40, "deletions": 10},
            "test": {"files": 2, "additions": 40, "deletions": 20, "modified": 2},
        },
        test_files_modified=2, ci_status="success",
        state="merged", merged=True, reverted=True,
        review_count=5, approvals=3, change_requests=1, reviewers=3,
    ),
    # --- substantial review, unmerged ---
    "heavy_review_unmerged": _base(
        title="Replace polling loop with event-driven worker",
        additions=650, deletions=300, changed_files=18, commits_count=7,
        complexity="High", files_total=18,
        file_categories={
            "source": {"files": 13, "additions": 520, "deletions": 240},
            "test": {"files": 5, "additions": 130, "deletions": 60, "added": 3, "modified": 2},
        },
        test_files_added=3, test_files_modified=2, linked_issue_count=2,
        state="closed",
        review_count=9, approvals=0, change_requests=4, reviewers=3, comments=25,
        author_replied=True,
    ),
    # --- minimal review merged ---
    "minimal_review_merged": _base(
        title="Fix typo in error message",
        additions=3, deletions=1, changed_files=1, commits_count=1,
        complexity="Low", files_total=1,
        file_categories={"source": {"files": 1, "additions": 3, "deletions": 1}},
        state="merged", merged=True, ci_status="success",
        review_count=0, approvals=0, reviewers=0, comments=0,
    ),
    # --- own repo PR: excluded from OSS credit ---
    "own_repo_feature": _base(
        is_own_repo=True, eligibility_status="EXCLUDED_SELF_OWNED",
        title="Add dark mode toggle",
        additions=300, deletions=80, changed_files=10, commits_count=5,
        complexity="Medium", files_total=10,
        file_categories={
            "source": {"files": 7, "additions": 240, "deletions": 60},
            "test": {"files": 3, "additions": 60, "deletions": 20, "added": 2},
        },
        test_files_added=2, state="merged", merged=True, ci_status="success",
        review_count=0, approvals=0, reviewers=0,
    ),
}

# Human-labelled expectations used by the calibration test:
# (name, min_substance, substance_band_max, min_testing, confidence_floor)
EXPECTATIONS = {
    "critical_race_fix":        (40, 100, 30, "Medium"),
    "large_routine_refactor":   (45, 100, 20, "Medium"),
    "security_fix":             (40, 100, 30, "Medium"),
    "concurrency_fix":          (45, 100, 30, "Medium"),
    "docs_only":                (0, 50, 15, "Medium"),
    "test_only":                (30, 80, 50, "Medium"),
    "perf_improvement":         (45, 100, 30, "Medium"),
    "api_change":               (50, 100, 35, "High"),
    "reverted_pr":              (50, 100, 30, "Medium"),
    "heavy_review_unmerged":    (55, 100, 40, "High"),
    "minimal_review_merged":    (0, 55, 15, "Medium"),
    "own_repo_feature":         (40, 100, 30, "Medium"),
}
