# ContribIQ

Engineering intelligence for developers — turns your GitHub history into a
verifiable profile of real engineering work: PR-centric contribution analysis,
collaboration evidence, an evidence-backed skill graph, resume bullets, STAR
interview answers, and a shareable recruiter dossier.

## What it measures

ContribIQ answers *"what engineering work has this developer demonstrably
contributed to?"* — not "how active are they on GitHub?"

- **PR-centric evidence** — authored PRs, merge outcomes, review cycles,
  approvals and change requests, own-repo vs independently maintained codebases
- **Comprehensive ingestion** — paginated GitHub REST + search-based discovery
  across every repo you touched, not just your top 30
- **Deterministic scoring** — impact scores and dimension subscores
  (substance / collaboration / acceptance / context / problem complexity) are
  pure functions of GitHub facts; the LLM only classifies and explains
- **Evidence-backed AI** — every resume bullet and STAR answer must link to the
  PRs that prove it; claims without evidence are dropped

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

`POST /api/analysis/start` runs a background job: **fetch → classify → skills →
insights**, with progress at `GET /api/analysis/status`. Re-runs are incremental
(dedupe-keyed), so only new GitHub activity is processed.

## Testing

```bash
cd backend && pytest          # backend lane (pytest-xdist, asyncio auto)
cd frontend && yarn typecheck # tsc -b (project references — plain tsc checks nothing)
cd frontend && yarn lint      # oxlint
```
