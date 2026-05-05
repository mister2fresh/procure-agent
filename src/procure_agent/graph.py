"""LangGraph translation of the from-scratch ReAct loop in `agent.py`.

Same Anthropic SDK client, same prompt, same fixture corpus, same tool — the only
change is shape: the loop becomes nodes (`extract` + `tools`), the recursion
becomes a conditional edge (`should_continue`), and run state lives in a typed
dict that LangGraph checkpoints between turns. `match` / `flag` / `approval`
are no-op stubs until those workflows land.
"""

from __future__ import annotations

import json
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from procure_agent.agent import (
    HANDLERS,
    MAX_TOKENS,
    MODEL,
    TOOLS,
    client,
    extract_json_block,
)
from procure_agent.prompts import SYSTEM
from procure_agent.schemas import Quote
from procure_agent.state import QuoteWorkflowState


def extract_node(state: QuoteWorkflowState) -> dict:
    """One Anthropic turn on the extract conversation.

    Reads the running message list from state, calls
    ``client.messages.create`` with the tool catalog and the SYSTEM prompt
    `agent.py` uses, and returns a partial state update appending the
    assistant's response to ``messages``. When ``resp.stop_reason !=
    "tool_use"``, also parse the assistant's fenced JSON into ``quote``.
    """
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        tools=TOOLS,
        messages=state["messages"],
    )
    update: dict = {"messages": [{"role": "assistant", "content": resp.content}]}
    if resp.stop_reason != "tool_use":
        update["quote"] = Quote.model_validate_json(extract_json_block(resp))
    return update


def tools_node(state: QuoteWorkflowState) -> dict:
    """Execute every ``tool_use`` block from the most recent assistant message.

    Mirrors the dispatch loop in ``agent.run``: iterates ``tool_use`` blocks,
    calls the matching handler from ``agent.HANDLERS``, packages outputs as
    ``tool_result`` content blocks, and returns them as a single user-role
    message appended to ``messages``.
    """
    last = state["messages"][-1]
    results = [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(HANDLERS[block.name](**block.input)),
        }
        for block in last["content"]
        if block.type == "tool_use"
    ]
    return {"messages": [{"role": "user", "content": results}]}


def should_continue(state: QuoteWorkflowState) -> Literal["tools", "match"]:
    """Route after `extract_node` — loop through `tools` or advance to `match`.

    Returns ``"tools"`` while the assistant's last message contains any
    ``tool_use`` block; otherwise ``"match"`` to advance the workflow.
    """
    last = state["messages"][-1]
    if any(block.type == "tool_use" for block in last["content"]):
        return "tools"
    return "match"


def match_node(state: QuoteWorkflowState) -> dict:
    """Resolve each ``state["quote"].line_items`` entry against the product master.

    Cascade per line, short-circuiting at the first hit:

    1. exact ``supplier_sku`` → ``MatchMethod.SUPPLIER_SKU_EXACT``
    2. exact ``requested_sku`` → ``MatchMethod.REQUESTED_SKU_EXACT``
    3. fuzzy ``supplier_sku`` → ``MatchMethod.SUPPLIER_SKU_FUZZY``
    4. fuzzy ``requested_sku`` → ``MatchMethod.REQUESTED_SKU_FUZZY``
    5. fuzzy ``description``  → ``MatchMethod.DESCRIPTION_FUZZY``
    6. otherwise              → ``MatchMethod.UNMATCHED`` + an
       ``ExceptionKind.UNMATCHED`` flag on the result

    Calls into :mod:`procure_agent.db` for the lookups. Returns
    ``{"matches": [...]}`` — one ``MatchResult`` per line, in the same order.
    Flag accumulation (price variance, currency, pack/UoM drift) happens in
    :func:`flag_node`; this node only attaches the UNMATCHED flag.
    """
    return {}


def flag_node(state: QuoteWorkflowState) -> dict:
    """Compare each matched product against its quote line and accumulate flags.

    For every ``MatchResult`` in ``state["matches"]`` with a non-None
    ``matched_sku``, load the canonical product and compare against the
    corresponding ``QuoteLineItem``. Append flags for:

    - ``PRICE_VARIANCE`` when ``unit_price`` deviates from
      ``last_paid_unit_price`` by more than the threshold (handoff: 10%).
    - ``CURRENCY_MISMATCH`` when ``currency`` differs from
      ``last_paid_currency``.
    - ``PACK_SIZE_DRIFT`` when ``pack_size`` doesn't normalize to the
      product's ``pack_size``.
    - ``UOM_MISMATCH`` when ``uom`` differs from the product's ``uom``.

    Returns ``{"matches": [...]}`` with the enriched list. Unmatched results
    pass through untouched (their UNMATCHED flag was attached by ``match_node``).
    """
    return {}


def approval_node(state: QuoteWorkflowState) -> dict:
    """No-op until HITL formatting lands.

    The graph halts immediately *before* this node via ``interrupt_before``,
    so this body only runs after the HITL endpoint resumes the run.
    """
    return {}


def build_graph():
    """Wire nodes + edges and compile with the in-memory checkpointer.

    Edges:
        START → extract → (tools → extract)* → match → flag → approval → END

    Halts before ``approval`` so the HITL endpoint can inject the human
    decision into state before the graph resumes.
    """
    builder = StateGraph(QuoteWorkflowState)
    builder.add_node("extract", extract_node)
    builder.add_node("tools", tools_node)
    builder.add_node("match", match_node)
    builder.add_node("flag", flag_node)
    builder.add_node("approval", approval_node)

    builder.add_edge(START, "extract")
    builder.add_conditional_edges(
        "extract",
        should_continue,
        {"tools": "tools", "match": "match"},
    )
    builder.add_edge("tools", "extract")
    builder.add_edge("match", "flag")
    builder.add_edge("flag", "approval")
    builder.add_edge("approval", END)

    return builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["approval"],
    )


graph = build_graph()


if __name__ == "__main__":
    import sys

    from procure_agent.agent import DEFAULT_FIXTURE

    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    initial_state: QuoteWorkflowState = {
        "fixture_filename": fixture,
        "messages": [{"role": "user", "content": f"Extract the quote in {fixture} as JSON."}],
    }
    config = {"configurable": {"thread_id": f"demo-{fixture}"}}
    final_state = graph.invoke(initial_state, config=config)
    print(final_state["quote"].model_dump_json(indent=2))
