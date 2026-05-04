"""Generate migrations/0002_seed_products.sql from data/inventory/inventory.csv.

Reads the CSV via the existing loader (so it shares Pydantic validation with
the runtime path), emits a single multi-row INSERT into procure_agent.products,
and writes the result to migrations/. Run after the CSV changes, then commit
the generated SQL.

Usage:
    uv run python scripts/generate_seed_sql.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from procure_agent.inventory import load_products
from procure_agent.schemas import Product

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "migrations" / "0002_seed_products.sql"

COLUMNS = (
    "sku",
    "description",
    "category",
    "uom",
    "pack_size",
    "preferred_supplier_name",
    "last_paid_unit_price",
    "last_paid_currency",
    "last_paid_date",
    "reorder_point",
    "on_hand_qty",
    "lead_time_days",
)


def main() -> int:
    """Render the seed migration. Returns 0."""
    products = sorted(load_products().values(), key=lambda p: p.sku)
    rows = [_render_row(p) for p in products]

    body = (
        "-- Auto-generated from data/inventory/inventory.csv by "
        "scripts/generate_seed_sql.py.\n"
        "-- Do not edit by hand; re-run the generator and commit the result.\n"
        "\n"
        f"INSERT INTO procure_agent.products ({', '.join(COLUMNS)}) VALUES\n"
        + ",\n".join(rows)
        + ";\n"
    )
    OUT_PATH.write_text(body)
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} ({len(rows)} rows)")
    return 0


def _render_row(p: Product) -> str:
    """Render one product as a parenthesized VALUES tuple."""
    fields = (
        _lit(p.sku),
        _lit(p.description),
        f"{_lit(p.category.value)}::procure_agent.category",
        f"{_lit(p.uom.value)}::procure_agent.uom",
        _lit(p.pack_size),
        _lit(p.preferred_supplier_name),
        _lit(p.last_paid_unit_price),
        _lit(p.last_paid_currency),
        _lit(p.last_paid_date),
        _lit(p.reorder_point),
        _lit(p.on_hand_qty),
        _lit(p.lead_time_days),
    )
    return f"    ({', '.join(fields)})"


def _lit(value: str | Decimal | date | int | None) -> str:
    """Render a Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (Decimal, int)):
        return str(value)
    if isinstance(value, date):
        return f"'{value.isoformat()}'"
    raise TypeError(f"unsupported literal type: {type(value).__name__}")


if __name__ == "__main__":
    sys.exit(main())
