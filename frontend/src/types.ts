// Hand-written mirrors of the Pydantic models in backend/models/contribiq.py.
// Nothing infers across the Python↔TypeScript boundary — update both in the same edit.

export interface UserPublic {
  id: string;
  is_demo: boolean;
  login: string;
  name: string;
  avatar_url: string;
  profile_url: string;
  has_github_token: boolean;
  last_synced_at: string | null;
  excluded_repos: string[];
  auto_sync: boolean;
}

export interface MeResponse {
  user: UserPublic | null;
}

export interface AuthUrlResponse {
  configured: boolean;
  url: string;
}

export type ContributionKind = "pr" | "issue" | "commit" | "review";

export interface Contribution {
  id: string;
  user_id: string;
  kind: ContributionKind;
  repo: string;
  repo_owner: string;
  is_own_repo: boolean;
  title: string;
  summary: string;
  number: number | null;
  url: string;
  state: string;
  labels: string[];
  additions: number;
  deletions: number;
  comments: number;
  merged: boolean;
  draft: boolean;
  author_association: string;
  changed_files: number;
  commits_count: number;
  review_count: number;
  approvals: number;
  change_requests: number;
  reviewers: number;
  pr_author: string;
  category: string;
  complexity: "Low" | "Medium" | "High";
  impact_score: number;
  dimensions: Record<string, number>;
  technologies: string[];
  analyzed: boolean;
  occurred_at: string;
  analyzed_at: string | null;
}

export interface ContributionPage {
  items: Contribution[];
  total: number;
  facets: Record<string, string[]>;
}

export type SkillConfidence = "High" | "Medium" | "Low";

export interface Skill {
  id: string;
  user_id: string;
  name: string;
  confidence: SkillConfidence;
  score: number;
  evidence_count: number;
  repo_count: number;
  last_used_at: string | null;
}

export interface SkillsResponse {
  items: Skill[];
}

export interface EvidenceLink {
  contribution_id: string;
  label: string;
  url: string;
}

export type InsightKind = "bullet" | "star" | "recruiter_summary";

export interface Insight {
  id: string;
  user_id: string;
  kind: InsightKind;
  title: string;
  content: string;
  situation: string | null;
  task: string | null;
  action: string | null;
  result: string | null;
  evidence: EvidenceLink[];
  pinned: boolean;
  created_at: string;
}

export interface InsightsResponse {
  items: Insight[];
}

export type JobStatus = "queued" | "running" | "completed" | "failed";
export type JobStage = "queued" | "fetch" | "classify" | "skills" | "insights" | "done";

export interface AnalysisJob {
  id: string;
  user_id: string;
  mode: "full" | "insights";
  status: JobStatus;
  stage: JobStage;
  stage_label: string;
  progress: number;
  error: string | null;
  stats: Record<string, number>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface AnalysisStatusResponse {
  job: AnalysisJob | null;
}

export interface StartAnalysisResponse {
  job: AnalysisJob;
}

export interface OverviewStats {
  total_contributions: number;
  authored_prs: number;
  merged_prs: number;
  external_prs: number;
  prs_reviewed: number;
  top_skill: string;
  avg_impact: number;
  collaboration_score: number;
  consistency_score: number;
  categories_used: number;
  evidence_count: number;
  repos_count: number;
  last_analyzed_at: string | null;
  has_data: boolean;
}

export interface ShareInfo {
  token: string;
  path: string;
  expires_at: string;
  revoked: boolean;
}

export interface ShareStateResponse {
  share: ShareInfo | null;
}

export interface RecruiterSkill {
  name: string;
  confidence: string;
  score: number;
  evidence_count: number;
}

export interface RecruiterHighlight {
  contribution_id: string;
  kind: string;
  title: string;
  repo: string;
  summary: string;
  category: string;
  impact_score: number;
  url: string;
}

export interface PublicRecruiterView {
  name: string;
  login: string;
  avatar_url: string;
  profile_url: string;
  is_demo: boolean;
  summary: string;
  skills: RecruiterSkill[];
  highlights: RecruiterHighlight[];
  stats: Record<string, number>;
  expires_at: string;
}

export interface DeleteDataResponse {
  user_id: string;
  deleted: Record<string, number>;
}

export interface RepoOption {
  full_name: string;
  included: boolean;
  language: string;
  contribution_count: number;
}

export interface ReposResponse {
  items: RepoOption[];
  live: boolean;
}

export interface TailoredSet {
  id: string;
  user_id: string;
  title: string;
  job_description: string;
  match_summary: string;
  bullets: Insight[];
  stars: Insight[];
  created_at: string;
}

export interface TailoredListResponse {
  items: TailoredSet[];
}
