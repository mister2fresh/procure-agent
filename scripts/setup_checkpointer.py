"""Create the LangGraph checkpoint tables (in the public schema).

PostgresSaver expects to own its tables in the connection's default
search_path; ``from_conn_string`` opens connections without our ``SET
search_path`` so the tables live in ``public`` rather than ``procure_agent``.
Domain rows and LangGraph internals are different concerns — keeping them
in separate schemas reflects that.

``PostgresSaver.setup()`` is idempotent: re-running with no schema changes is
a no-op. Run once after applying SQL migrations, and again whenever the
``langgraph-checkpoint-postgres`` dependency bumps its own migrations.

Usage:
    uv run python scripts/setup_checkpointer.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run PostgresSaver.setup() against DATABASE_URL. Returns 0 on success."""
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    with PostgresSaver.from_conn_string(url) as cp:
        cp.setup()
    print("checkpoint tables ready in public schema")
    return 0


if __name__ == "__main__":
    sys.exit(main())
