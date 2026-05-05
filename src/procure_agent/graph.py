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
from langgraph.checkpoint.base import BaseCheckpointSaver
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
    LineAction,
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
        system=[
            {
                "type": "text",
                "text": SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
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


def _flag_one(
    conn: psycopg.Connection, line: QuoteLineItem, match: MatchResult
) -> None:
    """Append divergence flags for one (line, match) pair. Mutates ``match.flags``.

    Shared between :func:`flag_node` (initial pass over the whole quote) and
    :func:`approval_node` (re-run against an override SKU). UNMATCHED results
    return early — they keep the UNMATCHED flag ``match_node`` attached.

    Flag rules:

    - ``PRICE_VARIANCE`` when ``unit_price`` deviates from
      ``last_paid_unit_price`` by more than ``PRICE_VARIANCE_THRESHOLD``.
    - ``CURRENCY_MISMATCH`` when ``currency`` differs from
      ``last_paid_currency`` AND both sides are explicitly set. If either side
      is ``None`` (source ambiguous or catalog gap), no flag — ambiguity is
      encoded in the field itself, not surfaced as divergence.
    - ``PACK_SIZE_DRIFT`` when ``pack_size`` doesn't agree with the
      product's ``pack_size`` after cosmetic normalization.
    - ``UOM_MISMATCH`` when ``uom`` doesn't agree with the product's ``uom``
      after cosmetic normalization.
    """
    if match.matched_sku is None:
        return
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
    if (
        line.currency is not None
        and product.last_paid_currency is not None
        and line.currency != product.last_paid_currency
    ):
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


def flag_node(state: QuoteWorkflowState) -> dict:
    """Run :func:`_flag_one` against every (line, match) pair on the quote."""
    with connect() as conn:
        for match, line in zip(
            state["matches"], state["quote"].line_items, strict=True
        ):
            _flag_one(conn, line, match)
    return {"matches": state["matches"]}


def approval_node(state: QuoteWorkflowState) -> dict:
    """Apply the human reviewer's per-line decisions to ``state['matches']``.

    The graph halts immediately *before* this node via ``interrupt_before``,
    so this body only runs after the HITL endpoint has injected
    ``human_decision`` into state and resumed the run.

    Per-line action semantics:

    - ``APPROVE`` — record ``human_action`` on the result; the cascade match
      and any flags pass through untouched.
    - ``REJECT`` — record ``human_action``; the line is excluded from any
      downstream PO. The original match + flags stay on the result so the
      audit trail preserves what the reviewer rejected.
    - ``OVERRIDE`` — set ``matched_sku`` to the reviewer's choice, mark the
      result ``MatchMethod.HUMAN_OVERRIDE`` with full confidence, drop the
      flags from the prior (wrong) match, and re-run :func:`_flag_one`
      against the override SKU so any new divergences surface immediately.

    The API boundary (:func:`procure_agent.api.resume_run`) validates that
    every ``override_sku`` resolves to a real product before the graph
    resumes, so ``_flag_one`` here is guaranteed a hydratable SKU.
    """
    decision = state["human_decision"]
    matches = state["matches"]
    by_index = {m.line_index: m for m in matches}
    lines = state["quote"].line_items

    with connect() as conn:
        for ld in decision.line_decisions:
            match = by_index[ld.line_index]
            match.human_action = ld.action
            if ld.action == LineAction.OVERRIDE:
                match.matched_sku = ld.override_sku
                match.match_method = MatchMethod.HUMAN_OVERRIDE
                match.confidence = 1.0
                match.flags = []
                _flag_one(conn, lines[ld.line_index], match)
    return {"matches": matches}


def build_graph(checkpointer: BaseCheckpointSaver):
    """Wire nodes + edges and compile with the supplied checkpointer.

    Edges:
        START → extract → (tools → extract)* → match → flag → approval → END

    Halts before ``approval`` so the HITL endpoint can inject the human
    decision into state before the graph resumes. Caller owns the checkpointer
    lifecycle — pass ``MemorySaver`` for tests/evals, ``PostgresSaver`` for
    anything that needs to survive a process restart (CLI demo, FastAPI HITL).
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
        checkpointer=checkpointer,
        interrupt_before=["approval"],
    )


if __name__ == "__main__":
    import os
    import sys

    from langgraph.checkpoint.postgres import PostgresSaver

    from procure_agent.agent import DEFAULT_FIXTURE

    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    url = os.environ["DATABASE_URL"]
    initial_state: QuoteWorkflowState = {
        "fixture_filename": fixture,
        "messages": [{"role": "user", "content": f"Extract the quote in {fixture} as JSON."}],
    }
    config = {"configurable": {"thread_id": f"demo-{fixture}"}}
    with PostgresSaver.from_conn_string(url) as checkpointer:
        graph = build_graph(checkpointer)
        final_state = graph.invoke(initial_state, config=config)
    print(final_state["quote"].model_dump_json(indent=2))
