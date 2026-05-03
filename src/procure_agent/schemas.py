"""Domain schemas for procure-agent.

Mirrors the eventual Supabase tables landing on Day 2. The post-extraction `Quote` shape
is what the agent's extraction step produces, what `quotes.line_items` JSONB stores, and
what each fixture's `.expected.json` golden file conforms to for the eval harness.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class TierPrice(BaseModel):
    """A quantity break in tier pricing."""

    min_qty: Decimal = Field(..., description="Minimum quantity to qualify for this tier.")
    unit_price: Decimal


class QuoteLineItem(BaseModel):
    """One line on a supplier quote, post-extraction.

    Captures what the supplier said, not the result of matching it against the product
    master. Match results (matched_sku, price_variance_flag, etc.) live on a separate
    reconciled type defined on Day 3 when the matching node exists.
    """

    requested_sku: str | None = Field(
        None,
        description="SKU the buyer asked for. None if the quote is unsolicited.",
    )
    supplier_sku: str | None = Field(
        None,
        description="SKU the supplier offered. None if the quote is prose-only or omits one.",
    )
    description: str
    pack_size: str | None = Field(
        None,
        description="Unit pack as written by the supplier ('4 oz', 'case of 12', '1 gal jug').",
    )
    quantity: Decimal
    uom: str = Field(
        ...,
        description="Canonical UoM, lowercase ('kg', 'lb', 'oz', 'gal', 'l', 'each', 'case').",
    )
    unit_price: Decimal
    currency: str | None = Field(
        None,
        description="ISO currency code as stated by the document (e.g. 'USD'). None when only a "
        "bare symbol like '$' is present; downstream applies the default.",
    )
    tier_prices: list[TierPrice] = Field(default_factory=list)
    min_order_qty: Decimal | None = Field(
        None, description="Supplier-stated minimum order quantity for this line item, if any."
    )
    notes: str | None = None


class Quote(BaseModel):
    """A supplier quote, post-extraction. Shape mirrors `quotes.line_items` JSONB in Postgres."""

    supplier_name: str
    supplier_ref: str | None = Field(
        None, description="Quote number or reference issued by the supplier."
    )
    customer_ref: str | None = Field(
        None,
        description="Persistent customer identifier — the supplier's stable ID for this buyer "
        "in their system (Customer #, Account #, customer code, Bill-To ID). Same value across "
        "every quote that supplier sends. Distinct from `rfq_ref`, which is per-transaction.",
    )
    rfq_ref: str | None = Field(
        None,
        description="Buyer-side transaction reference this quote responds to — the RFQ # "
        "(or 'Buyer Ref:', 'Your Ref:') the buyer issued and the supplier echoed back. "
        "Per-transaction; changes every quote. Distinct from `customer_ref`.",
    )
    issued_date: date | None = None
    valid_through: date | None = None
    line_items: list[QuoteLineItem]
    payment_terms: str | None = Field(
        None, description="Payment terms as stated ('Net 30', 'COD', '2/10 net 30')."
    )
    shipping_terms: str | None = Field(
        None, description="Shipping/incoterms as stated ('FOB origin', 'FOB Portland, OR', 'CIF')."
    )
    raw_notes: str | None = Field(
        None, description="Prose framing or commentary from the source document."
    )
