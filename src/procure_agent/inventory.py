"""Inventory product master loader.

Reads the v1 inventory CSV into an in-memory SKU → Product index. The CSV is the source
of truth for product master in v1; Postgres-backed `products` table lands when match
logic moves off the in-memory index.
"""

from __future__ import annotations

from csv import DictReader
from pathlib import Path

from procure_agent.schemas import Product

DEFAULT_INVENTORY_PATH = Path(__file__).resolve().parents[2] / "data/inventory/inventory.csv"


def load_products(path: Path = DEFAULT_INVENTORY_PATH) -> dict[str, Product]:
    """Load the inventory CSV into a SKU-indexed Product dict.

    Args:
        path: 12-column inventory CSV with header row. Defaults to the repo's
            `data/inventory/inventory.csv`.

    Returns:
        Mapping from SKU to Product.

    Raises:
        FileNotFoundError: If `path` does not exist.
        pydantic.ValidationError: If a row fails Product validation (e.g. unknown
            category/UoM, empty cell in a required column, malformed Decimal/date).
    """
    with path.open(newline="") as f:
        return {p.sku: p for p in (Product.model_validate(_clean(row)) for row in DictReader(f))}


def _clean(row: dict[str, str]) -> dict[str, str | None]:
    return {k: (v if v != "" else None) for k, v in row.items()}
