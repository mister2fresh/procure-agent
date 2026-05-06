"""One-shot bootstrap for the deployed Postgres instance.

Runs domain SQL migrations and creates the LangGraph checkpoint tables in
``public``. Idempotent — re-running is safe and only applies what's missing.

Usage:
    DATABASE_URL=... uv run python scripts/bootstrap_prod_db.py

Run once after first Railway deploy, and again whenever a new SQL migration
or a langgraph-checkpoint-postgres dependency bump lands.
"""

from __future__ import annotations

import sys

import migrate
import setup_checkpointer


def main() -> int:
    """Apply migrations then PostgresSaver.setup(). Returns first non-zero exit, else 0."""
    rc = migrate.main()
    if rc != 0:
        return rc
    return setup_checkpointer.main()


if __name__ == "__main__":
    sys.exit(main())
