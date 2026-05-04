"""Smoke tests for the LangGraph quote-reconciliation graph.

Structural and pure-function checks that run without API calls. The eval harness
covers correctness against real API responses; this file covers wiring.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from procure_agent.graph import (
    build_graph,
    graph,
    should_continue,
    tools_node,
)


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
