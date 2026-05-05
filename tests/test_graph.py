"""Smoke tests for the LangGraph quote-reconciliation graph.

Structural and pure-function checks that run without API calls, plus
``match_node`` integration tests that hit the seeded postgres catalog
(skipped when ``DATABASE_URL`` is unreachable). The eval harness covers
end-to-end correctness against real API responses; this file covers wiring
and the cascade behaviour of ``match_node`` against the real DB.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from procure_agent.graph import (
    build_graph,
    flag_node,
    match_node,
    should_continue,
    tools_node,
)
from procure_agent.schemas import Quote, QuoteLineItem
from procure_agent.state import Exception_, ExceptionKind, MatchMethod, MatchResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_graph_compiles_with_expected_nodes() -> None:
    g = build_graph(MemorySaver())
    assert set(g.nodes.keys()) == {
        "__start__",
        "extract",
        "tools",
        "match",
        "flag",
        "approval",
    }


def test_should_continue_routes_to_tools_when_tool_use_present() -> None:
    state = _state_with(
        _block(type_="text", text="thinking..."),
        _block(type_="tool_use", id="t1", name="read_file", input={}),
    )
    assert should_continue(state) == "tools"


def test_should_continue_routes_to_match_when_no_tool_use() -> None:
    state = _state_with(_block(type_="text", text="```json\n{}\n```"))
    assert should_continue(state) == "match"


def test_tools_node_dispatches_read_file() -> None:
    state = _state_with(
        _block(
            type_="tool_use",
            id="t1",
            name="read_file",
            input={"filename": "01_aloe_corp_clean_tabular.txt"},
        ),
    )
    update = tools_node(state)
    [msg] = update["messages"]
    assert msg["role"] == "user"
    [result] = msg["content"]
    assert result["tool_use_id"] == "t1"
    assert "ALOE CORP" in json.loads(result["content"])


def test_tools_node_skips_text_blocks() -> None:
    state = _state_with(
        _block(type_="text", text="here you go"),
        _block(
            type_="tool_use",
            id="t1",
            name="read_file",
            input={"filename": "01_aloe_corp_clean_tabular.txt"},
        ),
    )
    update = tools_node(state)
    [msg] = update["messages"]
    assert len(msg["content"]) == 1


def _block(*, type_: str, **kwargs: object) -> SimpleNamespace:
    """Stand-in for an Anthropic content block (attribute-access)."""
    return SimpleNamespace(type=type_, **kwargs)


def _state_with(*blocks: SimpleNamespace) -> dict:
    """Wrap content blocks in a state shape with one assistant message."""
    return {"messages": [{"role": "assistant", "content": list(blocks)}]}


# --- match_node integration tests (real DB) ---------------------------------


@pytest.fixture
def _require_db() -> None:
    """Skip the test if DATABASE_URL is unset or the server is unreachable."""
    load_dotenv(REPO_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        with psycopg.connect(url):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"DATABASE_URL unreachable: {exc}")


def _make_line(**overrides: object) -> QuoteLineItem:
    """Build a QuoteLineItem with sensible defaults; override per test."""
    defaults: dict[str, object] = {
        "requested_sku": None,
        "supplier_sku": None,
        "description": "placeholder description",
        "pack_size": None,
        "quantity": Decimal("1"),
        "uom": "each",
        "unit_price": Decimal("0"),
        "currency": "USD",
    }
    defaults.update(overrides)
    return QuoteLineItem(**defaults)


def _make_quote(*lines: QuoteLineItem) -> Quote:
    """Wrap line items in a minimal Quote so match_node can iterate them."""
    return Quote(supplier_name="Test Supplier", line_items=list(lines))


def test_match_node_tier3_supplier_sku_fuzzy(_require_db: None) -> None:
    """Drifted supplier_sku (no dashes) lands at tier 3 with the trigram score."""
    quote = _make_quote(
        _make_line(supplier_sku="STRAPPP58", description="poly strapping"),
    )
    [match] = match_node({"quote": quote})["matches"]
    assert match.line_index == 0
    assert match.match_method == MatchMethod.SUPPLIER_SKU_FUZZY
    assert match.matched_sku == "STRAP-PP-58"
    assert 0.0 < match.confidence < 1.0
    assert match.flags == []


def test_match_node_tier4_requested_sku_fuzzy(_require_db: None) -> None:
    """Tier 1+3 skip on supplier_sku=None; tier 2 misses; tier 4 catches the drift."""
    quote = _make_quote(
        _make_line(requested_sku="STRAPPP58", description="poly strapping"),
    )
    [match] = match_node({"quote": quote})["matches"]
    assert match.match_method == MatchMethod.REQUESTED_SKU_FUZZY
    assert match.matched_sku == "STRAP-PP-58"
    assert 0.0 < match.confidence < 1.0
    assert match.flags == []


def test_match_node_tier5_description_fuzzy(_require_db: None) -> None:
    """Both SKUs absent — description trigram resolves the line."""
    quote = _make_quote(
        _make_line(description="Aloe vera extract food grade"),
    )
    [match] = match_node({"quote": quote})["matches"]
    assert match.match_method == MatchMethod.DESCRIPTION_FUZZY
    assert match.matched_sku == "AL101"
    assert 0.0 < match.confidence <= 1.0
    assert match.flags == []


def test_match_node_unmatched_attaches_flag(_require_db: None) -> None:
    """Garbage on every signal — fallthrough records UNMATCHED with a populated detail."""
    quote = _make_quote(
        _make_line(
            supplier_sku="ZZZZZZZZZZ-NOPE-99999",
            requested_sku="QQQQQQQ-MISS",
            description="quantum entanglement field generator",
        ),
    )
    [match] = match_node({"quote": quote})["matches"]
    assert match.match_method == MatchMethod.UNMATCHED
    assert match.matched_sku is None
    assert match.confidence == 0.0
    [flag] = match.flags
    assert flag.kind == ExceptionKind.UNMATCHED
    assert "ZZZZZZZZZZ-NOPE-99999" in flag.detail
    assert "QQQQQQQ-MISS" in flag.detail
    assert "quantum entanglement" in flag.detail


# --- flag_node integration tests --------------------------------------------
#
# Catalog rows used (from data/inventory/inventory.csv):
#   AL101         kg   5 kg pail        78.50 USD
#   STRAP-PP-58   each 6000 ft coil     58.00 USD
#   NITRILE-M-100 each box of 100        8.50 USD


def _make_match(line_index: int, matched_sku: str | None, **overrides: object) -> MatchResult:
    """Build a MatchResult mirroring what match_node would emit."""
    defaults: dict[str, object] = {
        "line_index": line_index,
        "matched_sku": matched_sku,
        "match_method": (
            MatchMethod.SUPPLIER_SKU_EXACT if matched_sku else MatchMethod.UNMATCHED
        ),
        "confidence": 1.0 if matched_sku else 0.0,
        "flags": [],
    }
    defaults.update(overrides)
    return MatchResult(**defaults)


def _aloe_clean_line(**overrides: object) -> QuoteLineItem:
    """A QuoteLineItem that matches AL101 cleanly on every flag axis."""
    base: dict[str, object] = {
        "supplier_sku": "AL101",
        "description": "Aloe vera extract food grade powder",
        "pack_size": "5 kg pail",
        "quantity": Decimal("10"),
        "uom": "kg",
        "unit_price": Decimal("78.50"),
        "currency": "USD",
    }
    base.update(overrides)
    return _make_line(**base)


def test_flag_node_clean_match_emits_no_flags(_require_db: None) -> None:
    """Every axis agrees with the catalog — flags stay empty."""
    quote = _make_quote(_aloe_clean_line())
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert match.flags == []


def test_flag_node_price_variance_above_threshold(_require_db: None) -> None:
    """20% price hike fires PRICE_VARIANCE only; detail carries the numbers."""
    quote = _make_quote(_aloe_clean_line(unit_price=Decimal("94.20")))  # +20%
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    [flag] = match.flags
    assert flag.kind == ExceptionKind.PRICE_VARIANCE
    assert "94.20" in flag.detail
    assert "78.50" in flag.detail
    assert "20" in flag.detail  # "20.0%" appears in the formatted deviation


def test_flag_node_price_within_threshold_emits_no_flag(_require_db: None) -> None:
    """5% drift is under the 10% threshold — no flag."""
    quote = _make_quote(_aloe_clean_line(unit_price=Decimal("82.43")))  # +5%
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert match.flags == []


def test_flag_node_currency_mismatch(_require_db: None) -> None:
    quote = _make_quote(_aloe_clean_line(currency="CAD"))
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    [flag] = match.flags
    assert flag.kind == ExceptionKind.CURRENCY_MISMATCH
    assert "CAD" in flag.detail
    assert "USD" in flag.detail


def test_flag_node_currency_unknown_quote_side_no_flag(_require_db: None) -> None:
    """Source ambiguous (line.currency is None) — no currency_mismatch flag fires
    even though the catalog has an explicit last_paid_currency."""
    quote = _make_quote(_aloe_clean_line(currency=None))
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert not any(f.kind == ExceptionKind.CURRENCY_MISMATCH for f in match.flags)


def test_flag_node_currency_unknown_catalog_side_no_flag(_require_db: None) -> None:
    """Catalog gap (product.last_paid_currency is None) — no flag, even when the
    quote states an explicit currency. SULFUR-PRILL-50 is seeded with last_paid_currency=None."""
    quote = _make_quote(_aloe_clean_line(currency="USD"))
    matches = [_make_match(0, "SULFUR-PRILL-50")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert not any(f.kind == ExceptionKind.CURRENCY_MISMATCH for f in match.flags)


def test_flag_node_pack_size_substantive_drift(_require_db: None) -> None:
    """Different container word fires PACK_SIZE_DRIFT."""
    quote = _make_quote(_aloe_clean_line(pack_size="5 kg sack"))
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    [flag] = match.flags
    assert flag.kind == ExceptionKind.PACK_SIZE_DRIFT


def test_flag_node_pack_size_cosmetic_drift_suppressed(_require_db: None) -> None:
    """Glued digit/letter is cosmetic — same_pack_size collapses it, no flag."""
    quote = _make_quote(_aloe_clean_line(pack_size="5kg pail"))
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert match.flags == []


def test_flag_node_uom_substantive_drift(_require_db: None) -> None:
    """Pacific Amendments scenario: supplier ROLL vs catalog `each`."""
    line = _make_line(
        supplier_sku="STRAP-PP-58",
        description="Polypropylene strapping machine grade",
        pack_size="6000 ft coil",
        quantity=Decimal("2"),
        uom="ROLL",
        unit_price=Decimal("58.00"),
        currency="USD",
    )
    quote = _make_quote(line)
    matches = [_make_match(0, "STRAP-PP-58")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    [flag] = match.flags
    assert flag.kind == ExceptionKind.UOM_MISMATCH
    assert "ROLL" in flag.detail


def test_flag_node_uom_cosmetic_drift_suppressed(_require_db: None) -> None:
    """`Kg` vs catalog `kg` is alias-mapped — no flag."""
    quote = _make_quote(_aloe_clean_line(uom="Kg"))
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert match.flags == []


def test_flag_node_all_four_flags_on_one_line(_require_db: None) -> None:
    """Every axis off — every flag fires, in cascade order."""
    quote = _make_quote(
        _aloe_clean_line(
            unit_price=Decimal("100.00"),  # +27% > 10%
            currency="EUR",
            pack_size="10 kg drum",
            uom="lb",
        )
    )
    matches = [_make_match(0, "AL101")]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    kinds = [f.kind for f in match.flags]
    assert kinds == [
        ExceptionKind.PRICE_VARIANCE,
        ExceptionKind.CURRENCY_MISMATCH,
        ExceptionKind.PACK_SIZE_DRIFT,
        ExceptionKind.UOM_MISMATCH,
    ]


def test_flag_node_unmatched_passthrough(_require_db: None) -> None:
    """Unmatched lines keep their UNMATCHED flag and gain nothing else."""
    quote = _make_quote(
        _make_line(description="quantum entanglement field generator"),
    )
    prior_flag = Exception_(kind=ExceptionKind.UNMATCHED, detail="no match")
    matches = [_make_match(0, None, flags=[prior_flag])]
    [match] = flag_node({"quote": quote, "matches": matches})["matches"]
    assert match.flags == [prior_flag]


def test_flag_node_independent_lines(_require_db: None) -> None:
    """Multi-line: one clean, one dirty, one unmatched — flags stay scoped."""
    quote = _make_quote(
        _aloe_clean_line(),
        _aloe_clean_line(unit_price=Decimal("100.00")),  # price variance
        _make_line(description="not a real product"),
    )
    matches = [
        _make_match(0, "AL101"),
        _make_match(1, "AL101"),
        _make_match(
            2, None, flags=[Exception_(kind=ExceptionKind.UNMATCHED, detail="x")]
        ),
    ]
    out = flag_node({"quote": quote, "matches": matches})["matches"]
    assert out[0].flags == []
    [variance] = out[1].flags
    assert variance.kind == ExceptionKind.PRICE_VARIANCE
    [unmatched] = out[2].flags
    assert unmatched.kind == ExceptionKind.UNMATCHED
