"""Repository eligibility tests — the ownership decision matrix (milestone 2).

Org *membership* is no longer disqualifying: admin = controlled org (excluded),
member = independent org (eligible at reduced confidence), unverifiable role =
REVIEW_REQUIRED. The assessed repo is always the PR's base repository.
"""

from services import eligibility as elig

LOGIN = "dev-user"
ORGS = {"dev-org", "work-org"}
ROLES = {"dev-org": "admin", "work-org": "member"}


def _repo(owner="someone", owner_type="User", is_fork=False, parent=None, repo_id=1):
    repo = {
        "id": repo_id,
        "full_name": f"{owner}/proj",
        "fork": is_fork,
        "owner": {"login": owner, "type": owner_type},
        "permissions": {"push": True, "pull": True},
    }
    if parent:
        repo["parent"] = {"full_name": parent}
    return repo


def _classify(repo, orgs=ORGS, roles=ROLES):
    return elig.classify_repo_ownership(repo, login=LOGIN, user_orgs=orgs, org_roles=roles)


# ---------- personal ----------

def test_own_personal_repo_excluded():
    d = _classify(_repo(owner=LOGIN))
    assert d["status"] == elig.EXCLUDED_SELF_OWNED
    assert d["confidence"] >= 0.9


def test_fork_of_own_repo_excluded():
    d = _classify(_repo(owner="dev-user-fork", is_fork=True, parent=f"{LOGIN}/upstream"))
    assert d["status"] == elig.EXCLUDED_SELF_OWNED
    assert "fork" in d["reason"]


# ---------- organizations ----------

def test_admin_org_repo_excluded_as_controlled():
    d = _classify(_repo(owner="dev-org", owner_type="Organization"))
    assert d["status"] == elig.EXCLUDED_CONTROLLED_ORGANIZATION
    assert d["org_role"] == "admin"


def test_member_org_repo_is_eligible():
    """Milestone-2 correction: membership in an independent org must not
    disqualify contributions."""
    d = _classify(_repo(owner="work-org", owner_type="Organization"))
    assert d["status"] == elig.ELIGIBLE_EXTERNAL
    assert d["org_role"] == "member"
    assert d["confidence"] == 0.75


def test_external_org_repo_eligible():
    d = _classify(_repo(owner="kubernetes", owner_type="Organization"))
    assert d["status"] == elig.ELIGIBLE_EXTERNAL
    assert d["org_role"] is None
    assert d["confidence"] >= 0.8


def test_member_org_role_unknown_is_review_required():
    """Member of an org but role unverifiable → no unverified credit, not excluded."""
    d = elig.classify_repo_ownership(
        _repo(owner="mystery-org", owner_type="Organization"),
        login=LOGIN, user_orgs={"mystery-org"}, org_roles={},
    )
    assert d["status"] == elig.REVIEW_REQUIRED


def test_member_set_without_roles_treated_as_member():
    """Legacy callers passing only a membership set get member-level credit."""
    d = elig.classify_repo_ownership(
        _repo(owner="legacy-org", owner_type="Organization"),
        login=LOGIN, user_orgs={"legacy-org"}, org_roles=None,
    )
    assert d["status"] == elig.ELIGIBLE_EXTERNAL
    assert d["org_role"] == "member"


# ---------- forks (base repo is the destination) ----------

def test_external_fork_eligible_with_reduced_confidence():
    d = _classify(_repo(owner="forker", is_fork=True, parent="upstream-org/project"))
    assert d["status"] == elig.ELIGIBLE_EXTERNAL
    assert d["is_fork"] is True
    assert d["upstream"] == "upstream-org/project"
    assert d["confidence"] < 0.85


def test_fork_of_member_org_upstream_still_eligible():
    """A fork targeting a member-org upstream is external collaboration —
    the fork owner is independent of the developer."""
    d = _classify(_repo(owner="forker", is_fork=True, parent="work-org/project"))
    assert d["status"] == elig.ELIGIBLE_EXTERNAL


def test_user_fork_targeting_upstream_is_external():
    """PR base repo = upstream project (not the fork): eligibility judged on
    the upstream, which is what the collaboration score should measure."""
    upstream = _repo(owner="upstream-org", owner_type="Organization")
    d = _classify(upstream)
    # upstream-org is not a member org → external
    assert d["status"] == elig.ELIGIBLE_EXTERNAL


# ---------- edge cases ----------

def test_inaccessible_repo_unknown():
    d = _classify(None)
    assert d["status"] == elig.UNKNOWN
    assert d["confidence"] == 0.0


def test_unrecognised_owner_type_review_required():
    d = _classify(_repo(owner="weird", owner_type="Bot"))
    assert d["status"] == elig.REVIEW_REQUIRED


def test_eligibility_record_persists_audit_fields():
    rec = elig.eligibility_record(
        "work-org/hello", _repo(owner="work-org", owner_type="Organization"),
        login=LOGIN, user_orgs=ORGS, user_id="u1", org_roles=ROLES,
    )
    assert rec["user_id"] == "u1"
    assert rec["status"] == elig.ELIGIBLE_EXTERNAL
    assert rec["org_role"] == "member"
    assert rec["verified_at"] is not None
