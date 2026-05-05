"""LangGraph translation of the from-scratch ReAct loop in `agent.py`.

Same Anthropic SDK client, same prompt, same fixture corpus, same tool — the only
change is shape: the loop becomes nodes (`extract` + `tools`), the recursion
becomes a conditional edge (`should_continue`), and run state lives in a typed
dict that LangGraph checkpoints between turns. `match` / `flag` / `approval`
are no-op stubs until those workflows land.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Literal

import psycopg
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
from procure_agent.db import (
    connect,
    find_products_by_description_similarity,
    find_products_by_sku_similarity,
    get_product,
)
from procure_agent.normalize import same_pack_size, same_uom
from procure_agent.prompts import SYSTEM
from procure_agent.schemas import Quote, QuoteLineItem
from procure_agent.state import (
    Exception_,
    ExceptionKind,
    MatchMethod,
    MatchResult,
    QuoteWorkflowState,
)

PRICE_VARIANCE_THRESHOLD = Decimal("0.10")  # 10% per handoff


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


def _match_line(
    conn: psycopg.Connection, line_index: int, line: QuoteLineItem
) -> MatchResult:
    """Run the match cascade for one quote line. Short-circuits at first hit."""
    # Tier 1: exact supplier_sku
    if line.supplier_sku and (p := get_product(conn, line.supplier_sku)):
        return MatchResult(
            line_index=line_index,
            matched_sku=p.sku,
            match_method=MatchMethod.SUPPLIER_SKU_EXACT,
            confidence=1.0,
        )

    # Tier 2: exact requested_sku
    if line.requested_sku and (p := get_product(conn, line.requested_sku)):
        return MatchResult(
            line_index=line_index,
            matched_sku=p.sku,
            match_method=MatchMethod.REQUESTED_SKU_EXACT,
            confidence=1.0,
        )

    # Tier 3: fuzzy supplier_sku
    if line.supplier_sku:
        hits = find_products_by_sku_similarity(conn, line.supplier_sku, limit=1)
        if hits:
            return MatchResult(
                line_index=line_index,
                matched_sku=hits[0].product.sku,
                match_method=MatchMethod.SUPPLIER_SKU_FUZZY,
                confidence=hits[0].score,
            )

    # Tier 4: fuzzy requested_sku
    if line.requested_sku:
        hits = find_products_by_sku_similarity(conn, line.requested_sku, limit=1)
        if hits:
            return MatchResult(
                line_index=line_index,
                matched_sku=hits[0].product.sku,
                match_method=MatchMethod.REQUESTED_SKU_FUZZY,
                confidence=hits[0].score,
            )

    # Tier 5: fuzzy description (no guard — description is required)
    hits = find_products_by_description_similarity(conn, line.description, limit=1)
    if hits:
        return MatchResult(
            line_index=line_index,
            matched_sku=hits[0].product.sku,
            match_method=MatchMethod.DESCRIPTION_FUZZY,
            confidence=hits[0].score,
        )

    # Fallthrough: UNMATCHED
    return MatchResult(
        line_index=line_index,
        match_method=MatchMethod.UNMATCHED,
        flags=[
            Exception_(
                kind=ExceptionKind.UNMATCHED,
                detail=(
                    f"no product master row matched "
                    f"supplier_sku={line.supplier_sku!r}, "
                    f"requested_sku={line.requested_sku!r}, "
                    f"description={line.description!r}"
                ),
            )
        ],
    )


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
    with connect() as conn:
        matches = [
            _match_line(conn, i, line)
            for i, line in enumerate(state["quote"].line_items)
        ]
    return {"matches": matches}


def flag_node(state: QuoteWorkflowState) -> dict:
    """Compare each matched product against its quote line and accumulate flags.

    For every ``MatchResult`` in ``state["matches"]`` with a non-None
    ``matched_sku``, load the canonical product and append flags for:

    - ``PRICE_VARIANCE`` when ``unit_price`` deviates from
      ``last_paid_unit_price`` by more than ``PRICE_VARIANCE_THRESHOLD``.
    - ``CURRENCY_MISMATCH`` when ``currency`` differs from
      ``last_paid_currency``.
    - ``PACK_SIZE_DRIFT`` when ``pack_size`` doesn't agree with the
      product's ``pack_size`` after cosmetic normalization.
    - ``UOM_MISMATCH`` when ``uom`` doesn't agree with the product's ``uom``
      after cosmetic normalization.

    Mutates each ``MatchResult.flags`` in place. UNMATCHED results pass
    through untouched — their UNMATCHED flag was attached by ``match_node``.
    Returns ``{"matches": state["matches"]}``.
    """
    with connect() as conn:
        for match, line in zip(
            state["matches"], state["quote"].line_items, strict=True
        ):
            if match.matched_sku is None:
                continue
            product = get_product(conn, match.matched_sku)
            deviation = (
                abs(line.unit_price - product.last_paid_unit_price)
                / product.last_paid_unit_price
            )
            if deviation > PRICE_VARIANCE_THRESHOLD:
                match.flags.append(Exception_(
                    kind=ExceptionKind.PRICE_VARIANCE,
                    detail=(
                        f"unit_price {line.unit_price} deviates {deviation:.1%} "
                        f"from last paid {product.last_paid_unit_price}"
                    ),
                ))
            if line.currency != product.last_paid_currency:
                match.flags.append(Exception_(
                    kind=ExceptionKind.CURRENCY_MISMATCH,
                    detail=(
                        f"quote currency {line.currency} != "
                        f"last paid {product.last_paid_currency}"
                    ),
                ))
            if not same_pack_size(line.pack_size, product.pack_size):
                match.flags.append(Exception_(
                    kind=ExceptionKind.PACK_SIZE_DRIFT,
                    detail=(
                        f"quote pack_size {line.pack_size} != "
                        f"product {product.pack_size}"
                    ),
                ))
            if not same_uom(line.uom, product.uom):
                match.flags.append(Exception_(
                    kind=ExceptionKind.UOM_MISMATCH,
                    detail=f"quote uom {line.uom} != product {product.uom}",
                ))
    return {"matches": state["matches"]}


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
