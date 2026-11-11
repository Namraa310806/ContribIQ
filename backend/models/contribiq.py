"""Pydantic v2 models for ContribIQ.

Every response the API returns is declared here; the hand-written TS mirrors live in
frontend/src/types.ts — update both in the same edit (nothing infers across the boundary).
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    # Aware UTC everywhere: naive datetimes break comparisons on read.
    return datetime.now(timezone.utc)


# ---------- auth ----------

class User(BaseModel):
    id: str = Field(default_factory=_uuid)
    is_demo: bool = False
    github_id: Optional[str] = None
    login: str
    name: str = ""
    email: Optional[str] = None
    avatar_url: str = ""
    profile_url: str = ""
    # GitHub OAuth token — server-side only, never serialized into a response.
    github_token: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    excluded_repos: List[str] = Field(default_factory=list)  # owner/name, skipped by future fetches
    auto_sync: bool = False  # weekly re-analysis, opt-in
    created_at: datetime = Field(default_factory=_now)


class UserPublic(BaseModel):
    id: str
    is_demo: bool = False
    login: str
    name: str
    avatar_url: str
    profile_url: str
    has_github_token: bool = False
    last_synced_at: Optional[datetime] = None
    excluded_repos: List[str] = Field(default_factory=list)
    auto_sync: bool = False


class MeResponse(BaseModel):
    user: Optional[UserPublic] = None


class AuthUrlResponse(BaseModel):
    configured: bool
    url: str = ""


# ---------- contributions ----------

class Contribution(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    kind: str = "pr"  # pr | issue | commit | review
    repo: str  # owner/name
    repo_owner: str = ""
    is_own_repo: bool = False  # repo owned by the user vs independently maintained
    title: str
    summary: str = ""
    dedupe_key: str = Field(default_factory=_uuid)
    number: Optional[int] = None
    url: str = ""
    state: str = ""  # merged | open | closed | committed
    labels: List[str] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    comments: int = 0
    # PR-centric evidence fields (empty/zero for non-PR kinds)
    merged: bool = False
    draft: bool = False
    author_association: str = ""
    changed_files: int = 0
    commits_count: int = 0
    review_count: int = 0
    approvals: int = 0
    change_requests: int = 0
    reviewers: int = 0
    pr_author: str = ""  # for kind=review: who authored the reviewed PR
    category: str = "Other"
    complexity: str = "Medium"  # Low | Medium | High
    impact_score: int = 0
    dimensions: Dict[str, int] = Field(default_factory=dict)  # substance/collaboration/acceptance/context/problem_complexity
    technologies: List[str] = Field(default_factory=list)
    analyzed: bool = False
    occurred_at: datetime = Field(default_factory=_now)
    analyzed_at: Optional[datetime] = None


class ContributionPage(BaseModel):
    items: List[Contribution]
    total: int
    facets: Dict[str, List[str]] = Field(default_factory=dict)  # kinds / categories / repos


# ---------- skills ----------

class Skill(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    name: str
    confidence: str = "Low"  # High | Medium | Low
    score: int = 0  # 0-100
    evidence_count: int = 0
    repo_count: int = 0
    last_used_at: Optional[datetime] = None


class SkillsResponse(BaseModel):
    items: List[Skill]


# ---------- insights ----------

class EvidenceLink(BaseModel):
    contribution_id: str
    label: str
    url: str = ""


class Insight(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    kind: str  # bullet | star | recruiter_summary
    title: str
    content: str = ""
    situation: Optional[str] = None
    task: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None
    evidence: List[EvidenceLink] = Field(default_factory=list)
    pinned: bool = False
    created_at: datetime = Field(default_factory=_now)


class InsightsResponse(BaseModel):
    items: List[Insight]


class PinRequest(BaseModel):
    pinned: bool


# ---------- analysis jobs ----------

class AnalysisJob(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    mode: str = "full"  # full | insights
    status: str = "queued"  # queued | running | completed | failed
    stage: str = "queued"  # queued | fetch | classify | skills | insights | done
    stage_label: str = "Queued"
    progress: int = 0
    error: Optional[str] = None
    stats: Dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


class StartAnalysisResponse(BaseModel):
    job: AnalysisJob


class AnalysisStatusResponse(BaseModel):
    job: Optional[AnalysisJob] = None


# ---------- overview ----------

class OverviewStats(BaseModel):
    total_contributions: int = 0
    authored_prs: int = 0
    merged_prs: int = 0
    external_prs: int = 0
    prs_reviewed: int = 0  # reviews the user wrote on others' PRs
    top_skill: str = ""
    avg_impact: int = 0
    collaboration_score: int = 0  # mean collaboration dimension over PR+review evidence
    consistency_score: int = 0  # sustained activity across time and repos
    categories_used: int = 0
    evidence_count: int = 0  # merged/landed PRs + substantive reviews
    repos_count: int = 0
    last_analyzed_at: Optional[datetime] = None
    has_data: bool = False


# ---------- recruiter share ----------

class ShareInfo(BaseModel):
    token: str
    path: str
    expires_at: datetime
    revoked: bool = False


class ShareStateResponse(BaseModel):
    share: Optional[ShareInfo] = None


class CreateShareRequest(BaseModel):
    days: int = Field(default=30)  # 7 | 30 | 90


class RecruiterSkill(BaseModel):
    name: str
    confidence: str
    score: int
    evidence_count: int


class RecruiterHighlight(BaseModel):
    contribution_id: str
    kind: str
    title: str
    repo: str
    summary: str
    category: str
    impact_score: int
    url: str


class PublicRecruiterView(BaseModel):
    name: str
    login: str
    avatar_url: str
    profile_url: str
    is_demo: bool = False
    summary: str = ""
    skills: List[RecruiterSkill] = Field(default_factory=list)
    highlights: List[RecruiterHighlight] = Field(default_factory=list)
    stats: Dict[str, int] = Field(default_factory=dict)
    expires_at: datetime


class DeleteDataResponse(BaseModel):
    user_id: str
    deleted: Dict[str, int]


# ---------- repo picker ----------

class RepoOption(BaseModel):
    full_name: str
    included: bool = True
    language: str = ""
    contribution_count: int = 0  # already-analyzed items from this repo


class ReposResponse(BaseModel):
    items: List[RepoOption]
    live: bool = False  # True when the list came from GitHub, False when from stored data


class UpdateExcludedRequest(BaseModel):
    excluded: List[str] = Field(default_factory=list, max_length=200)


# ---------- auto-sync ----------

class AutoSyncRequest(BaseModel):
    enabled: bool


# ---------- job-tailored insights ----------

class TailoredSet(BaseModel):
    id: str = Field(default_factory=_uuid)
    user_id: str
    title: str
    job_description: str
    match_summary: str = ""
    bullets: List[Insight] = Field(default_factory=list)
    stars: List[Insight] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


class CreateTailoredRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    job_description: str = Field(min_length=40, max_length=8000)


class TailoredListResponse(BaseModel):
    items: List[TailoredSet]
