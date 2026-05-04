# CLAUDE.md

procure-agent: a manufacturing-ops AI agent for SMB procurement workflows. Quote reconciliation is the reference workflow shipping first; supplier onboarding, product master, and BOM creation share the same architecture.

The canonical planning artifact is `procure-agent-handoff.md` at the repo root. The running build log is `docs/build_log.md`. Re-read before reconstructing from memory.

## Stack

- Python 3.12, managed by uv
- LangGraph (Anthropic SDK underneath); Claude Sonnet 4.6 planner, Haiku 4.5 extraction
- Postgres (`procure_agent` schema): local docker for dev (`docker-compose.yml`), Supabase for deploy. Hand-rolled SQL migrations under `migrations/`; products are DB-as-master, seeded from `data/inventory/inventory.csv` via `scripts/generate_seed_sql.py`.
- LangGraph Postgres checkpointer (deferred — `MemorySaver` until match/flag bodies + HITL endpoint land)
- FastAPI for the HITL approval endpoint, Streamlit for the demo UI
- LangSmith tracing
- pytest + ruff; CI on push/PR to main (postgres service container so DB tests run)

## Commands

```
uv sync --all-groups               # install deps including dev
uv run ruff check .                # lint
uv run pytest                      # tests + evals (requires postgres for DB tests)
docker compose up -d               # local postgres
uv run python scripts/migrate.py   # apply pending migrations
uv run python scripts/generate_seed_sql.py   # regenerate 0002_seed_products.sql from CSV
```

## Layout

```
src/procure_agent/      package code
data/synthetic_quotes/  hand-crafted supplier quote fixtures (eval corpus)
data/prompt_examples/   held-out demo fixture for the system-prompt few-shot
data/inventory/         reference inventory CSVs
migrations/             hand-rolled SQL migrations (lexically ordered)
scripts/                migration runner + seed generator
evals/                  pytest-driven eval harness + golden set
tests/                  unit tests
docs/                   build_log.md and concept-mapping notes
```

## Working agreements

- The user writes the core agent loop logic — LangGraph node bodies, prompts, state transitions. Claude Code scaffolds structure but does not author the loop.
- Claude Code handles surrounding infrastructure freely — pyproject changes, FastAPI / Streamlit boilerplate, Railway config, migrations, CI. No need to ask.
- README content is collaborative. Claude Code drafts, user revises.
- Append to `docs/build_log.md` after every session — what worked, what broke, failure-mode observations.
- Push back on scope creep. Default response to mid-build feature additions: "noted, after we ship."
