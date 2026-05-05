"""LangGraph state types for the quote-reconciliation workflow.

Mirrors the state shape called out in the handoff: a typed dict carrying raw
input, the parsed Quote, per-line match results (which own their own flags),
and the human-decision payload. Quote-level flags (supplier address drift,
header mismatches) are out of scope until supplier-onboarding ships.
"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field

from procure_agent.schemas import Quote


class MatchMethod(StrEnum):
    """Which signal in the cascade carried this line.

    Tracks the cascade order in match_node so eval and HITL can distinguish
    a strong exact-SKU match from a weaker description-fuzzy hit.
    """

    SUPPLIER_SKU_EXACT = "supplier_sku_exact"
    REQUESTED_SKU_EXACT = "requested_sku_exact"
    SUPPLIER_SKU_FUZZY = "supplier_sku_fuzzy"
    REQUESTED_SKU_FUZZY = "requested_sku_fuzzy"
    DESCRIPTION_FUZZY = "description_fuzzy"
    UNMATCHED = "unmatched"


class ExceptionKind(StrEnum):
    """Closed set of flag categories. Add a value when a new flag rule lands."""

    UNMATCHED = "unmatched"
    PRICE_VARIANCE = "price_variance"
    CURRENCY_MISMATCH = "currency_mismatch"
    PACK_SIZE_DRIFT = "pack_size_drift"
    UOM_MISMATCH = "uom_mismatch"


class Exception_(BaseModel):
    """A conflict surfaced for human review.

    Lives on the :class:`MatchResult` it explains — a flag without a match it
    varies from has no domain meaning, so we don't carry a separate quote-level
    exceptions list.
    """

    kind: ExceptionKind
    detail: str = Field(
        ...,
        description="Human-readable summary the HITL operator reads to decide. "
        "Free-text by design — structured comparison fields land only if the UI "
        "demands them.",
    )


class MatchResult(BaseModel):
    """One quote line item's match outcome and any divergence flags.

    ``matched_sku`` is the canonical buyer-side SKU from
    ``procure_agent.products`` when a match was found, otherwise ``None``.
    ``flags`` lists every :class:`Exception_` raised against this line; an
    empty list is a clean reconciliation. ``confidence`` is 1.0 for exact
    matches, the trigram similarity score for fuzzy matches, and 0.0 when
    unmatched.
    """

    line_index: int
    matched_sku: str | None = None
    match_method: MatchMethod = MatchMethod.UNMATCHED
    confidence: float = 0.0
    flags: list[Exception_] = Field(default_factory=list)


class QuoteWorkflowState(TypedDict, total=False):
    """Workflow state carried across LangGraph nodes.

    Fields:
        fixture_filename: Synthetic-quote fixture this run is keyed to.
        messages: Anthropic-native conversation history. The
            ``Annotated[..., operator.add]`` reducer makes node returns
            concatenate rather than overwrite.
        quote: Parsed structured form, populated by ``extract_node``.
        matches: Per-line match outcomes (each carrying its own flags),
            populated by ``match_node`` and enriched by ``flag_node``.
        human_decision: Approval payload set by the HITL endpoint after the
            graph resumes from ``interrupt_before``.
    """

    fixture_filename: str
    messages: Annotated[list[dict], operator.add]
    quote: Quote
    matches: list[MatchResult]
    human_decision: dict
