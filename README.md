# ContribIQ

Engineering intelligence for developers — turns your GitHub history into a
verifiable profile of real engineering work: PR-centric contribution analysis,
collaboration evidence, an evidence-backed skill graph, resume bullets, STAR
interview answers, and a shareable recruiter dossier.

## What it measures

ContribIQ answers *"what engineering work has this developer demonstrably
contributed to?"* — not "how active are they on GitHub?"

- **PR-centric evidence** — the pull request is the primary unit of engineering
  contribution. Each authored PR gets a detail fetch plus changed files
  (with patches), reviews, review/conversation comments, per-commit CI checks,
  and linked issues — persisted as queryable evidence, not just counts
- **Search-driven discovery** — authored PRs, authored issues, reviews written,
  and commits are discovered via the GitHub Search API with recursive
  `created:`/`author-date:` window partitioning that works around the
  1,000-result-per-query ceiling; per-window coverage is stored and reported,
  so partial history is never claimed as complete
- **Repository eligibility engine** — every PR's *base* repo gets an auditable
  ownership verdict (`ELIGIBLE_EXTERNAL`, `EXCLUDED_SELF_OWNED`,
  `EXCLUDED_CONTROLLED_ORGANIZATION`, `REVIEW_REQUIRED`, `UNKNOWN`) resolved
  through owner type, org membership **role** (admin = controlled, member =
  independent), fork upstream, and API permissions. A PR from a personal fork
  to an upstream project is judged on the upstream — that is where the
  collaboration happened. Own/controlled-org repos keep their technical evidence
  (personal portfolio) but earn zero open-source collaboration credit
- **Snapshot-safe evidence** — PR child collections (files, reviews, comments,
  commits, checks, timeline) are only replaced when their fetch succeeds;
  failed fetches preserve the previous snapshot, per-collection status and a
  snapshot version are stored on the PR document
- **Integration outcomes** — PR timelines provide revert and superseded
  evidence; reverted PRs lose acceptance credit but keep technical merit
- **Deterministic scoring** — six independent dimensions (technical substance,
  code quality, testing & validation, problem significance, review
  collaboration, acceptance & integration) plus repository context and an
  evidence-confidence rating. Merged ≠ excellent, closed ≠ worthless, and raw
  line/comment/reviewer counts are log-dampened signals, never quality proxies
- **Evidence-backed AI** — the classifier receives file-category, CI, merge
  and eligibility context; every resume bullet and STAR answer must link to the
  PRs that prove it; claims without evidence are dropped
- **Honest coverage** — `GET /api/coverage` reports search windows completed,
  eligibility verdicts, and per-PR evidence completeness

## Stack

- `backend/` — FastAPI + Motor (async MongoDB) + Pydantic v2, Python 3.13
- `frontend/` — Vite + React 19 + TypeScript strict, Tailwind v4, shadcn/ui
- `tests/` — Playwright e2e workspace

## Running locally

```bash
# terminal 1 — backend (port 8001)
cd backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# terminal 2 — frontend (port 3000, proxies /api → 8001)
cd frontend && yarn dev
```

MongoDB must be running locally (`mongodb://localhost:27017` by default).

## Configuration (`backend/.env` — copy from `.env.example`)

| Var | Purpose |
| --- | --- |
| `MONGO_URL`, `DB_NAME` | Mongo connection |
| `APP_URL` | Frontend origin — used to build the OAuth callback URL |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | GitHub OAuth App (callback: `{APP_URL}/api/auth/github/callback`) |
| `LLM_API_KEY` | Any OpenAI-compatible key (OpenAI, OpenRouter, DeepSeek, local vLLM…) |
| `LLM_BASE_URL`, `LLM_MODEL` | Optional endpoint/model overrides |
| `WEBHOOK_CRON_SECRET` | Bearer secret for the weekly-sync webhook |

Without `LLM_API_KEY` the pipeline falls back to keyword heuristics; without
GitHub OAuth credentials the demo profile (`POST /api/auth/demo`) still works.

## Pipeline

`POST /api/analysis/start` runs a background job: **discover → PR evidence →
classify → rescore → skills → insights**, with progress at
`GET /api/analysis/status`.

- Discovery uses partitioned GitHub Search (`author:`, `reviewed-by:`,
  `is:issue author:`, commit `author:`), so history beyond the 1,000-result
  search ceiling is reached by bisecting date windows. Windows that cannot be
  fully fetched are recorded as partial in `sync_coverage`.
- Each authored PR is fetched once, then refreshed only when its `updated_at`
  changes; evidence children are replaced per-collection only on successful
  fetches (failed fetches preserve prior snapshots). PR timelines supply
  revert/superseded outcome evidence.
- Bisection never splits below a 14-day window — denser-than-resolvable history
  is marked `partial` in `sync_coverage`, never claimed complete.
- Contributions are upserted by dedupe key, so merge state and scores stay
  current; re-runs rescore existing rows without another LLM pass.
- API reads: `GET /api/prs?repo=owner/name&number=N` (full PR evidence),
  `GET /api/prs/eligibility` (ownership verdicts), `GET /api/coverage`
  (sync coverage report).

## Testing

```bash
cd backend && pytest          # backend lane (pytest-xdist, asyncio auto)
cd frontend && yarn typecheck # tsc -b (project references — plain tsc checks nothing)
cd frontend && yarn lint      # oxlint
```
