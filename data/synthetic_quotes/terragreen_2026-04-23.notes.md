# notes — terragreen_2026-04-23

`.expected.json` covers extracted-correctly only. Below is the downstream-eval rubric. This fixture is the v1 stress-test for the **completeness** rubric.

## v1 extraction caveats

- **Missing required-for-PO fields**: `supplier_ref`, `valid_through`, `payment_terms`, `shipping_terms` — none stated in source. Goldens emit `null` per "null beats guessing" rule.
- **Line 4 (GREENS-CC)**: `$2.85/lb` + qty `200`, no UoM column. Golden writes `uom: "lb"`, `unit_price: "2.85"`, `quantity: "200"` — i.e. UoM derived from the price modifier. This is mild inference; a strict reading would emit `null` UoM and force HITL. Worth re-evaluating: should agent extract the UoM from the price-modifier, or refuse and ask?
- **Line 5 (WORMC-1CY)**: UoM encoded in SKU stem (`1CY` = 1 cubic yard) but never stated as a unit. Golden defaults to `"each"` — over-conservative but schema-required. Real expected behavior is "ambiguous, ask buyer."
- **Line 3 (ALFM-50)**: leading-whitespace + missing `$` glyph on price (`   28.40   `). Golden = `"28.40"` — extraction must tolerate the formatting noise.

## exception-flagged-when-warranted

- **Soft pricing on biochar (line 6)**: "might be able to do better on price if you can wait" — must NOT propagate as firm price. Mark as soft-commit.
- **Soft lead time on worm castings (line 5)**: "vendor said maybe 2 weeks but could be sooner" — flag, not bindable.
- **Missing-fields catalog**: agent must enumerate which PO-required fields are absent.

## faithfulness (math / per-uom claims)

- No supplier-stated subtotal to reconcile against. If agent derives a subtotal, line 4's interpretation (qty-in-lb × $2.85) cascades into the total — wrong UoM = wrong total.

## completeness / HITL routing

- This fixture should route to HITL with the missing-fields list and the line-4/line-5 UoM ambiguity. It's the canonical "do not auto-PO" example.

## inventory matching

- 6 amendment SKUs (FEM, BLDM, ALFM, GREENS-CC, WORMC, BIOCH). Same domain as Pacific Amendments — overlap likely if both quotes are evaluated against a shared master.
