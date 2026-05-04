"""Smoke tests for the migration runner.

Drops procure_agent (clean slate), invokes ``scripts/migrate.py`` end-to-end,
and asserts the resulting DB state matches the CSV the seed migration was
generated from. Requires postgres reachable at ``DATABASE_URL`` — in CI that's
the postgres service container; locally that's ``docker compose up`` plus the
local ``.env``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

from procure_agent.inventory import load_products

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fresh_db_url() -> str:
    """Drop and rebuild the procure_agent schema; return the DATABASE_URL.

    Skips the module if DATABASE_URL is unset or the server is unreachable —
    keeps non-DB test runs (CI without the postgres service, or a local
    contributor without docker up) from looking like a migration regression.

    Returns:
        The connection URL the migration runner used.
    """
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")

    try:
        with psycopg.connect(url) as conn:
            conn.execute("DROP SCHEMA IF EXISTS procure_agent CASCADE")
    except psycopg.OperationalError as exc:
        pytest.skip(f"DATABASE_URL unreachable: {exc}")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "migrate.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"migrate.py failed: {result.stderr}"
    return url


def test_schema_migrations_records_both_versions(fresh_db_url: str) -> None:
    """The runner records every applied version, in order, exactly once."""
    with psycopg.connect(fresh_db_url) as conn:
        rows = conn.execute(
            "SELECT version FROM procure_agent.schema_migrations ORDER BY version"
        ).fetchall()
    assert [r[0] for r in rows] == ["0001_init", "0002_seed_products"]


def test_products_row_count_matches_csv(fresh_db_url: str) -> None:
    """The seed migration loaded every CSV row into the products table."""
    with psycopg.connect(fresh_db_url) as conn:
        actual = conn.execute("SELECT COUNT(*) FROM procure_agent.products").fetchone()[0]
    assert actual == len(load_products())


def test_anchor_product_row_matches_csv(fresh_db_url: str) -> None:
    """An anchor row round-trips column-for-column from CSV through SQL.

    Cheap regression cover for type coercion (Decimal precision, date format,
    enum casting, currency null-vs-empty) at the seed-generator boundary.
    """
    expected = load_products()["AL101"]
    with psycopg.connect(fresh_db_url) as conn:
        row = conn.execute(
            """
            SELECT sku, description, category::text, uom::text, pack_size,
                   preferred_supplier_name, last_paid_unit_price,
                   last_paid_currency, last_paid_date,
                   reorder_point, on_hand_qty, lead_time_days
            FROM procure_agent.products
            WHERE sku = %s
            """,
            (expected.sku,),
        ).fetchone()
    assert row == (
        expected.sku,
        expected.description,
        expected.category.value,
        expected.uom.value,
        expected.pack_size,
        expected.preferred_supplier_name,
        expected.last_paid_unit_price,
        expected.last_paid_currency,
        expected.last_paid_date,
        expected.reorder_point,
        expected.on_hand_qty,
        expected.lead_time_days,
    )


def test_migrate_is_idempotent(fresh_db_url: str) -> None:
    """A second run reapplies nothing and exits cleanly."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "migrate.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "up to date" in result.stdout
