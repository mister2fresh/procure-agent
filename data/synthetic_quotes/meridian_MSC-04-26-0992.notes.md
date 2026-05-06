# notes — meridian_MSC-04-26-0992

`.expected.json` covers extracted-correctly only. Below is the downstream-eval rubric. Stacked-exceptions integration test.

## v1 extraction caveats

- **Tier cross-reference**: line 5 (EARPLG-FOAM) shows "see below" in the main table, with the actual ladder in a secondary table. Golden populates `unit_price` with the prose-stated applied tier ($0.24 at qty 1,000) plus all four tiers in `tier_prices`. Tests whether the model follows the cross-reference and applies the right tier.
- **MOQ from prose** (lines 1, 2, 6): captured in `min_order_qty`. Tests prose-based MOQ extraction (not column).
- **Line 4 (LUBE-WD40-1G)**: pack form "1 gallon" appears in the description and the UoM column is `GAL`. Golden uses `uom: "gal"` and leaves the description intact rather than splitting "1 gallon" into `pack_size`. Different from the `pack_size`-extraction pattern used elsewhere — worth deciding if this is the right call vs. always splitting.
- Non-canonical UoMs (`BOX`, `BALE`, `PR`) collapse to `each` per canonical set.

## exception-flagged-when-warranted

- **Missing freight**: "Freight quoted separately upon order confirmation" — `shipping_terms` covers FOB origin only; freight cost itself is absent. Completeness flag.
- **MOQ-aggregation rule** (lines 1-2 nitrile): "splitting an order across sizes does not aggregate toward MOQ" — context for downstream PO validation if buyer reduces a quantity.
- **Tier-firmness rule** (line 5): "Adjustments to ordered quantity will be re-priced at the applicable tier" — context for PO validation if buyer adjusts qty.

## faithfulness (math / per-uom claims)

- Line totals: 24×11.40=273.60, 36×11.40=410.40, 6×42=252, 12×38.50=462, 1000×0.24=240, 20×74.25=1485, 4×58=232 → 3,355.00 ✓
- "Quote total: $3,643.53" = subtotal $3,355.00 + AZ tax 8.6% ($288.53). **Total is incomplete by stated terms** — excludes freight. Agent must not present this as a binding total.

## completeness / HITL routing

- Missing freight + MOQ-aggregation rule + tier-firmness rule → flag for buyer review of binding cost before PO release.

## inventory matching

- 7 SKUs across PPE (gloves, earplugs), janitorial (rags, lubricant), agricultural (kelp meal, twine). Mixed cross-domain — good test for whether matching against a single inventory master can resolve a multi-domain quote.
