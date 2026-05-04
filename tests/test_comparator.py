"""Regression tests for the line-bucketing path in ``evals.comparator``.

Catches the silent-collapse bug where two predicted lines sharing the same
composite identity key (e.g. null SKUs + same quantity) were being merged into
one match by the prior dict-keyed implementation, dropping a real line from the
P/R count without surfacing as ``only_predicted``.
"""

from __future__ import annotations

from typing import Any

from evals.comparator import compare


def _line(**overrides: Any) -> dict[str, Any]:
    base = {
        "requested_sku": None,
        "supplier_sku": None,
        "description": "Item",
        "pack_size": None,
        "quantity": "1",
        "uom": "each",
        "unit_price": "1.00",
        "currency": None,
        "tier_prices": [],
        "min_order_qty": None,
        "notes": None,
    }
    return {**base, **overrides}


def _quote(*lines: dict[str, Any]) -> dict[str, Any]:
    return {
        "supplier_name": "S",
        "supplier_ref": None,
        "customer_ref": None,
        "rfq_ref": None,
        "issued_date": None,
        "valid_through": None,
        "line_items": list(lines),
        "payment_terms": None,
        "shipping_terms": None,
        "raw_notes": None,
    }


def test_colliding_keys_pair_positionally() -> None:
    a = _line(quantity="12", description="A", unit_price="385.00")
    b = _line(quantity="12", description="B", unit_price="445.00")
    result = compare(_quote(a, b), _quote(a, b), "collide")
    assert len(result.matched_lines) == 2
    assert result.only_predicted == 0
    assert result.only_golden == 0


def test_surplus_lines_count_as_only_predicted() -> None:
    a = _line(quantity="12", description="A")
    b = _line(quantity="12", description="B")
    c = _line(quantity="12", description="C")
    result = compare(_quote(a, b, c), _quote(a, b), "surplus")
    assert len(result.matched_lines) == 2
    assert result.only_predicted == 1
    assert result.only_golden == 0


def test_unique_keys_unaffected() -> None:
    a = _line(requested_sku="SKU-A", quantity="1")
    b = _line(requested_sku="SKU-B", quantity="2")
    result = compare(_quote(a, b), _quote(b, a), "reordered")
    assert len(result.matched_lines) == 2
    assert result.only_predicted == 0
    assert result.only_golden == 0


def _bucket_for(result, path: str) -> str:
    for fc in result.quote_fields:
        if fc.path == path:
            return fc.bucket
    raise AssertionError(f"path {path} not found")


def test_prose_paragraph_separator_drift_is_format_drift() -> None:
    p = _quote(_line(requested_sku="A"))
    g = _quote(_line(requested_sku="A"))
    p["raw_notes"] = "Lead Time: 14-21 days\nLines 5 and 7 quoted in USD"
    g["raw_notes"] = "Lead Time: 14-21 days\n\nLines 5 and 7 quoted in USD"
    assert _bucket_for(compare(p, g, "f"), "raw_notes") == "format_drift"


def test_prose_line_wrap_drift_is_format_drift() -> None:
    p = _quote(_line(requested_sku="A"))
    g = _quote(_line(requested_sku="A"))
    p["raw_notes"] = "got most of what you wanted in stock but a couple items I had to check"
    g["raw_notes"] = "got most of what you wanted in stock but a couple\nitems I had to check"
    assert _bucket_for(compare(p, g, "f"), "raw_notes") == "format_drift"


def test_prose_substantive_change_still_value_mismatch() -> None:
    p = _quote(_line(requested_sku="A"))
    g = _quote(_line(requested_sku="A"))
    p["raw_notes"] = "Lead time 14 days"
    g["raw_notes"] = "Lead time 21 days"
    assert _bucket_for(compare(p, g, "f"), "raw_notes") == "value_mismatch"


def test_prose_null_vs_string_is_value_mismatch() -> None:
    p = _quote(_line(requested_sku="A"))
    g = _quote(_line(requested_sku="A"))
    p["raw_notes"] = None
    g["raw_notes"] = "something"
    assert _bucket_for(compare(p, g, "f"), "raw_notes") == "value_mismatch"


def test_prose_tolerance_does_not_apply_to_decimal_fields() -> None:
    p = _quote(_line(requested_sku="A", unit_price="300"))
    g = _quote(_line(requested_sku="A", unit_price="300.00"))
    result = compare(p, g, "f")
    bucket = next(
        fc.bucket for fc in result.matched_lines[0] if fc.path == "line_items.*.unit_price"
    )
    assert bucket == "format_drift"
