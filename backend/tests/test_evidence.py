"""Evidence-layer tests: file categorisation, summaries, normalisers,
CI collapsing, author-reply detection, linked-issue extraction.

All pure — no API or Mongo needed.
"""

from datetime import datetime, timezone

from services import evidence as ev


def test_categorize_file():
    assert ev.categorize_file("src/app/main.py") == "source"
    assert ev.categorize_file("tests/test_api.py") == "test"
    assert ev.categorize_file("pkg/foo_test.go") == "test"
    assert ev.categorize_file("docs/guide.md") == "docs"
    assert ev.categorize_file("README.md") == "docs"
    assert ev.categorize_file("docker-compose.yml") == "config"
    assert ev.categorize_file(".github/workflows/ci.yml") == "config"
    assert ev.categorize_file("pyproject.toml") == "config"


def test_summarize_files_buckets_and_patch_ratio():
    files = [
        {"filename": "src/a.py", "additions": 50, "deletions": 10, "patch": "@@ -1 +1 @@"},
        {"filename": "tests/test_a.py", "additions": 30, "deletions": 0, "patch": "@@"},
        {"filename": "big.bin", "additions": 5, "deletions": 0},  # no patch
    ]
    s = ev.summarize_files(files)
    assert s["files_total"] == 3
    assert s["patch_available"] == 2
    assert s["patch_ratio"] == round(2 / 3, 3)
    assert s["categories"]["source"]["files"] == 2  # src/a.py + big.bin
    assert s["categories"]["test"]["files"] == 1
    assert s["categories"]["source"]["additions"] == 55


def test_normalize_pr_captures_merge_state_and_ids():
    detail = {
        "id": 12345,
        "node_id": "PR_abc",
        "number": 7,
        "title": "Fix race in worker",
        "body": "Closes #42",
        "state": "closed",
        "merged": True,
        "merged_at": "2024-05-01T10:00:00Z",
        "draft": False,
        "user": {"login": "dev"},
        "author_association": "FIRST_TIME_CONTRIBUTOR",
        "labels": [{"name": "bug"}],
        "additions": 120,
        "deletions": 30,
        "changed_files": 5,
        "commits": 3,
        "head": {"ref": "fix", "sha": "abc123"},
        "base": {"ref": "main"},
        "html_url": "https://github.com/o/r/pull/7",
        "created_at": "2024-04-30T00:00:00Z",
        "updated_at": "2024-05-01T10:00:00Z",
        "closed_at": "2024-05-01T10:00:00Z",
    }
    doc = ev.normalize_pr("o/r", detail, "u1")
    assert doc["pr_key"] == "o/r#7"
    assert doc["merged"] is True
    assert doc["state"] == "merged"
    assert doc["github_id"] == 12345
    assert doc["head_sha"] == "abc123"
    assert doc["user_id"] == "u1"
    assert doc["github_updated_at"] == "2024-05-01T10:00:00Z"


def test_normalize_file_marks_truncated_patch():
    long_patch = "x" * (ev.PATCH_MAX_CHARS + 100)
    doc = ev.normalize_file("u1", "o/r#1", {
        "filename": "src/big.py",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "patch": long_patch,
    })
    assert doc["patch_available"] is True
    assert doc["patch_truncated"] is True
    assert len(doc["patch"]) == ev.PATCH_MAX_CHARS
    assert doc["category"] == "source"


def test_normalize_file_missing_patch_recorded():
    doc = ev.normalize_file("u1", "o/r#1", {"filename": "assets/logo.png", "status": "added"})
    assert doc["patch_available"] is False
    assert doc["patch"] is None


def test_checks_summary_states():
    assert ev.checks_summary([]) == "none"
    assert ev.checks_summary([{"status": "in_progress", "conclusion": None}]) == "pending"
    assert ev.checks_summary([{"status": "completed", "conclusion": "success"}]) == "success"
    assert ev.checks_summary([
        {"status": "completed", "conclusion": "success"},
        {"status": "completed", "conclusion": "failure"},
    ]) == "failure"
    assert ev.checks_summary([{"status": "completed", "conclusion": None}]) == "unknown"


def test_normalize_checks_merges_runs_and_statuses():
    checks = ev.normalize_checks(
        "u1", "o/r#1", "sha",
        check_runs=[{"name": "ci/tests", "status": "completed", "conclusion": "success", "html_url": "u"}],
        combined={"statuses": [{"context": "lint", "state": "failure", "target_url": "v"}]},
    )
    assert len(checks) == 2
    names = {c["name"] for c in checks}
    assert names == {"ci/tests", "lint"}
    assert ev.checks_summary(checks) == "failure"


def test_author_replied_requires_review_then_author_comment():
    t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    reviews = [{"reviewer_login": "maint", "submitted_at": t1}]
    # author comment AFTER the review → replied
    assert ev.author_replied("dev", reviews, [], [{"user_login": "dev", "created_at": t2}]) is True
    # author comment BEFORE any review → not a reply
    assert ev.author_replied("dev", reviews, [], [{"user_login": "dev", "created_at": datetime(2023, 12, 1, tzinfo=timezone.utc)}]) is False
    # no external reviews → cannot establish reply
    assert ev.author_replied("dev", [], [{"user_login": "dev", "created_at": t2}], []) is False
    # reviewer's own comment doesn't count as author reply
    assert ev.author_replied("dev", reviews, [], [{"user_login": "maint", "created_at": t2}]) is False


def test_extract_issue_refs_only_closing_keywords():
    body = "This fixes #12 and also see #99 for context. Resolves o/other#5 too."
    refs = ev.extract_issue_refs(body, "o/r")
    assert 12 in refs
    assert 5 not in refs  # cross-repo ref excluded
    # bare #99 without closing keyword is not a linked issue
    assert 99 not in refs


def test_review_summary_counts_unique_reviewers():
    docs = [
        {"reviewer_login": "a", "state": "APPROVED"},
        {"reviewer_login": "a", "state": "COMMENTED"},
        {"reviewer_login": "b", "state": "CHANGES_REQUESTED"},
    ]
    s = ev.review_summary(docs)
    assert s["review_count"] == 3
    assert s["reviewers"] == 2  # events ≠ reviewers
    assert s["approvals"] == 1
    assert s["change_requests"] == 1


def test_evidence_status_grades_completeness():
    assert ev.evidence_status([], True) == "complete"
    assert ev.evidence_status(["files: boom"], True) == "partial"
    assert ev.evidence_status(["files: boom", "reviews: boom"], False) == "failed"
    assert ev.evidence_status([], False) == "complete"  # empty PR is legitimately complete


def test_normalize_pr_counts_discussion_comments():
    """GitHub's `comments` (conversation) + `review_comments` (inline) feed the
    contribution `comments` field — conversation alone undercounts PRs."""
    doc = ev.normalize_pr("o/r", {
        "number": 3,
        "title": "t",
        "comments": 4,
        "review_comments": 6,
    }, "u1")
    assert doc["comment_count"] == 10
