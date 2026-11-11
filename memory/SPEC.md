# ContribIQ — App Spec

## What it does
Turns a developer's GitHub history into professional intelligence: AI-classified contributions,
an evidence-backed skill profile, resume bullets, STAR interview answers, and a public,
expiring recruiter dossier. Login is GitHub OAuth (or the one-click demo profile).

## Data model (MongoDB, `app` database — string uuid `id` everywhere, never ObjectId)
- `users` — login, name, avatar, `github_id` (unique when present), `github_token` (server-side only, never serialized), `is_demo`, `last_synced_at`
- `sessions` — `session_hash` (sha256 of the opaque cookie value), `user_id`, `expires_at` (TTL index); cookie `contribiq_session`, HttpOnly, SameSite=Lax
- `contributions` — kind (pr|issue|commit|review), repo, title, summary, category, complexity (Low|Medium|High), impact_score (0-100), technologies[], dedupe_key (unique per user)
- `skills` — name, confidence (High|Medium|Low), score 0-100, evidence_count, repo_count, last_used_at (recomputed per analysis run)
- `insights` — kind (bullet|star|recruiter_summary), content / S-T-A-R fields, evidence[] (contribution_id, label, url), pinned
- `jobs` — status (queued|running|completed|failed), stage (fetch|classify|skills|insights|done), progress 0-100, stats; runs as managed asyncio task (uvicorn single process); stale running jobs > 15 min are marked failed
- `share_tokens` — token (unique), expires_at, revoked; one active per user

## API (all under /api)
- `GET /auth/github-url` → {configured, url} (probe; sets short-lived oauth_state/oauth_verifier cookies)
- `GET /auth/github/callback` → real OAuth (PKCE + state), sets session, 303 → /dashboard
- `POST /auth/demo` → demo session (seeds demo profile if missing); `GET /auth/me`; `POST /auth/logout` (204)
- `POST /analysis/start` (full) / `POST /insights/regenerate` (insights-only mode); `GET /analysis/status`
- `GET /overview`, `GET /contributions?kind&category&q&limit`, `GET /skills`, `GET /insights`
- `POST /insights/{id}/pin` {pinned}; `DELETE /user/data` (purges all derived data, keeps account/session)
- `GET/POST/DELETE /share` (manage link, days 7|30|90); `GET /share/{token}` (public dossier; 404 revoked, 410 expired)
- `GET /repos` → {items:[{full_name, included, language, contribution_count}], live}; `PUT /repos/excluded` {excluded:[owner/name]} — exclusions only skip future GitHub fetches (already-analyzed work stays visible, per user choice)
- `PUT /settings/auto-sync` {enabled} → UserPublic (auto_sync + excluded_repos are on UserPublic / /auth/me)
- `GET /tailored`, `POST /tailored` {title 2-120, job_description 40-8000} (synchronous GPT, ~10-30s; keyword fallback), `DELETE /tailored/{id}` — collection `tailored_sets`, each job saved as its own set (match_summary + bullets[] + stars[] as Insight shapes with evidence)
- `POST /cron/weekly-sync` — platform cron webhook (Bearer WEBHOOK_CRON_SECRET, idempotent on X-Webhook-Id via `cron_runs`, acks 202 and works in background). `.emergent/crons.yml` fires it daily 06:00 UTC; it re-analyzes users with auto_sync=true + a GitHub token whose last_synced_at is null or 7+ days old, one at a time

## Recruiter PDF
"Download PDF" on /r/:token calls window.print(); `@media print` in index.css flips the dossier to dark ink on white (.print-root/.print-doc), keeps skill bar colors (.print-keep-bg), hides .no-print.

## Key flows
- Analysis pipeline (backend/services/pipeline.py): fetch (GitHub REST, rate-limit aware; offline mode re-uses stored data when no token) → batched LLM classification (~10/call, GPT via EMERGENT_LLM_KEY, heuristic fallback) → skill aggregation (evidence count + repo diversity + recency → confidence) → insight generation (LLM with template fallback; pinned insights survive regeneration).
- Frontend: TanStack Query everywhere; session cache owned by src/lib/session.ts (beginSession/endSession clear the cache). Dashboard polls /analysis/status every 2s while a job is active.

## Demo data (seeded, idempotent — lib/demo.py, run `python seed.py`)
- User "alexchen-dev" (is_demo): 20 contributions across acme-labs/{fastapi-distributed-cache, react-data-grid, infra-k8s-mesh, payments-engine}, 11 skills, 9 insights (summary + 5 bullets + 3 STARs; bullet 1-2 and STAR 1 pinned).
- Permanent demo dossier link: `/r/contribiq-demo-dossier` (expires ~10 years out).

## Credentials
No passwords anywhere. Two entry paths:
1. Demo profile: click "Explore the live demo profile" (POST /api/auth/demo) — no credentials.
2. Real users: GitHub OAuth — GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET are set (backend/.env); callback URL `https://doc-fullstack--0mddl0u9.preview.emergentagent.com/api/auth/github/callback`. A failed round-trip lands on `/?auth_error=github` and shows a toast.

## Known scope decisions (deliberate deviations from the source document)
- Background analysis = FastAPI asyncio task + Mongo progress (not Postgres/Celery/Redis).
- LLM = OpenAI GPT via Emergent managed key (single provider, no abstraction layer).
- Reviews by the user on others' PRs are fetched only for the 3 most recent repos (API-budget bound).
