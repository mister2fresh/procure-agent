# notes — quote_acme_fasteners_2026-04-22

**No `.expected.json` golden yet.** Deferred — see "v1 extraction caveats" below.

## v1 extraction caveats

- **Source is a price list, not a buy.** Multiple tier rows per SKU; no order quantity stated. Current `Quote.line_items[].quantity` is non-null `Decimal`, so v1 schema can't represent this fixture without inventing a quoted quantity. Resolution path is to add a `quote_type` discriminator (`"price_list" | "rfq_response" | ...`) or relax `quantity` to `Optional`. Until then, this fixture stays in the corpus as a known-not-yet-scorable case.
- **Tier rows: collapse vs. multi-line.** Each SKU appears 3-4 times with non-overlapping `Tier Min Qty`/`Tier Max Qty` ranges. Top tier has empty `Tier Max Qty` (open-ended). Once schema lands, expected behavior is one logical line per SKU with a populated `tier_prices` ladder and `quantity: null`.
- **3-decimal unit prices** (e.g. `$0.142`, `$0.094`). Schema's 2dp `Price` quantizer dropped these; that bug is fixed (validator removed). Goldens written post-fix preserve source precision.

## exception-flagged-when-warranted

- Quote-type classification: agent must recognize this as a price list and route to a price-update flow, not draft a PO from it.

## faithfulness (math / per-uom claims)

- Steel-surcharge clause: "Steel surcharges may apply on orders placed after 2026-05-22." Conditional pricing — must not propagate as firm.
- Sales tax note (8.0% Ohio destinations) is conditional on ship-to.

## completeness / HITL routing

- Price-list with no order quantity → routes to buyer to specify desired quantities, not auto-PO.

## inventory matching

- 6 fastener SKUs (HCS, FNW, LWS, HXN, SHC, CRW). Industrial-fastener domain — likely net-new SKUs vs. an SMB master.
