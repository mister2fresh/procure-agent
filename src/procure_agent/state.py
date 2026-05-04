"""LangGraph state types for the quote-reconciliation workflow.

Mirrors the state shape called out in the handoff: a typed dict carrying raw input,
the parsed Quote, per-line match results, flagged exceptions, and the human-decision
payload. `MatchResult` and `Exception_` are placeholder shells; their fields firm up
as the match and flag nodes land.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

from procure_agent.schemas import Quote


class MatchResult(BaseModel):
    """One extracted line item's match outcome against the product master.

    Schema firms up with the match node; today the workflow only carries the
    line index so the state shape is structurally meaningful.
    """

    line_index: int


class Exception_(BaseModel):
    """A conflict flagged for human review.

    Schema firms up with the flag node. `kind` tightens to a StrEnum once the
    closed set of flag categories stabilizes (sku_not_found, price_variance, etc.).
    """

    line_index: int | None
    kind: str
    detail: str


class QuoteWorkflowState(TypedDict, total=False):
    """Workflow state carried across LangGraph nodes.

    Fields:
        fixture_filename: Synthetic-quote fixture this run is keyed to.
        messages: Anthropic-native conversation history (list of dicts with
            ``role`` and ``content``). The ``Annotated[..., operator.add]``
            reducer makes node returns concatenate rather than overwrite.
        quote: Parsed structured form, populated by `extract_node` when the
            ReAct loop terminates.
        matches: Per-line match outcomes, populated by `match_node`.
        exceptions: Flagged conflicts, populated by `flag_node`.
        human_decision: Approval payload set by the HITL endpoint after the
            graph resumes from `interrupt_before`.
    """

    fixture_filename: str
    messages: Annotated[list[dict], operator.add]
    quote: Quote
    matches: list[MatchResult]
    exceptions: list[Exception_]
    human_decision: dict
