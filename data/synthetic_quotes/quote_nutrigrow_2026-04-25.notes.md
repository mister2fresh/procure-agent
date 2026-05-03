# notes — quote_nutrigrow_2026-04-25

`.expected.json` covers extracted-correctly only. Below is the downstream-eval rubric. Headline edge case: substitution + buyer-decision-required → must NOT auto-process.

## v1 extraction caveats

- **Source format is `.docx`** — same pipeline as Precision Bearings.
- **Substitution captured natively** (line 1): `requested_sku: "KMEAL-50"` (from prose), `supplier_sku: "KMEAL-44"` (from table). The `requested_sku` ≠ `supplier_sku` field split is the schema's mechanism for substitution; this is the first fixture exercising it.
- **Substitution marker in description**: golden preserves the `(substituted — see notes)` parenthetical verbatim, so a downstream consumer reading description alone still sees the flag.
- **Pack-form split**: each line's pack form ("44 lb bag", "5 gallon pail", "50 lb bag") moves to `pack_size`; description is the rest verbatim.

## exception-flagged-when-warranted

- **Substitution requires buyer acceptance** — this is the canonical "do not auto-PO" case even though all other lines are clean. HITL trigger is the substitution itself, not field absence.
- **Four buyer-decision options** (checkboxes in source): accept-30 / accept-35 / hold-KMEAL-only / cancel-KMEAL-only. Agent must surface all four; downstream HITL UI presents them.
- **Time-bounded HITL**: "If we don't hear back by May 2, we'll assume the order is on hold." Should set a buyer-response deadline on the HITL ticket.
- **Cascading hold**: supplier holds the **entire order** (not just the substituted line) pending decision. Other-lines fulfillment is gated on the substitution decision.

## faithfulness (math / per-uom claims)

- Per-pound parity claim: $62.50 / 44 lb = $1.42045/lb vs. supplier-stated $1.420/lb. Drift is 4dp rounding only — claim holds at the stated 3dp precision.
- Original quote per-pound: $71.00 / 50 lb = $1.4200/lb. ✓
- "180 fewer pounds" claim: 1500 - 1320 = 180 ✓
- 35-bag alternative: 35 × 44 = 1,540 lb ✓; 35 × 62.50 = 2,187.50 ✓
- All math claims in the substitution section reconcile. Math-check passes.
- **Subtotal $5,699.00 excludes freight** ("Quoted at order confirmation"). Provisional total — must not propagate as binding.

## completeness / HITL routing

- Substitution + freight-pending-confirmation → HITL is mandatory. The substitution decision blocks all lines (per supplier note); even a "clean" PO of lines 2-6 cannot proceed without the buyer answering the substitution question.

## inventory matching

- 6 amendment SKUs (KMEAL-44 sub, FISH-EM, ROCK-PHOS, GREENS-BUCKWHEAT, AZOMITE, NEEM-MEAL). Same domain as Pacific Amendments and TerraGreen — overlap likely.
- The replacement (KMEAL-44 vs. KMEAL-50) tests whether the matching node can recognize a substitution as "same logical product, different packaging" rather than "new SKU."
