# notes — pacific-coast_PCA-26-1183

`.expected.json` covers extracted-correctly only (per-line currency, pack splits, raw_notes). Below is the downstream-eval rubric.

## v1 extraction caveats

- Per-line `currency` mix (CAD lines 1-4, 6, 8; USD lines 5, 7) tests the field's per-line scope (vs. document-level default).
- Non-canonical UoMs in source (`BAG`, `PAIL`, `BALE`, `ROLL`) collapse to `each` per the prompt's canonical set. Pack form preserved in `pack_size`. Worth deciding later whether the canonical set should grow.
- "PEAT-BALE-3.8" — the pack form `3.8 cu ft` is in the description (no separate pack column). Golden splits it into `pack_size: "3.8 cu ft"`. Tests whether the model strips description-embedded pack info.

## exception-flagged-when-warranted

- **Multi-currency**: agent must flag that the order is split-currency. Final invoice is CAD per supplier note; USD line items are quoted-currency only.
- **Split shipment**: line 5 (Mycorrhizal Inoculant) ships from Portland OR, not Vancouver. Either separate freight line or split-shipment flag.
- **Cross-border**: Vancouver BC → Reno NV. US customs/brokerage explicitly out of scope per supplier note. Compliance flag for buyer.

## faithfulness (math / per-uom claims)

- The "Estimated USD Total at 0.7320 CAD/USD: $10,212.41" is **reference-only**. Agent must not commit USD-converted totals to a PO. Binding numbers are CAD subtotals.
- Per-line CAD totals: 40×68.50=2740, 60×42.25=2535, 8×184=1472, 120×18.75=2250, 80×24.50=1960, 2×142=284 → CAD subtotal 11,241.00 ✓
- Per-line USD totals: 4×412=1648, 12×28=336 → USD subtotal 1,984.00 ✓

## completeness / HITL routing

- Cross-border shipment with customs implications, soft-FX estimate, split-shipment line — buyer should review before PO release.

## inventory matching

- 8 amendment/packaging SKUs: kelp meal, bone meal, gypsum, perlite, mycorrhizae, peat moss, pallets, strapping. Mixed agricultural-input + shipping-supply domain.
