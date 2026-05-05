"""LangGraph state types for the quote-reconciliation workflow.

Mirrors the state shape called out in the handoff: a typed dict carrying raw
input, the parsed Quote, per-line match results (which own their own flags),
and the human-decision payload. Quote-level flags (supplier address drift,
header mismatches) are out of scope until supplier-onboarding ships.
"""

from __future__ import annotations

import operator
from datetime import datetime
from enum import StrEnum
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field, model_validator

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
    HUMAN_OVERRIDE = "human_override"


class ExceptionKind(StrEnum):
    """Closed set of flag categories. Add a value when a new flag rule lands."""

    UNMATCHED = "unmatched"
    PRICE_VARIANCE = "price_variance"
    CURRENCY_MISMATCH = "currency_mismatch"
    PACK_SIZE_DRIFT = "pack_size_drift"
    UOM_MISMATCH = "uom_mismatch"


class LineAction(StrEnum):
    """How the human reviewer chose to resolve a single quote line.

    v1 is per-line, not per-flag — the reviewer sees the full set of flags on
    a line and decides the line as a unit. Per-flag granularity is a future
    enhancement.
    """

    APPROVE = "approve"
    REJECT = "reject"
    OVERRIDE = "override"


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
    unmatched. ``human_action`` is ``None`` until ``approval_node`` runs;
    after resume it carries the reviewer's per-line decision (approve /
    reject / override) so downstream consumers see one source of truth per
    line.
    """

    line_index: int
    matched_sku: str | None = None
    match_method: MatchMethod = MatchMethod.UNMATCHED
    confidence: float = 0.0
    flags: list[Exception_] = Field(default_factory=list)
    human_action: LineAction | None = None


class LineDecision(BaseModel):
    """One reviewer decision against a single ``MatchResult``.

    ``override_sku`` is required when ``action == OVERRIDE`` and forbidden
    otherwise — enforced by :meth:`_check_override_sku`. Caller pairs
    ``LineDecision`` to its target by ``line_index``, which must match the
    corresponding ``MatchResult.line_index``.
    """

    line_index: int
    action: LineAction
    override_sku: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_override_sku(self) -> LineDecision:
        if self.action == LineAction.OVERRIDE and not self.override_sku:
            raise ValueError("override_sku is required when action == 'override'")
        if self.action != LineAction.OVERRIDE and self.override_sku is not None:
            raise ValueError("override_sku may only be set when action == 'override'")
        return self


class HumanDecision(BaseModel):
    """Human-reviewer payload injected into state at the ``approval`` interrupt.

    ``line_decisions`` length must match ``state['matches']`` length and every
    ``LineDecision.line_index`` must correspond to a real ``MatchResult``.
    Cardinality validation lives in the API handler at the boundary, not here,
    so this model stays usable for partial-state inspection in tests.

    ``decided_at`` is set server-side when the HITL endpoint resumes the run
    — clients don't supply it.
    """

    reviewer: str
    decided_at: datetime
    line_decisions: list[LineDecision]
    overall_notes: str | None = None


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
    human_decision: HumanDecision
