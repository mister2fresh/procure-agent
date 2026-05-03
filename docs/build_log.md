# build log

Real-time observations through the 7-day build. Append-only. What worked, what broke, failure-mode notes, snippets of failed runs. Day 6 README's production-failure section gets sourced from here.

## 2026-05-03 — Day 1

Pre-loop session. Designed the post-extraction quote schema (`src/procure_agent/schemas.py`)
and authored three starter fixtures in `data/synthetic_quotes/` to point the ReAct loop at:

- `01_aloe_corp_clean_tabular` — baseline tabular, single line item (AL101 / 50 kg / $300/kg)
- `02_aloe_corp_prose_email` — same line item wrapped in email prose (extraction stress test)
- `03_rootwise_nonstandard_columns` — Rootwise / RMC101 / 30 each / $15 / MOQ 30, with
  non-standard column headers ("Item Code", "Pack")

Schema decisions worth remembering:
- **Extraction canonicalizes, source preserves itself.** UoM emits lowercase canonical tokens
  (`kg`, `lb`, `each`, etc.), SKUs uppercase, dates ISO. Faithfulness check is semantic, not
  literal, so we don't preserve surface casing in the structured output.
- Fixture convention: each `*.txt` has a paired `*.expected.json` golden file. Same shape will
  back `quotes.line_items` JSONB on Day 2 and the Day 4 eval harness.
- Schema fields that landed beyond the minimal core: `payment_terms`, `shipping_terms`,
  `min_order_qty`. Suppliers in real procurement always state these; cheaper to model now
  than retrofit Day 3.
- `requested_sku` and `supplier_sku` both nullable. Substitution case = both populated and ≠.

ReAct loop deferred to next session. Anthropic API key + LangSmith account need to land in
`.env` before the loop runs.
