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

from procure_agent.graph import (
    build_graph,
    graph,
    match_node,
    should_continue,
    tools_node,
)
from procure_agent.schemas import Quote, QuoteLineItem
from procure_agent.state import ExceptionKind, MatchMethod

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_graph_compiles_with_expected_nodes() -> None:
    g = build_graph()
    assert set(g.nodes.keys()) == {
        "__start__",
        "extract",
        "tools",
        "match",
        "flag",
        "approval",
    }


def test_module_level_graph_is_compiled() -> None:
    assert "extract" in graph.nodes


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
