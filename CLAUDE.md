# CLAUDE.md

procure-agent: a manufacturing-ops AI agent for SMB procurement workflows. Quote reconciliation is the reference workflow shipping first; supplier onboarding, product master, and BOM creation share the same architecture.

The canonical planning artifact is `procure-agent-handoff.md` at the repo root. The running build log is `docs/build_log.md`. Re-read before reconstructing from memory.

## Stack

- Python 3.12, managed by uv
- LangGraph (Anthropic SDK underneath); Claude Sonnet 4.6 planner, Haiku 4.5 extraction
- Postgres via Supabase (schema-namespaced to `procure_agent`); LangGraph Postgres checkpointer
- FastAPI for the HITL approval endpoint, Streamlit for the demo UI
- LangSmith tracing
- pytest + ruff; CI on push/PR to main

## Commands

```
uv sync --all-groups       # install deps including dev
uv run ruff check .        # lint
uv run pytest              # tests + evals
```

## Layout

```
src/procure_agent/      package code
data/synthetic_quotes/  hand-crafted supplier quote fixtures (eval corpus)
data/prompt_examples/   held-out demo fixture for the system-prompt few-shot
data/inventory/         reference inventory CSVs
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
