"""Tests for the inventory CSV loader."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from procure_agent.inventory import DEFAULT_INVENTORY_PATH, load_products
from procure_agent.schemas import Category, UoM


def test_real_csv_loads_clean() -> None:
    products = load_products()
    assert len(products) == 146
    assert all(sku == p.sku for sku, p in products.items())


def test_anchor_sku_matches_source_row() -> None:
    al101 = load_products()["AL101"]
    assert al101.description == "Aloe vera extract food grade powder"
    assert al101.category is Category.SOIL_AMENDMENT
    assert al101.uom is UoM.KG
    assert al101.pack_size == "5 kg pail"
    assert al101.preferred_supplier_name == "Aloe Corp."
    assert al101.last_paid_unit_price == Decimal("78.50")
    assert al101.last_paid_currency == "USD"
    assert al101.last_paid_date == date(2026, 2, 10)
    assert al101.reorder_point == 10
    assert al101.on_hand_qty == 18
    assert al101.lead_time_days == 14


def test_substitution_anchor_preserved() -> None:
    """KMEAL-44 is intentionally absent so the NutriGrow substitution case still fires."""
    products = load_products()
    assert "KMEAL-50" in products
    assert "KMEAL-44" not in products


def test_empty_currency_cell_loads_as_none(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, last_paid_currency="")
    products = load_products(csv_path)
    assert products["TEST-1"].last_paid_currency is None


def test_unknown_category_fails_validation(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, category="not_a_real_category")
    with pytest.raises(ValidationError):
        load_products(csv_path)


def test_unknown_uom_fails_validation(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path, uom="bag")
    with pytest.raises(ValidationError):
        load_products(csv_path)


def test_default_path_points_at_repo_inventory() -> None:
    assert DEFAULT_INVENTORY_PATH.exists()
    assert DEFAULT_INVENTORY_PATH.name == "inventory.csv"


def _write_csv(tmp_path: Path, **overrides: str) -> Path:
    """Factory for a single-row inventory CSV. Override any column to exercise an edge case."""
    fields: dict[str, str] = {
        "sku": "TEST-1",
        "description": "Test product",
        "category": "fertilizer",
        "uom": "kg",
        "pack_size": "5 kg pail",
        "preferred_supplier_name": "Test Supplier",
        "last_paid_unit_price": "10.00",
        "last_paid_currency": "USD",
        "last_paid_date": "2026-01-01",
        "reorder_point": "10",
        "on_hand_qty": "20",
        "lead_time_days": "7",
    }
    fields.update(overrides)
    header = ",".join(fields)
    row = ",".join(fields.values())
    csv_path = tmp_path / "inventory.csv"
    csv_path.write_text(f"{header}\n{row}\n")
    return csv_path
