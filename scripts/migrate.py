"""Apply pending SQL migrations from migrations/ in lexical order.

Bootstraps the procure_agent schema and a schema_migrations tracking table on
first run, then applies every *.sql file whose stem (the version) is not yet
recorded. Idempotent — re-running with no new migrations is a no-op.

Usage:
    uv run python scripts/migrate.py

Reads DATABASE_URL from the environment (loads .env if present).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"


def main() -> int:
    """Apply pending migrations. Returns 0 on success, 1 on configuration error."""
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("no migrations found")
        return 0

    with psycopg.connect(url) as conn:
        _bootstrap_tracking(conn)
        applied = _read_applied(conn)
        pending = [f for f in files if f.stem not in applied]
        if not pending:
            print(f"up to date ({len(applied)} migrations applied)")
            return 0
        for path in pending:
            print(f"applying {path.stem}...")
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO procure_agent.schema_migrations (version) VALUES (%s)",
                    (path.stem,),
                )
        print(f"applied {len(pending)} migration(s)")
    return 0


def _bootstrap_tracking(conn: psycopg.Connection) -> None:
    """Ensure procure_agent schema and schema_migrations table exist."""
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS procure_agent")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS procure_agent.schema_migrations (
                version    text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )


def _read_applied(conn: psycopg.Connection) -> set[str]:
    """Return the set of versions already recorded in schema_migrations."""
    rows = conn.execute("SELECT version FROM procure_agent.schema_migrations").fetchall()
    return {r[0] for r in rows}


if __name__ == "__main__":
    sys.exit(main())
