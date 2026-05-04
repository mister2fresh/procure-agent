"""Field-aware comparator for predicted-vs-golden Quote JSON.

Operates on raw JSON dicts (not Pydantic instances) so source precision survives:
``"300"`` and ``"300.00"`` are bucketed as ``format_drift``, not silently coerced
into match. Line items are matched on a composite identity key
``(requested_sku, supplier_sku, quantity)``; price stays out so price drift
surfaces as a matched-line field mismatch instead of a P/R loss. Tier prices
are sorted by ``min_qty`` before compare (order is cosmetic per prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# Field paths whose values are Decimal-as-string per the Quote schema. The
# prompt rule "preserve source precision" is enforced via string-equal compare;
# numeric fallback splits format_drift from value_mismatch.
DECIMAL_FIELDS: frozenset[str] = frozenset(
    {
        "line_items.*.quantity",
        "line_items.*.unit_price",
        "line_items.*.min_order_qty",
        "line_items.*.tier_prices.*.min_qty",
        "line_items.*.tier_prices.*.unit_price",
    }
)

QUOTE_LEAF_FIELDS: tuple[str, ...] = (
    "supplier_name",
    "supplier_ref",
    "customer_ref",
    "rfq_ref",
    "issued_date",
    "valid_through",
    "payment_terms",
    "shipping_terms",
    "raw_notes",
)

LINE_ITEM_LEAF_FIELDS: tuple[str, ...] = (
    "requested_sku",
    "supplier_sku",
    "description",
    "pack_size",
    "quantity",
    "uom",
    "unit_price",
    "currency",
    "min_order_qty",
    "notes",
)

TIER_PRICE_LEAF_FIELDS: tuple[str, ...] = ("min_qty", "unit_price")

LineKey = tuple[Any, Any, Any]


@dataclass(frozen=True, slots=True)
class FieldComparison:
    """One leaf-field compare. ``bucket`` is the failure class for aggregation."""

    path: str
    bucket: str  # match | format_drift | value_mismatch
    predicted: Any
    golden: Any


@dataclass(frozen=True, slots=True)
class FixtureResult:
    """Per-fixture comparator output."""

    fixture: str
    quote_fields: tuple[FieldComparison, ...]
    matched_lines: tuple[tuple[FieldComparison, ...], ...]
    only_predicted: int
    only_golden: int
    line_count_predicted: int
    line_count_golden: int


def _bucket_decimal(predicted: Any, golden: Any) -> str:
    """Bucket a Decimal-typed leaf compare. ``"300"`` vs ``"300.00"`` is format_drift."""
    if predicted == golden:
        return "match"
    if predicted is None or golden is None:
        return "value_mismatch"
    try:
        if Decimal(str(predicted)) == Decimal(str(golden)):
            return "format_drift"
    except InvalidOperation:
        pass
    return "value_mismatch"


def _compare_leaf(path: str, predicted: Any, golden: Any) -> FieldComparison:
    if path in DECIMAL_FIELDS:
        bucket = _bucket_decimal(predicted, golden)
    else:
        bucket = "match" if predicted == golden else "value_mismatch"
    return FieldComparison(path=path, bucket=bucket, predicted=predicted, golden=golden)


def _line_key(line: dict) -> LineKey:
    """Composite identity key. Price intentionally excluded so price drift surfaces."""
    return (line.get("requested_sku"), line.get("supplier_sku"), line.get("quantity"))


def _sorted_tiers(line: dict) -> list[dict]:
    tiers = line.get("tier_prices") or []
    try:
        return sorted(tiers, key=lambda t: Decimal(str(t.get("min_qty", "0"))))
    except (InvalidOperation, TypeError):
        return tiers


def _compare_tiers(p_tiers: list[dict], g_tiers: list[dict]) -> tuple[FieldComparison, ...]:
    """Compare tier_prices index-by-index after sort. Length mismatches surface as
    value_mismatch on min_qty/unit_price for the missing tier slot."""
    out: list[FieldComparison] = []
    for i in range(max(len(p_tiers), len(g_tiers))):
        p = p_tiers[i] if i < len(p_tiers) else {}
        g = g_tiers[i] if i < len(g_tiers) else {}
        for fname in TIER_PRICE_LEAF_FIELDS:
            out.append(
                _compare_leaf(f"line_items.*.tier_prices.*.{fname}", p.get(fname), g.get(fname))
            )
    return tuple(out)


def _compare_line(p_line: dict, g_line: dict) -> tuple[FieldComparison, ...]:
    leaves = [
        _compare_leaf(f"line_items.*.{fname}", p_line.get(fname), g_line.get(fname))
        for fname in LINE_ITEM_LEAF_FIELDS
    ]
    leaves.extend(_compare_tiers(_sorted_tiers(p_line), _sorted_tiers(g_line)))
    return tuple(leaves)


def compare(predicted: dict, golden: dict, fixture: str) -> FixtureResult:
    """Compare a predicted Quote dict against its golden.

    Args:
        predicted: Raw JSON dict produced by the agent (post-fenced-block parse).
        golden: Raw JSON dict loaded from the ``.expected.json`` file.
        fixture: Identifier for reporting (typically the golden's stem).

    Returns:
        ``FixtureResult`` with per-leaf-field buckets and line-item P/R counts.
    """
    quote_fields = tuple(
        _compare_leaf(name, predicted.get(name), golden.get(name)) for name in QUOTE_LEAF_FIELDS
    )
    p_lines: list[dict] = predicted.get("line_items") or []
    g_lines: list[dict] = golden.get("line_items") or []
    p_by_key = {_line_key(line): line for line in p_lines}
    g_by_key = {_line_key(line): line for line in g_lines}
    matched = p_by_key.keys() & g_by_key.keys()
    matched_lines = tuple(_compare_line(p_by_key[k], g_by_key[k]) for k in matched)
    return FixtureResult(
        fixture=fixture,
        quote_fields=quote_fields,
        matched_lines=matched_lines,
        only_predicted=len(p_by_key.keys() - g_by_key.keys()),
        only_golden=len(g_by_key.keys() - p_by_key.keys()),
        line_count_predicted=len(p_lines),
        line_count_golden=len(g_lines),
    )
