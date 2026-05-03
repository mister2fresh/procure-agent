# notes — quote_precision_bearings_2026-04-22

`.expected.json` covers extracted-correctly only. Below is the downstream-eval rubric. Tests `.docx` ingestion + dense prose-MOQ + line-level constraint extraction.

## v1 extraction caveats

- **Source format is `.docx`**. `read_file` dispatches to `_read_docx`, which renders paragraphs as lines and tables as pipe-delimited rows in document order. Tests the docx pipeline end-to-end.
- **MOQ from prose** (lines 1-4): "minimum order quantity of 25 units per part number per order." Extracted as `min_order_qty: "25"` per line.
- **`valid_through: null`**: source prose says "valid for thirty (30) days from the date above." Golden does NOT derive `2026-05-22` per the prompt's "no deriving valid_through from issued_date" rule. The prose itself is preserved in `raw_notes`.
- **Carton-rounding rule** (lines 5-6): "ship in cartons of 4 units; quantities not divisible by 4 will be rounded up." No schema field for this. Lives in `raw_notes` for v1; could move to a structured `order_constraints` field later.

## exception-flagged-when-warranted

- **NCNR clause** (line 8 BLT-NK-1HP): non-cancellable, non-returnable once cut to bore size. Critical PO-flag — must be surfaced to buyer at PO release, not buried in raw_notes.
- **Bore-spec confirmation required** (line 8): supplier asks buyer to confirm 1-inch bore on PO acknowledgment. PO-acceptance flag.
- **Carton-rounding rule** (lines 5-6): structural rule for any future order; current quantities are exact and no rounding triggers, but the rule should attach to those SKUs in the master.
- **Sub-component reference** (line 7 CPL-LM-095): mentions a replacement spider SKU `CPL-LM-095-SPIDER` at $4.80/each, 5-unit min. Should appear in the matched-SKU catalog if agent expands sub-components.
- **Below-MOQ handling fee** ($75.00): contextual constraint for downstream PO validation if quantities ever drop.

## faithfulness (math / per-uom claims)

- Line totals: 75×8.42=631.50, 40×9.18=367.20, 30×11.85=355.50, 25×10.40=260.00, 12×28.75=345.00, 8×31.20=249.60, 6×54.80=328.80, 4×38.50=154.00 → subtotal 2,691.60 ✓
- Estimated freight ($84.50) is "actual at time of shipment" — non-binding.
- SC sales tax not applicable (out-of-state) — should not be added to PO total.

## completeness / HITL routing

- NCNR clause + bore-spec confirmation → both must surface to buyer before PO release. Otherwise quote is straightforward.

## inventory matching

- 8 industrial bearing/drive SKUs (B-62xx, B-63xx, PIL-UCP, FLG-UCFL, CPL, BLT). Stocky industrial-distribution domain — likely net-new vs. an SMB amendment-focused master.
