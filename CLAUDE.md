# CLAUDE.md

procure-agent: a manufacturing-ops AI agent for SMB procurement workflows. Quote reconciliation is the reference workflow shipping first; supplier onboarding, product master, and BOM creation share the same architecture.

The canonical planning artifact is `procure-agent-handoff.md` at the repo root. The running build log is `docs/build_log.md`. Re-read before reconstructing from memory.

## Stack

**Backend (`api` service)**
- Python 3.12, managed by uv
- LangGraph (Anthropic SDK underneath); Claude Sonnet 4.6 planner, Haiku 4.5 extraction
- Postgres (`procure_agent` schema for domain rows; `public` for LangGraph checkpoints): local docker for dev (`docker-compose.yml`), Railway-Postgres for deploy. Hand-rolled SQL migrations under `migrations/`; products are DB-as-master, seeded from `data/inventory/inventory.csv` via `scripts/generate_seed_sql.py`.
- LangGraph Postgres checkpointer
- FastAPI for the HITL endpoints (`/runs`, `/runs/{id}`, `/runs/{id}/resume`, `/fixtures`, `/health`)
- LangSmith tracing
- pytest + ruff; CI on push/PR to main (postgres service container so DB tests run)

**Frontend (`web` service)**
- Next.js 16 (App Router, server components by default), TypeScript strict
- Tailwind v4, shadcn/ui (base-ui-backed), Zod 4 as the FE single source of truth
- Biome (lint + format), pnpm
- Server actions for mutations; browser never speaks directly to FastAPI (Next.js proxies `/api/*` to the api service via `API_INTERNAL_URL`)

**Deploy**
- Two Railway services from this repo: `api` (root `/`) and `web` (root `/web`). Each has its own Dockerfile + `railway.toml`. Public URL is the web service; CORS is moot in prod (same-origin).

## Commands

Backend:
```
uv sync --all-groups               # install deps including dev
uv run ruff check .                # lint
uv run pytest                      # tests + evals (requires postgres for DB tests)
docker compose up -d               # local postgres
uv run uvicorn procure_agent.api:app --port 8000   # run api locally
uv run python scripts/migrate.py             # apply pending domain migrations
uv run python scripts/setup_checkpointer.py  # create LangGraph checkpoint tables (idempotent, public schema)
uv run python scripts/bootstrap_prod_db.py   # one-shot: migrate + setup_checkpointer (use on first deploy)
uv run python scripts/generate_seed_sql.py   # regenerate 0002_seed_products.sql from CSV
```

Frontend (run from `web/`):
```
pnpm install
pnpm dev              # Next.js dev on :3000, proxies /api/* to API_INTERNAL_URL
pnpm build            # standalone production build (.next/standalone)
pnpm lint             # biome check
pnpm typecheck        # tsc --noEmit
```

## Layout

```
src/procure_agent/      package code (FastAPI app, LangGraph, schemas, prompts)
data/synthetic_quotes/  hand-crafted supplier quote fixtures (eval corpus)
data/prompt_examples/   held-out demo fixture for the system-prompt few-shot
data/inventory/         reference inventory CSVs
migrations/             hand-rolled SQL migrations (lexically ordered)
scripts/                migration runner + seed generator + bootstrap_prod_db
evals/                  pytest-driven eval harness + golden set
tests/                  unit tests
docs/                   build_log.md and concept-mapping notes
web/                    Next.js frontend (separate Railway service)
Dockerfile              api service build
web/Dockerfile          web service build (multi-stage, Next.js standalone)
railway.toml            api service deploy config
web/railway.toml        web service deploy config
```

## Working agreements

- The user writes the core agent loop logic — LangGraph node bodies, prompts, state transitions. Claude Code scaffolds structure but does not author the loop.
- Claude Code handles surrounding infrastructure freely — pyproject changes, FastAPI / Next.js boilerplate, Railway config, migrations, CI. No need to ask.
- README content is collaborative. Claude Code drafts, user revises.
- Append to `docs/build_log.md` after every session — what worked, what broke, failure-mode observations.
- Push back on scope creep. Default response to mid-build feature additions: "noted, after we ship."
