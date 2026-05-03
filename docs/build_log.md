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

Second session same day. Scaffolded `src/procure_agent/agent.py` with the from-scratch
ReAct loop infrastructure: `Anthropic` client, `MODEL = claude-sonnet-4-6`, `read_file`
tool (schema + path-scoped handler with traversal guard targeting `data/synthetic_quotes/`),
and the `run()` loop itself. System prompt and `__main__` entry point are the user's
to write — see TODO markers at `agent.py:84` and `agent.py:125`.

Reasoning notes worth keeping:
- The minimal SDK loop is the right shape for Day 1. LangGraph translation, HITL
  pause/resume, and Postgres checkpointing are Day 3+ concerns and explicitly out of
  scope for the from-scratch loop. Surfacing those concerns prematurely added confusion
  that had to be walked back; recalibrate to the day's scope first when the user asks
  "will this work?"
- `read_file` is path-scoped via `Path.resolve()` + `QUOTES_DIR not in target.parents`
  rather than a string `startswith` check. Keeps symlinks and `..` segments honest.
- Tool result `content` is `json.dumps(...)`'d so dict/list returns survive intact rather
  than getting `repr()`'d. Trivial now (`read_file` returns str), but the convention
  carries forward to Day 3 tools that return structured data.

No live run yet, so no failure mode observed. That's tomorrow's first task.

Third session same day. System prompt + few-shot scaffolding landed; loop entry point still TODO.

Schema deltas:
- `QuoteLineItem.pack_size: str | None` — pack info ("4 oz", "case of 12") is a structured field, not a description suffix. Real procurement primitive: needed for matching, ordering, cost-per-unit calcs.
- `Quote.customer_ref: str | None` — persistent customer identifier (Customer #, Account #, customer code). The supplier's stable ID for the buyer in their system; same value across every quote. Caught mid-cleanup that this is distinct from per-transaction refs (RFQ #, PO #) — the original prompt collapsed them. Per-transaction refs are dropped at this stage; they come back as a separate field when there's a use case.
- `TierPrice.min_qty`: `int` → `Decimal`. Matches the "all quantity-shaped fields are Decimal-as-string" convention so prompt and schema agree on serialization.
- `QuoteLineItem.currency`: `str = "USD"` → `str | None = None`. Default moves downstream so the model emits explicit `null` when the source doesn't state a currency, and the schema doesn't silently fill in.

Goldens reconciled against the new rules:
- All four fixtures (3 eval + 1 demo) get `pack_size`.
- Demo fixture exercises `customer_ref` ("Customer #: 2F-104") alongside a per-transaction "Buyer Ref: RFQ-8842" so the few-shot teaches both at once: capture the customer code, drop the RFQ.
- Eval fixtures 01/02/03 have no customer code in their source text → `customer_ref: null`. That exercises the "null when not stated" path.
- Currency rule: document-level annotations (column header "Unit Price (USD)", subtotal "$450 USD") count as stated; bare `$` symbol does not. Forces fixture 02's currency to `null` (its source has only `$300/kg`).
- Fixture 03 description splits: "Microbe Complete" + `pack_size: "4 oz"`, instead of folding pack into the description string.

Few-shot example pattern: held-out demo fixture lives in `data/prompt_examples/`, strictly separate from the eval corpus (`data/synthetic_quotes/`) so the model is never scored on something it's literally been shown. Loader (`src/procure_agent/prompts.py`) reads input + golden at import time, re-serializes the JSON via `json.dumps(..., indent=2)` to canonicalize formatting drift, and substitutes into a template. `SYSTEM` becomes a module-level constant — agent imports it the same way it imported the inline string.

Untested at runtime. The prompt has rules and a demo, the loader produces a valid string, all goldens validate against the updated schema — but Sonnet 4.6 has never seen any of it. The strict-JSON output contract, the symbol-only-currency rule, the customer-ref-vs-RFQ discrimination, and the demo's anchoring effect all need to survive contact with the model. First live run + observations land in the next session along with the `__main__` driver.

Fourth session same day. Reopened the per-transaction-ref decision from earlier today before more was built on top.

Schema delta:
- `Quote.rfq_ref: str | None` — buyer-side transaction reference this quote responds to (RFQ #, "Buyer Ref:", "Your Ref:", "Buyer Reference:"). Distinct from `customer_ref` (the persistent customer ID).

The earlier session's plan was to call this field `buyer_ref` if/when it came back. That name was wrong: `buyer_ref` reads as a synonym for `customer_ref` — both name "the buyer/customer's identifier from the supplier's POV." The per-transaction concept needs a distinct name that signals transaction-specificity. Settled on per-document-type naming: `rfq_ref` on Quote; PO and Invoice models, when they arrive, will carry `po_ref` / `invoice_ref`. Same pattern as `supplier_ref` already being document-type-scoped. A downstream doc can also carry an upstream ref (a PO might carry `rfq_ref` linking back to the originating RFQ) without overloading a single polymorphic field.

Cost of doing it now vs. deferring: every fixture already has the data in source text, the prompt was already spending a paragraph telling the model to throw it away, and post-Day-3 (Postgres) it would have meant a column migration. ~30 min of mechanical edits today.

Goldens reconciled:
- Demo `marian_demo` → `rfq_ref: "RFQ-8842"` (the line that was previously dropped).
- Eval 01/02 → `rfq_ref: "RFQ-1142"` (header line on 01; subject line on the prose-email 02).
- Eval 03 → `rfq_ref: "RFQ-1143"` ("Buyer Reference:" label variant).

Prompt updates: `customer_ref` bullet's "dropped entirely" clause flipped to "those go in `rfq_ref`, not here"; new `rfq_ref` bullet covers the label variants and explicitly notes prose-inline appearance (email subject) so fixture 02's RFQ extraction has a directive.

Still untested at runtime. Adds another extraction surface to the eval set; whether the model picks up the RFQ from a prose subject line vs. only from header-shaped lines is an unknown.

Fifth session same day. `__main__` driver landed; loop is now end-to-end runnable.

Driver shape: `sys.argv[1]` (default `01_aloe_corp_clean_tabular.txt`) → `run(...)` → `_extract_json_block` → `Quote.model_validate_json` → `model_dump_json(indent=2)` to stdout. Skipped argparse — one positional arg doesn't earn a parser. `_extract_json_block` filters text blocks, regex-matches the fenced ```json``` from the output contract, and raises `ValueError` with the full response inlined when no block is found. Validation is fail-fast on purpose: each failure mode (bad fixture name, no JSON block, wrong shape, max_turns) raises a distinct exception type so the eventual eval harness can switch on them.

Prompt change: `read_file` failure clause flipped from "emit a JSON object with all fields null" to "emit a single line `ERROR: <short description>` and stop". The all-null instruction would've failed `Quote` validation anyway (`supplier_name`, `line_items`, etc. are non-optional). Considered relaxing the schema to allow null on those fields — rejected. The schema mirrors what lands in `quotes.line_items` JSONB on Day 2; loosening domain types to model a *tool failure* would force every downstream consumer to null-check fields that are genuinely required for a real quote. Tool failures are "no extraction happened," not "extraction with missing fields." The `ERROR:` line short-circuits to `_extract_json_block`'s ValueError path and surfaces the model's description verbatim. If the eval harness later wants structured failure, add an `ExtractionResult = Quote | ExtractionError` union — but only when actually needed.

Live run pending — driver is wired and the API key is in place; first run + observations land in the next session.

Sixth session same day. First live runs of all three eval fixtures + design-principle clarification + reconciliation of goldens to match.

End-to-end loop worked on first try. No infrastructure surprises: `.env` loaded, two-turn extraction on every fixture (one `read_file` tool call, one fenced-JSON emission), `Quote.model_validate_json` accepted every output, `_extract_json_block` regex matched. The infra-design choices from earlier sessions held — fail-fast validation, ERROR-line failure path, path-scoped tool — none needed adjusting.

Output-vs-golden diff revealed the goldens were wrong, not the model. Across the three fixtures:
- **Fixture 01**: model returned `"ALOE CORP."`, golden had `"Aloe Corp."`. Source header is `ALOE CORP. — QUOTE` — model was verbatim, golden had silently title-cased.
- **Fixture 02**: model returned `"food-grade aloe vera extract"` (verbatim from this email), golden had `"Aloe Vera Extract, food grade"` (lifted from fixture 01's tabular phrasing). Goldens were inconsistent with their own source. Same fixture: model returned `"FOB our facility in Mesa"` verbatim, golden had paraphrased to `"FOB Mesa facility"`. Same fixture: `unit_price` model returned `"300"` from `$300/kg`, golden had `"300.00"` — the only delta where the *golden* was right.
- **Fixture 03**: same supplier-name casing issue as 01.

Design principle that fell out: **supplier-facing surface fields extract verbatim; canonical normalization is a downstream join.** Specifically:
- Verbatim: `supplier_name`, `description`, `payment_terms`, `shipping_terms`, `raw_notes`. Capture casing, punctuation, phrasing exactly as the source has them.
- Canonical: `uom` (lowercase token from a fixed set), `requested_sku`/`supplier_sku` (uppercase), dates (ISO 8601). These are tokens with a finite valid alphabet — the schema enforces canonical form.
- Decimal money fields: canonicalize at the **schema layer**, not prompt. Added `Price = Annotated[Decimal, AfterValidator(_to_2dp)]` and applied to both `unit_price` fields. `Decimal("300").quantize(Decimal("0.01"))` → `Decimal("300.00")` regardless of what the model emits. Prompt-level "always emit 2dp" rules drift; field validators don't.

The earlier "Extraction canonicalizes, source preserves itself" framing in this log overstated the canonicalization scope. It canonicalizes structured tokens only — not prose. Title-casing supplier names, paraphrasing terms, normalizing descriptions across documents are all *matching* concerns: `UPPER(supplier_name) = UPPER(?)` on the join, fuzzy supplier-master lookup, SKU canonicalization step. Doing those at extraction time tangles the eval (you can't tell whether a delta is an extraction failure or a normalization rule firing) and over-promises (the model can't reliably normalize without seeing the master tables).

Prompt changes: `supplier_name` rule strengthened to "verbatim from the source — preserve casing and punctuation. ALL CAPS letterheads stay ALL CAPS; stylized forms (`3M`, `e.l.f.`) are not normalized." `raw_notes` rule got KEEP/SKIP categories: KEEP signature contact info, soft asks, conditional pricing notes, supplier commentary; SKIP greetings, sign-offs, pure restatements of structured fields, email headers when their content is captured elsewhere. Spans joined with `\n\n` to preserve source order.

Goldens reconciled to match:
- 01/03 `supplier_name` → ALL CAPS verbatim.
- 02 `description` → `"food-grade aloe vera extract"` (matches its own source).
- 02 `shipping_terms` → `"FOB our facility in Mesa"` verbatim.
- 02 `raw_notes` → soft close + signature, KEEP/SKIP applied: `"Let me know if you want me to lock it in and I'll send the PO confirmation.\n\nSarah Chen\nAloe Corp.\n(480) 555-0114"`.
- 02 `unit_price` stayed `"300.00"` — Pydantic `Price` validator now pads on input.

Re-run results: 3/3 byte-identical to goldens, modulo one whitespace char on fixture 02 (`\n` vs `\n\n` between the soft close and signature). Model didn't fully comply with the literal `\n\n` instruction in the prompt. Worth logging as a failure mode: **prose-format directives in the system prompt have looser compliance than structured-field directives.** Token-shape rules (lowercase UoM, ISO dates, uppercase SKU) survive perfectly; whitespace-shape rules don't. Mitigation deferred — eval harness should normalize internal whitespace on prose fields before comparing rather than chase prompt-token spend on a cosmetic fidelity loss.

Things that worked on first run, worth noting because they could have failed:
- Nonstandard column headers in fixture 03 (`Item Code`, `Order Qty`, `Price Each`, `MOQ`) all mapped to the right schema fields with no per-fixture coaching.
- `customer_ref` vs `rfq_ref` discrimination held on all three fixtures, including the prose-email case where the RFQ is in the email subject line.
- Currency rule held: `USD` extracted when an explicit ISO code appears (`Unit Price (USD)`, `$450 USD`); `null` when only the `$` symbol appears (`$300/kg`). Same model behavior across three different surface forms — the prompt rule generalized correctly.
- `pack_size` split from `description` on fixture 03 (`"Microbe Complete"` + `pack_size: "4 oz"`) — no description-suffix folding.
- `min_order_qty` stripped units (`"30 units"` → `"30"`).

Two days of design work paid off in one session of clean runs. Loop is solid against the small corpus. Next: expand corpus to ~10-15 fixtures (tier pricing, multi-line, missing-field cases), wire the pytest eval harness with field-aware comparators, then translate to LangGraph.
