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

## 2026-05-03 — Day 1, evening (corpus expansion batch 1)

User dropped 6 new fixtures covering tier pricing, multi-currency, MOQ-in-prose, SKU substitution, missing-required-fields, and stacked exceptions. Format expansion: `.csv`, `.docx`, `.md` alongside the original `.txt`.

**`read_file` tool gained docx support.** Added `python-docx`. New `_read_docx` helper walks the body in document order — paragraphs as lines, tables as pipe-delimited rows. Dispatches on suffix in `read_file`; `.txt`/`.csv`/`.md` still pass through `read_text()` unchanged. Smoke-tested on both docx fixtures (Precision Bearings, NutriGrow); table rows render cleanly and document-order interleaving holds.

**Schema bug fixed: 2dp price quantizer was lossy.** The `Price = Annotated[Decimal, AfterValidator(_to_2dp)]` validator added during the verbatim-extraction pass was wrong for high-precision quotes. Acme's fastener pricing is at 3 decimals (`$0.142`); `Decimal("0.142").quantize(Decimal("0.01"))` truncates to `0.14`, breaking line-total reconciliation against subtotals.

Resolution: dropped the validator entirely. `unit_price` and `tier_prices[].unit_price` are now plain `Decimal`. Source precision survives end-to-end. The "compare 300 vs 300.00 as the same value" responsibility moves to the eval harness comparator (numeric Decimal equality), which is where it belongs anyway. All 9 existing + new goldens validate post-fix, so the change is non-breaking.

Lesson worth keeping: **schema-layer normalization is brittle when the domain has wider precision than the canonical form assumes.** The prompt already commits the model to source-precision verbatim; the schema validator was overriding that — solving a real problem (golden-comparison stability) at the wrong layer. Comparators belong in the harness; the schema's job is structure, not display.

**Goldens scaffolded for 5 of 6.** Acme deferred — it's a price list with no order quantity stated, and the schema requires non-null `quantity`. Three resolution paths possible (synthesize a fake quoted qty, add a `quote_type` discriminator, or ERROR-on-extract). User chose to keep the fixture and skip the golden until v1.x adds the schema branch — accepts that we lose one fixture's worth of eval signal in exchange for not inventing data.

**Sidecar `.notes.md` per fixture** captures the downstream-eval rubric items the v1 schema can't carry: NCNR clauses, carton-rounding rules, substitution-acceptance routing, FX-estimate-is-reference-only, missing-freight completeness flags, faithfulness math reconciliations. These become eval targets once reconciliation/HITL/PO-generation nodes land in step 3 (LangGraph translation). Format converged on 5 sections: v1 extraction caveats, exception-flagged-when-warranted, faithfulness, completeness/HITL routing, inventory matching.

**Design questions surfaced for later:**
- TerraGreen line `GREENS-CC` ($2.85/lb, qty 200, no UoM column): golden derives `uom: "lb"` from the price modifier. Strict reading would emit `null` UoM and force HITL. Currently mild inference; need to decide whether the prompt should be tightened or this is acceptable extraction behavior.
- TerraGreen line `WORMC-1CY` (UoM in SKU stem, `1CY` = 1 cubic yard): golden defaults to `"each"` since the schema requires non-null `uom`. Same class of problem — the canonical UoM set is too narrow for this domain.
- Meridian line `LUBE-WD40-1G`: golden uses `uom: "gal"` and leaves "1 gallon" in description rather than splitting to `pack_size`. Different from the consistent pack-split applied elsewhere. The prompt's pack-split rule kicks in only when there's a separate pack form vs. UoM; here they collide.
- The canonical UoM set (`{kg, lb, oz, gal, l, each, case}`) is forcing too many real-world UoMs (`BAG`, `PAIL`, `BALE`, `ROLL`, `BOX`, `PR`) to collapse to `each`. Fine for v1 but loses a lot of detail.

No agent runs against the new fixtures yet — saved for next session. Goldens are aspirational targets per the prompt's strict reading; harness-driven divergence will surface real signal once step 2 wires up.

Next: pull next batch of fixtures, then go wide on agent-run testing.

## 2026-05-03 — Day 1, late evening (corpus expansion batch 2 goldens)

User dropped 6 more fixtures targeted at extraction edge cases — refs, pack-size variations, date formats, multi-row qty breaks, lead-time prose, and a revised-quote ref trap. Same session wrote `.expected.json` for all 6. No `.notes.md` sidecars this batch — fixtures are narrower and the wrinkles are encoded in the goldens directly.

**Convention reinforcement (batch 1 → batch 2 carry-over):**
- Non-canonical UoM tokens (`bag`, `bale`, `pail`, `drum`, `tote`) → `uom: "each"` (or `"case"` when literal); pack form preserved in `pack_size`.
- Bare `$` symbol → `currency: null`; explicit ISO code → that code.
- `customer_ref` (persistent customer ID) and `rfq_ref` (per-transaction) stay separate even when both restate in a footer reminder line.

**Pack-size placement rule pinned:** UoM-column word (`bag`/`bale`/`drum`) goes into `pack_size` *only when not already in description*. Pacific amendments' `PEAT-BALE-3.8` left "bale" in description; fixture 7's `PM-C-2.2` pulled "bale" into `pack_size: "2.2 cu ft bale"` because the description didn't carry it. User validated as provisional. Saved as feedback memory.

**Judgment calls, batch-2-specific:**
- Fixture 9 (Northstar): slash-format date `05/04/2026` only appears in prose, kept verbatim in `raw_notes`. Structured `issued_date` / `valid_through` come from unambiguous `dd-MMM-yyyy` and `Month DD, YYYY` formats elsewhere in the email. Locale ambiguity not pinned by the golden — it's a downstream-normalization concern.
- Fixture 10 (Continental Ingredients qty break): same SKU appearing in two rows at different qty/price collapses to one line item with `tier_prices` populated. `quantity` = larger tier qty, `unit_price` = price at that tier. Cottonseed (single-row) gets empty `tier_prices`.
- Fixture 12 (Riverway revised quote): `supplier_ref` = live ref `"RW-2026-0419-R2"` (not the prominent old ref). Item 2 qty = 12; the parenthetical "(was qty 8 in original)" did not bleed into the line item. Supersession context lives in `raw_notes`.
- Fixture 11 (Harbor): per-line lead-time status went into `notes` per item (`"in stock — can ship today"`, `"8-10 week lead time — must commit by 5/15"`, etc.). `valid_through` derived from "Valid: 30 days from quote date" → 2026-05-29.

**Caught one near-miss:** initial fixture 7 draft was sanity-checked by user before write — flagged me to look at lines 55-56. Nothing wrong there in the end (BM-50 unit_price 34.25 verbatim from source, currency null per bare-$ convention). Worth the pause anyway; verbatim self-check beats trusting parallel-write output.

No agent runs yet against batch 2 either. Next: agent test pass across full corpus (batches 1 + 2), then pytest harness.

## 2026-05-03 — Day 1, late evening (first agent pass on batch 2 corpus)

First end-to-end agent runs on the batch-2 fixtures. Started 0/6 byte-matching the goldens; ended with 1 clean match (fixture 10) and the rest narrowed to a single class of remaining drift (signature stripping). Four prompt rules added en route.

**Drift buckets surfaced on the first pass:**
- **Schema/shape misses.** Fixture 10 (qty-break multirow) collapsed three CSV rows into three line items with the lowest tier as headline and one tier hoisted into `tier_prices`. Fixture 11 emitted `valid_through: null` despite source saying "Valid: 30 days from quote date".
- **Convention drift.** `currency: "USD"` over-inferred where source had only `$`; `pack_size` dropped UoM-column nouns (`"50 lb"` instead of `"50 lb bag"`); `uom: "case"` for a `bag` UoM column where the canonical set has no entry.
- **Prose hygiene.** raw_notes kept signatures and admin metadata (`Salesperson: K. Tomlinson`); `\n\n` separator compliance loose; `[ADDED]` verbatim vs golden's paraphrase.
- **Edge cases.** Pack info bleeding into description; parenthetical pack reordering (`"drum (55 gal)"` vs golden's `"55 gal drum"`).

**Four conventions decided this session and encoded in the prompt:**

1. **valid_through derivation reversed.** Old prompt rule: never derive from issued_date. New rule: derive when source states explicit math (`"valid 30 days from quote date"`, `"expires 2 weeks from issue"`); strict-null only when source is silent or vague (`TBD`/`upon request`). Triggered by fixture 11 where the golden encoded the derived date and the prompt forbade it — golden was right, prompt was wrong.
2. **Multi-row same-SKU is not a tier table.** Original golden 10 collapsed same-SKU rows into one line item with `tier_prices` populated and the top-tier qty as headline. Considered summing-as-headline (user's first instinct) — rejected because differing prices on same-SKU rows is the signature of supplier tier offers, not buyer split-lot orders, and summing invents a buyer commitment that isn't in the source. Settled rule: each CSV/table row is its own `QuoteLineItem`; `tier_prices` only populates when a single row carries an inline tier-break statement. Faithful row-by-row extraction; downstream decides duplicates. Golden 10 rewritten from 3 line items to 5.
3. **pack_size UoM-column rule moved from memory into the prompt.** When a CSV/table has a separate UoM column with a packaging noun (`bag`, `bale`, `pail`, `drum`, `tote`), fold it into `pack_size` only if not already in the description. Rule was previously only in memory (batch 2 review); model didn't have it, so output drifted across fixtures 07, 08, 10. Same edit also tightened the `uom` rule to enumerate the packaging nouns that route to `pack_size + uom: each`, since "what's a canonical UoM" was implicit.
4. **Currency: do not default to USD.** Existing rule said bare `$` is insufficient, but the model still defaulted to USD on fixture 07. Tightened with explicit "do not default to USD even if the supplier appears to be US-based."

**Re-run results:** fixture 10 byte-clean (was 13 diffs). Fixtures 07/08/09/11 down to 1-2 diffs each, almost entirely raw_notes signature retention. Fixture 12 still drifts on `[ADDED]` verbatim and revision-prose paraphrase.

**Single biggest source of remaining drift: signature keep/skip contradiction.** Current `raw_notes` KEEP rule says signature contact info (name, title, email, phone) belongs in raw_notes. All four affected goldens (07, 09, 11, 12) strip them. Either the rule flips (SKIP signatures) or the goldens get rewritten — same flavor of issue applies to header admin metadata (`Salesperson:`, `Freight: TBD`). Deferred for next session.

**Other minor drift left on the table:**
- Fixture 08: `pack_size: "drum (55 gal)"` (verbatim from CSV column) vs golden's `"55 gal drum"` (reordered). Prompt says "as written"; golden is normalized. Worth flipping one direction next pass.
- Fixture 09: `shipping_terms` over-split — agent put `ex-warehouse Tacoma` in raw_notes alone, golden combined as `"ex-warehouse Tacoma; freight prepay & add"`.
- Fixture 12: source-prose normalization (`**` markdown stripping, `your`→`buyer`, `[ADDED]`→`added in revision`) — agent preserves verbatim per existing rule.

**Sequence lesson worth keeping:** running the agent before harness wiring is high-signal-per-API-call. ~12 calls (two passes of 6 fixtures) surfaced four prompt rules + a golden rewrite + the next-session-blocker (signature decision). Same drift would have been masked by a harness-only run reporting per-field hit rates, because half the issues were prompt/golden contradictions where neither side was clearly correct.

**Next:** settle signature keep/skip; either flip the prompt or rewrite the four goldens. Then sweep batch 1 (remaining ~6 fixtures) for the same drift classes. Harness wiring after.

## 2026-05-03 — Day 1, late evening (signature keep/skip settled)

Decision: **KEEP signatures verbatim in `raw_notes`** (current prompt rule stands). No prompt edit, no golden rewrites. Goldens 07/09/11/12 will get signature blocks reinstated when their next pass runs — defer that mechanical fix to the batch-1 sweep session so it lands as one batch of golden updates rather than scattered.

Why not flip the prompt: signatures are genuinely structured supplier-contact data (name, title, email, phone) — exactly the schema supplier onboarding (handoff §week 3) needs. Designing a `Contact` model now expands extraction scope mid-build for a workflow that's two weeks out, on thin signal (signature shape varies a lot — "Thanks, Bob" through full block). Raw_notes loses no information; the structured lift is a one-prompt-change away once onboarding lands and we've seen 20+ signature variants.

Trigger for revisit: handoff doc §week 3 (Supplier onboarding) annotated with "extract signatures into structured `Contact` here" so the next-workflow-startup pass picks it up automatically.

Header admin metadata (`Salesperson:`, `Freight: TBD`) is the same shape of question but separate — those aren't signature data, they're document-header attribution. Will fall out of the batch-1 sweep when fresh fixtures with similar headers either get goldens that include them or push back on the prompt rule. No standalone decision needed yet.

## 2026-05-03 — Day 1, late evening (batch-1 sweep)

Eight batch-1 fixtures end-to-end (1/2/3 + Pacific / TerraGreen / Meridian / Precision / NutriGrow). Two passes, ~14 API calls. Three convention calls landed (rule A on per-line `notes` scope, rule B reframed for pack_size/UoM independence, rule C on header admin metadata kept). Four golden updates and signature reinstatement in 07/09/11/12.

**Conventions decided this session:**

1. **Rule A — `line.notes` scope.** `line.notes` populates ONLY when the source structurally attaches commentary to a single line: per-line column (`Status: in stock`), sub-bullet under that line, `Lead:` field. Global notes-section prose that *references* line numbers (`"Line 5 ships separately"`, `"MOQ for Lines 1 and 2 is 20"`) stays in `raw_notes` verbatim. Goldens 07/09/Pacific/TerraGreen/Meridian/Precision already match this; Harbor (golden 11) is the precedent for the "structurally per-line" case (Status field under each item).

2. **Rule B — pack_size/UoM independence.** The first cut had a too-broad "canonical UoM = no pack split" carve-out. User flagged the 55-gal-drum-charged-per-gallon counterexample. Reframed: pack_size is the *pack constraint* (the unit you must order in); UoM is *how it is charged*. They are independent and can coexist (`pack_size: "55-gal drum"`, `uom: "gal"`). Triggers, in priority: (1) packaging noun in description → lift verbatim pack phrase to `pack_size`, strip from description; (2) unit-pack form ("case of 12") → lift verbatim; (3) packaging-noun UoM column + size in description and no description noun → combine ("50 lb" + col=BAG → "50 lb bag"). When none fire (canonical UoM column + measurement-only description, no packaging noun, e.g. "1 gallon" + uom GAL), `pack_size` stays null.

3. **Rule C — header admin metadata.** `Salesperson:`, `Freight: TBD`, `Lead Time:`, `GST/HST:` and similar header attribution fields stay in `raw_notes` verbatim, same disposition as signatures. Goldens 07 and Pacific updated to include them. Revisit if/when downstream onboarding workflow wants structured fields for any of them.

**Mechanical golden updates beyond conventions:**
- Golden 02 `unit_price`: `"300.00"` → `"300"` (preserve source precision; the schema-layer 2dp validator was dropped during batch-1 fixture expansion when Acme's 3-decimal pricing surfaced, but golden 02 still had the padded form).
- Golden Precision `valid_through`: `null` → `"2026-05-22"` (per the batch-2 derive-on-explicit-math rule applied to "valid for thirty (30) days from the date above").
- Golden Pacific STRAP-PP-58: `pack_size: null` → `"5/8\" x 9000 ft roll"`, description trimmed.
- Golden Pacific PEAT-BALE-3.8: `pack_size "3.8 cu ft"` → `"compressed bale, 3.8 cu ft"` (verbatim source order; full pack phrase lifted, description reduced to product name).
- Goldens 07/09/11/12: signature blocks (and admin metadata for 07) reinstated in `raw_notes` per the now-settled signature-KEEP rule.

**Round 1 vs round 2 results.**

Round 1 (initial sweep, before prompt edits): 1/8 byte-clean (01_aloe). 02_aloe and 03_rootwise had the existing diffs from prior session. Pacific/TerraGreen/Meridian/Precision/NutriGrow each had multi-field drift dominated by per-line `notes` lifting from global notes prose, raw_notes paraphrasing, and currency over-defaulting.

Round 2 (after prompt + golden edits): 2/8 byte-clean (01_aloe, 03_rootwise). 02_aloe down to 2 cosmetic diffs (`food-grade`/`Food-grade` source-casing miss, `\n` vs `\n\n` whitespace). Currency fix held on NutriGrow. Pacific cleared the line.notes drift but introduced new drift on the freshly-aspirated rule 3 fold for STRAP-PP-58 (agent didn't apply). Per-line notes lifting persisted on TerraGreen / Precision (carton-rounding lifted into pack_size), suggesting rule A wording is too easy for the model to interpret as guidance rather than prohibition.

**Failure modes observed worth logging:**

- **Verbatim raw_notes is hard to enforce via prose.** Agent paraphrases multi-paragraph raw_notes content (Precision, NutriGrow, TerraGreen) even though the prompt says verbatim. Looks like the model finds dumping a 6-paragraph block awkward and "cleans it up." Mitigation candidates: stricter wording ("DO NOT paraphrase, summarize, or restructure"), or accept that verbatim-prose extraction is best handled downstream rather than as an extraction-step contract.
- **Adding a restrictive rule can suppress unrelated structured-field extraction.** Round 1 Meridian had `min_order_qty: "20"` populated correctly from prose. Round 2 (after rule A landed) lost it on three lines — agent appears to have read "don't lift from notes section" as "don't extract from notes section." `min_order_qty` extraction is explicitly allowed by its own rule but the model collapsed both. Worth a carve-out: rule A applies to `line.notes` only; structured-field extraction (min_order_qty, payment_terms, etc.) still applies regardless of source location.
- **Rule 3 (column-noun fold) has weak compliance.** STRAP-PP-58 source: description "Polypropylene Strapping, 5/8\" x 9000 ft, machine grade", uom column ROLL. Per the rule, "roll" is not in description, so column-noun + size should fold to `pack_size: "5/8\" x 9000 ft roll"`. Agent left it in description in round 2 despite the rule being in the prompt. May need an explicit example in the few-shot.
- **NutriGrow `requested_sku` semantic miss.** Source: "Your RFQ specified KMEAL-50". Agent put `requested_sku: "KMEAL-44"` (the substitute), golden has `KMEAL-50` (what buyer asked for). The substitution-aware case is genuinely tricky — the schema-level intent is `requested_sku` = what buyer asked for, `supplier_sku` = what supplier offered, and they diverge in the substitution case. Prompt has no explicit handling for substitution. Worth a rule like "in substitution scenarios (`substituted`, `proposed substitute`, `we suggest`), `requested_sku` stays the original buyer SKU; `supplier_sku` is the offered substitute."
- **NutriGrow KMEAL parenthetical handling.** Source description includes `(substituted — see notes)` parenthetical. Agent moved that into `notes` (and clipped `(substituted — see notes)` from description). Golden keeps the parenthetical in description. Either approach is defensible; not a clear win for a rule yet.

**Follow-up parked for next session:**

- Strengthen rule A's prohibition wording vs. carve out "structured fields still extract regardless of source location" exception (Meridian MOQ regression).
- Decide whether to add an explicit `pack_size` few-shot example covering the column-noun fold case (STRAP-PP-58 / rule 3 weak compliance).
- Add a substitution-aware rule for `requested_sku` / `supplier_sku` (NutriGrow).
- Consider a verbatim raw_notes few-shot example covering a multi-paragraph case to anchor "no paraphrasing."
- Acme schema gap still parked.
- Eval harness is the next big thing — every diff in this sweep was a manual `jq | diff`. A field-aware comparator that treats prose `\n` vs `\n\n` and case-insensitive description matches as warnings rather than failures would have flagged "real" drift much faster.

**Sequence note:** Three rounds of agent runs across 8 fixtures used ~16 API calls and surfaced enough signal for three convention decisions, four mechanical golden fixes, and four prompt-clarification candidates. The "run-then-diff" loop continues to outperform what a harness-only run would surface, but is starting to bump up against rate limits — one Precision retry needed a 60s cooldown when 8 fixtures fired in parallel hit the 30k input-tokens/min cap. Sequential runs would dodge this; parallel + retry-on-429 is fine for now.

## 2026-05-04 — Day 2 (rule A carve-out + substitution-SKU prompt edits, validation sweep)

Picked the two highest-confidence prompt edits from the four candidates parked last session and held off on the other two pending harness signal.

**Prompt edits in `src/procure_agent/prompts.py`:**
1. **Rule A carve-out (`line.notes` rule)**: appended "**This rule scopes `line.notes` only.** Structured fields (`min_order_qty`, `payment_terms`, `shipping_terms`, `valid_through`, etc.) still extract from notes-section prose when stated there — the prohibition is on lifting prose into per-line `notes`, not on extracting structured values regardless of source location." Targets the Meridian MOQ regression where rule A had collapsed structured-field extraction along with line.notes lifting.
2. **Substitution-aware SKU semantics (SKU fields rule)**: appended a substitution case enumerating triggers (`substituted`, `proposed substitute`, `we suggest`, `we recommend X instead of Y`, `your RFQ specified X`) with explicit "do not overwrite `requested_sku` with the substitute." Targets NutriGrow KMEAL where round 2 had `requested_sku=KMEAL-44` (the substitute) instead of `KMEAL-50` (what buyer asked for).

**Held for later (post-harness signal):**
- Verbatim raw_notes hardening — the prior session itself flagged ambiguity on whether this belongs at extraction or downstream. A field-aware comparator may absorb the prose-paraphrase noise without prompt edits.
- Rule B trigger 1 / column-noun fold few-shot — single-fixture signal (STRAP-PP-58) wasn't enough to pay a few-shot slot.

**Validation sweep (8 batch-1 fixtures, parallel, one cooldown retry on Meridian/Terragreen for the 429):**

Both targeted edits landed cleanly:
- **Edit #1 worked.** Meridian MOQs all match golden (L1=20, L2=20, L6=10, others null). The carve-out language successfully prevented MOQ extraction from being suppressed by rule A.
- **Edit #4 worked.** NutriGrow line 1: `requested_sku=KMEAL-50, supplier_sku=KMEAL-44` — exactly the golden.

Per-fixture state post-edits: 2/8 byte-clean (01_aloe, 03_rootwise), same as round 2 last session. 02_aloe down to 1 cosmetic diff (`food-grade` casing). Six fixtures with various drift; classes summarized below.

**Two golden artifacts surfaced and fixed in `quote_meridian_supply_2026-04-24.expected.json`:**
- `tier_prices` had been hand-written with single-line dicts (`{"min_qty": "100", "unit_price": "0.32"}`); agent emits `model_dump_json(indent=2)` multi-line. Reformatted golden to match the Pydantic serializer.
- `raw_notes` had stripped `**bold**` markdown markers from the source; agent verbatim correctly preserved them. Restored the markers in golden. Source is `.md`, so verbatim wins.

After golden fix, Meridian's only real drift is one TWINE-NAT-9K line: agent left `"9000 ft per bale"` in description; golden has it lifted to `pack_size`. Rule B trigger 1 (packaging noun in description → lift). Same drift class as Pacific STRAP-PP-58. Two-fixture signal now — would justify the few-shot slot if it persists across the harness.

**Precision currency was variance, not regression.** First run had `currency: "USD"` on all 8 lines (source has bare `$` only). Re-run produced `currency: null` matching golden. The "do not default to USD" rule is robust; first run was Sonnet noise.

**Real remaining drift classes (post-edits, post-golden-fix):**

1. **Rule B trigger 1 weak compliance** (Pacific STRAP, Meridian TWINE) — packaging-noun-in-description fold not firing reliably. Held edit #3 territory.
2. **raw_notes paraphrasing** (Pacific `\n\n`→`\n` separator, Terragreen content-stripped, Precision paraphrased, NutriGrow paraphrased) — held edit #2 territory; multiple shapes of the same class.
3. **Rule A loose on non-structured lifting** — edit #1 carved out structured fields, but the underlying "don't lift global notes prose" rule still has weak compliance for non-structured lifts. Surface forms: Terragreen lifted 3 strings into `line.notes` ("Cover crop is in stock now", "Availability to confirm…", "Supplier may be able to do better…"); Precision lifted "carton of 4" prose into `pack_size` on lines 5/6. The carve-out edit didn't tighten the prohibition itself, only scoped it.
4. **Pacific GST/HST line dropped from raw_notes** — rule C says header admin metadata stays, agent dropped it. Possible single-fixture noise; recheck after harness.
5. **NutriGrow line 1 description handling** — agent split off `"44 lb bag"` to pack_size and stripped `(substituted — see notes)` parenthetical; golden keeps both inline. The build log already noted this is a defensible-either-way case; not a clear win for a rule.

**Failure-mode observation worth keeping:** **Restrictive rules with carve-outs reduce specific regressions but don't strengthen the underlying prohibition.** Edit #1 fixed MOQs (the structured-field carve-out clause). It did not fix Terragreen's 3 line.notes lifts or Precision's pack_size lift from prose — those are exactly the prohibition rule A was intended to enforce. Implication: the model's "lift commentary near a line item" instinct is strong; explicit carve-outs scope but don't suppress it. May need an explicit anti-pattern in the few-shot, or accept that the harness comparator handles this drift class.

**Next:** harness wiring is the next big step. Manual diffing has now twice surfaced the same drift classes; further sweeps will not surface new rules — only more instances of the held drift. Field-aware comparator (numeric Decimal equality, prose-whitespace tolerance, raw_notes content-presence rather than verbatim) will let us distinguish "real new drift" from "known cosmetic noise" in seconds rather than minutes-of-manual-eyeballing per fixture.

## 2026-05-04 — Day 2 (baseline capture + comparator line-key bug)

First clean baseline through `evals/run.py` on the full 14-fixture corpus. Sequential, no 429s. Artifact: `evals/runs/20260504T142352Z.json`.

**Top-line:** 746/774 field matches (96.4%). 0 format_drift, 28 value_mismatch. Line P/R = 1.00 on every fixture. (Fixture 12 reported 0.67 before the comparator fix below; that was harness math, not extraction drift — 3/3 lines actually match post-fix.)

**Drift concentration matches last session's predictions; no new classes surfaced.** Per-field failure breakdown:

- `raw_notes` — 8 fixtures drift (paraphrasing; held edit #2 territory)
- `line_items.*.description` — 8 mismatches (pack/description fold)
- `line_items.*.pack_size` — 6 mismatches (Rule B trigger 1 weak compliance)
- `line_items.*.notes` — 5 mismatches (Rule A loose on non-structured lifting)
- `shipping_terms` — 1 mismatch (Northstar)
- `02_aloe` still drifting on the same `food-grade` / `Food-grade` source-casing miss

Confirms the prior session's call: harness sweeps will surface more *instances* of held drift, not new classes. We now have the field-grouped count signal needed to prioritize prompt-edit candidates by frequency rather than guess from the last fixture sampled.

**Comparator bug surfaced and fixed.** Fixture 12 reported `matched_lines=2`, `line_count_predicted=3`, `only_predicted=0`, `only_golden=0` — math doesn't close. Cause: `_line_key` in `evals/comparator.py` keys on `(requested_sku, supplier_sku, quantity)`; fixture 12 items 1 and 2 are both `(null, null, "12")` (different IBC totes — 275-gal vs 330-gal — at the same buyer qty, no SKU column in the source). The dict-keyed match collapsed both into a single bucket entry; the second line silently overwrote the first. Two real lines became one match with zero `only_predicted` flag.

Fix: replaced dict-keyed match with bucket-by-key + positional pairing within bucket (`_bucket_by_key`). Unique-key behavior is unchanged; colliding keys now pair positionally and surplus on either side counts toward `only_predicted` / `only_golden`. Regression coverage in `tests/test_comparator.py` (collision pair, surplus on one side, reordered unique keys).

**Failure-mode lesson:** **silent matching errors are a comparator failure mode the per-field breakdown can't expose by itself.** Field-match looked clean on fixture 12 because the matched line *fields* were correct — the lost line was simply absent from the comparison. An invariant assertion (`matched + only_predicted = line_count_predicted` and same on golden) would have caught this on the very first run; worth adding to the harness if a similar bug ever recurs. Skipping for now since the fix removes the recurrence vector.

**Next:** dig into the held drift classes with harness numbers in hand. Frequency ranking (raw_notes ≥ description ≥ pack_size > notes > shipping_terms) tells us where prompt-edit ROI is highest; per-fixture instances are where individual rule wording will get tested.

**Mid-session: split the 28 mismatches into golden bug / comparator gap / real drift, then closed the first two.**

- **Golden bug (fixture 12 `raw_notes`):** golden had stripped source's `**` markers, paraphrased `your` → `buyer` and `The original` → `Original` despite verbatim rule. Restored to source-verbatim form. Eliminated the mismatch and unblocked the line-key collision (P/R 0.67 → 1.00 — the collision had already been comparator-fixed; the golden fix removes the residual raw_notes drift).
- **Comparator gap (whitespace-only drift in prose):** added `PROSE_FIELDS` set + `_bucket_prose` tolerance to `evals/comparator.py`. Whitespace-collapse-equivalent strings now bucket as `format_drift`; semantic drift still buckets as `value_mismatch`. 5 unit tests pinning behavior in `tests/test_comparator.py` (paragraph separator drift, line-wrap drift, substantive change still mismatches, null-vs-string still mismatches, decimal-field path unaffected by prose tolerance).
- **Re-run after both fixes (artifact `evals/runs/20260504T150750Z.json`):** 752/784 (95.9%); fixture 12 fully clean except 1 line.notes source-attribution miss. Two run-to-run observations worth keeping: (a) **prose-whitespace tolerance fired zero times this run** — every raw_notes mismatch was substantive (paraphrasing or content swap), not whitespace-only. The tolerance is correctly built (tests pin it) and will catch the drift class when it recurs, but most "raw_notes drift" is structural rephrasing, not formatting. (b) **Precision currency surged 0 → 8 mismatches** — agent over-defaulted to USD on all 8 lines despite source having only `$`. Same fixture went `null` correctly in the prior baseline. The build log already flagged this as Sonnet noise on currency; reproduces here. May be worth a few-shot anti-pattern showing bare-`$` → `null` on a US-supplier-shaped fixture, since prompt-rule alone has weak compliance.

**Held drift classes after fixes (32 mismatches, Bucket C):** pack-noun fold (description ↔ pack_size, 6 mismatches across Quote 07 PEAT, Meridian TWINE, Pacific STRAP — same class flagged twice prior), currency over-default (Precision, 8), substantive `raw_notes` paraphrasing (7), per-line `notes` scoping (5), pack_size ordering (Quote 08, 1), shipping_terms cross-span combine (Quote 09, 1), 02_aloe sentence-cap casing (1). Pack-noun fold remains the highest-ROI prompt-edit candidate; currency over-default jumped into top-1 by count this run on a single fixture.

## 2026-05-04 — Day 2 (continued: Bucket C pack-noun fold, principle reframe, contamination fix)

Took the first Bucket C class — pack-noun fold — through case-by-case inspection. Result: one Bucket A close-out, two real prompt-shape misses, principle reframe applied, train/test contamination averted.

**Per-fixture inspection of the 6 "pack-noun fold" mismatches changed the picture significantly.** The build log called this "6 mismatches across 3 fixtures" treated as one drift class. Reading the actual predicted-vs-golden for each:

- **Quote 07 line 1 (PM-C-2.2 peat):** model lifted `"2.2 cu ft compressed bale"` to pack_size, golden had `"2.2 cu ft bale"` with `"compressed"` left in description. User judgment: model is right — `"compressed"` describes the bale's pack state (compressed bale ≈ 2.2 cu ft, fluffs to ~4 cu ft), so it belongs in pack_size as part of the physical-pack specification. Flipped golden. **2 mismatches close out as Bucket A.**
- **Meridian line 7 (TWINE-NAT-9K):** description `"Natural fiber baling twine, 9000 ft per bale"`, model left it intact, pack_size=null. Trigger 1 of the existing rule literally lists `"per bale"` as an example. Pure compliance gap.
- **Pacific line 8 (STRAP-PP-58):** description `'Polypropylene Strapping, 5/8" x 9000 ft, machine grade'`, UoM column `ROLL`. Trigger 3 territory but the rule's example is a simple `"50 lb"` + `BAG`; multi-dim size mid-comma-list with flanking adjectives doesn't pattern-match well.

**Failure-mode lesson:** **class-level frequency ranking can hide heterogeneity within a "class".** The 6 mismatches split 2/2/2 across three different shapes — one was a golden bug, two cases share Trigger 1 weak compliance, two cases share Trigger 3 example-shape-too-narrow. Per-fixture inspection is mandatory before deciding what to fix; the harness frequency table tells you *where* to look, not *what* to do.

**Principle reframe for the pack_size rule (`prompts.py:39–44`).** Rewrote the lead from "captures pack/packaging info" to "the complete physical-pack specification — the dimensions, count, density modifiers, and packaging-form noun that together describe how the product is packed. Kept as a single coherent field. Description carries product identity; pack_size carries how it's packed." Triggers stay as priority-ordered applications of the principle. Trigger 1 examples updated to call out density modifiers and mid-comma-list span extraction; Trigger 3 rewritten with multi-dim size handling and explicit "keep flanking adjectives in description" rule.

**Train/test contamination caught and fixed.** First draft of the reframed rule used three verbatim phrases from the eval set as concrete examples (`"2.2 cu ft compressed bale"` from Quote 07, `"9000 ft per bale"` from Meridian, `'5/8" x 9000 ft'` from Pacific). User flagged it: rule examples in the prompt body that name eval-corpus values are direct train/test contamination — even paraphrased, they teach the model to memorize specific eval strings rather than learn the pattern. Standard practice: **rule wording uses generic/archetypal shapes; concrete instances live only in the held-out demo.** Sanitized to `"40 lb fluffed bale"`, `"800 ft per spool"`, `'3/4" x 6000 ft'` — none in eval. Verified via grep over `data/synthetic_quotes/` that all replacement strings are absent.

**Failure-mode lesson:** **prompt examples are easy contamination vectors when drafting concrete rule examples** — the eval values are top of mind so they leak in. Worth a checklist habit going forward: any time a rule body gets a new concrete example, grep eval before committing.

**Demo enrichment.** Added two lines to `data/prompt_examples/marian_demo.{txt,expected.json}` using non-corpus products:
- `MAG-PS-09 — Pine shavings bedding, 9 cu ft fluffed bale` + UoM `BALE` → desc=`"Pine shavings bedding"`, pack_size=`"9 cu ft fluffed bale"`. Demonstrates Trigger 1 with a density modifier.
- `MAG-DT-12 — Poly drip tubing, 1/2" x 500 ft, pressure-rated` + UoM `SPOOL` → desc=`"Poly drip tubing, pressure-rated"`, pack_size=`'1/2" x 500 ft spool'`. Demonstrates Trigger 3 with multi-dim mid-comma-list size and flanking-adjective preservation.

Both products grepped clean against the eval corpus. The demo's role is concrete instances of the shapes the rule describes — covers the two failing eval cases by analogy without teaching the model their specific strings.

**Bucket C count after this session:** 30 mismatches (32 prior − 2 from Quote 07 golden flip). 4 of those 30 are the Meridian + Pacific pack-noun cases targeted by the principle reframe + demo enrichment.

**Next:** harness re-run to see what moves on Meridian + Pacific. Watch for (a) Trigger 1 firing on `"X per bale"` shape (Meridian), (b) Trigger 3 firing on multi-dim mid-description size + UoM-column noun (Pacific), (c) no regression on the 10+ fixtures where pack-noun rules already worked. If the reframe lands, move to currency over-default (next class by count) or substantive `raw_notes` paraphrasing (next class by spread).

## 2026-05-04 — Day 2 (continued: prompt sweep + currency salience regression)

Took the remaining drift through a coordinated prompt sweep. Result: **95.5% → 98.0% field-match (749/784 → 768/784, +19 fields).** One regression caught and fixed mid-sweep.

**Per-fixture inspection of the 35 baseline mismatches (artifact `evals/runs/20260504T170146Z.json`) regrouped them into 5 actionable shapes:**

- **Pack_size product-identity over-fire (10 fields, ~6 lines).** Rule 1 was lifting any "packaging noun in description" into pack_size, but the noun is sometimes the product itself (drum *liner* sold as a liner, *drum pump* a pump for drums, *poly tote* sold by-the-tote). Lift broke product names and produced phantom pack_sizes. Rule 4 (measurement-only + canonical UoM → pack_size null) was right but didn't say "and description stays verbatim" — model was stripping `"1 gallon"` anyway.
- **Density modifier dropped (2-3).** `"compressed"` not in the rule's modifier list (only `fluffed` was named).
- **Goldens-are-wrong on `50#` (3).** Per the locked extraction-normalizes decision, `50#` → `50 lb` is canonical; three terragreen goldens kept the source `#` shorthand.
- **Description case (1).** `"food-grade"` source-cased, model title-cased to `"Food-grade"`. No explicit "preserve casing" clause on description.
- **line.notes scope drift in informal email (4-5).** terragreen email — model lifted prose fragments ("In stock now.", "Might be able to do better...") into per-line notes; goldens kept them in raw_notes. The rule said "structurally attached to a single line" but didn't address email-prose ambiguity directly.

Plus 8 raw_notes mismatches (preamble drops, markdown variance) — flagged lowest-ROI, deferred.

**Prompt edits (`prompts.py`).** Single coordinated edit covering 4 of the 5 classes:
- Added a top-level `description` bullet that names verbatim-from-source as the rule and lists casing/punctuation/word-order preservation. Made strip-spans-only-when-rule-fires explicit (closes the "Multi-purpose lubricant, 1 gallon" hole and the case-drift on `"food-grade"`).
- Pack_size Rule 1: added `compressed` and `loose` next to `fluffed` in the density-modifier list. Added a **counter-rule for product-identity nouns** with the "would removing the noun phrase break the product name?" test and 6 archetypal examples (`barrel funnel`, `pail dolly`, `drum cradle`, `bag sealer`, `case opener`, `bottle filler` — all grepped clean against `data/synthetic_quotes/`).
- Pack_size Rule 4: appended "**and description stays verbatim** (do not strip the measurement)" to make the no-strip behavior explicit.
- Notes rule: added an "Informal email bodies" sub-clause — default `line.notes: null` for unstructured email prose; only populate when source uses an explicit per-line marker (`Lead:` / `Status:` / per-line bullet).

**Goldens fix.** Replaced `"pack_size": "50# bag"` × 3 with `"50 lb bag"` in `quote_terragreen_email_2026-04-23.expected.json`.

**Contamination audit caught corpus-verbatim examples in my own draft AND pre-existing in the prompt.** First draft of the counter-rule used `"poly drum liner"`, `"drum pump"`, `"poly tote, 275-gal IBC"`, `"2.2 cu ft compressed bale"` — all verbatim from the eval set (quote_09, quote_12, quote_07). User flagged before write. Re-checked all proposed examples via `rg --no-ignore -i "<term>" data/synthetic_quotes/` — replaced with synthetic equivalents, all grepped clean. **Also caught two pre-existing leaks in the same passage:** `"55-gal drum"` and `"Multi-purpose lubricant, 1 gallon"` were already in the prompt and both verbatim from the corpus (quote_11, quote_meridian). Swapped to `"200-l drum"` / `"Industrial cleaner, 5 liters"` — synthetic, grepped clean.

**Failure-mode lesson — contamination audit needs to cover *existing* prompt content, not just new edits.** Prior session already caught new-example leaks; this session shows old-example leaks survive across editing rounds because the grep habit only triggered on additions. Worth a periodic full-prompt sweep against `data/synthetic_quotes/` to catch latent leakage. The prompt itself is small enough that this is cheap.

**Currency salience regression — 0 → 8 mismatches on `quote_precision_bearings`.** Post-edit harness showed 96.4% net (above baseline despite the regression). Investigation: 8 of 8 lines in precision_bearings predicted `"USD"` despite source containing only `$` symbols and no ISO code (Greenville SC supplier, Reno NV ship-to). Three consecutive single-fixture re-runs all reproduced — not Haiku stochasticity, real prompt regression. The original currency rule's wording (*"Do not default to USD when no ISO code is stated"*) had previously held compliance; my edit lengthened the field-specific list above it, pushing currency further down and degrading attention.

**Failure-mode lesson — prompt edits redistribute attention across the whole rule list, not just where you edited.** A localized fix for class A can silently destabilize an unrelated class B that was previously holding by a thin margin. Compliance on long lists is fragile. Mitigation going forward: any harness sweep after a prompt edit needs to read the *full* per-field breakdown, not just the targeted classes — a regression elsewhere is a signal that the edit consumed attention budget.

**Currency rule rewrite.** Restructured the bullet to make the default explicit and the prohibition absolute: leads with *"ISO code only — emit `USD`/`EUR`/`CAD`, or `null`. **The default is `null`.**"* Then enumerates the only triggers that populate (ISO header, ISO footer, ISO subtotal, inline currency name). Then an absolute-language tail: *"**Never infer currency from supplier address, area code, state name, ZIP code, or country of operation** ... This rule is absolute; do not override it based on context plausibility."* Three re-runs of precision_bearings all clean (1 mis, raw_notes only — pre-existing).

**Final harness (artifact `evals/runs/20260504T174213Z.json`):** 768/784 (98.0%). 0 format_drift, 16 value_mismatch.

Per-field deltas vs baseline:
- `description` 10 → 2 (−8)
- `pack_size` 11 → 5 (−6)
- `notes` (line) 5 → 1 (−4)
- `raw_notes` 8 → 7 (−1)
- `currency` 0 → 0 (regression caught + fixed)
- `shipping_terms` 1 → 1 (unchanged)

Three fixtures now perfect (`02_aloe_corp_prose_email`, `quote_10`, `quote_11`). `quote_precision_bearings` returned to 1 mis (raw_notes). `quote_terragreen_email` improved 7 → 4 from `50#` golden fix + line.notes email-scope clause.

**Held drift after this session (16 mismatches):**
- `raw_notes` 7 — preamble drops, markdown bold variance, structural rephrasing. Lowest ROI; needs comparator semantic-equivalence work or per-fixture golden audits.
- `pack_size` 5 — word-order/canonical-form variants (`drum (55 gal)` vs `55 gal drum`, `compressed bale, 3.8 cu ft` vs `3.8 cu ft compressed bale`). Comparator territory more than prompt territory.
- `description` 2, `notes` 1, `shipping_terms` 1 — small singletons, mostly word-order or scope edge cases.

**Next:** the easy wins are gone. Remaining classes need either (a) comparator semantic-equivalence for prose fields and pack_size canonicalization, or (b) per-fixture golden audits — neither cheap. Worth weighing against shipping the LangGraph node-body work the harness was built to support.

## 2026-05-04 — Day 2 (continued: inventory CSV + Day-3 plan)

Inventory master at `data/inventory/inventory.csv`: 146 rows (51 anchors + 95 filler), 12 columns. Two-pass prompt to claude.ai — anchors-first to bound single-shot risk on row count + distribution constraints, filler in a second turn applying constraints across the full set. All 51 anchor SKUs from the eval corpus present verbatim. `KMEAL-44` absent on purpose (preserves the NutriGrow substitution exception case). Validated: unique SKUs, canonical UoM/category sets, all prices parse Decimal, all dates ISO. Distribution: 5 low-stock, 3 empty-currency, 4 stale-dated, 2 CAD anchors.

Three exception signals baked in by design (worth knowing about as match logic lands):
- `KMEAL-50` / `PEAT-BALE-3.8` in CAD — fires currency mismatch against corpus quotes that emit `currency: null` (Pacific Coast Amendments uses bare `$`).
- `STRAP-PP-58` master pack `"6000 ft coil"` vs corpus `'5/8" x 9000 ft'` / UoM `ROLL` — fires pack-size variance + noun divergence (coil vs roll).
- `AL101` master pack `"5 kg pail"` vs corpus 50 kg order — tests bulk-vs-pail handling on the match node.

v1 schema is denormalized — `last_paid_*` and `on_hand_qty` / `reorder_point` / `lead_time_days` collapse what an ERP would split into `products` / `price_history` / `inventory_levels` tables. Explicit v1 simplification; production split named in the README design-decisions section.

**Plan from here.** Product Pydantic model + CSV loader (in-memory `dict[str, Product]`) → state types (`QuoteWorkflowState`, `MatchResult`, `Exception_`) → hand-authored LangGraph extract subgraph (`extract_node` + `ToolNode` + `should_continue`; speak-in-primitives, not `create_react_agent`) → concept-mapping doc at `docs/from_primitives_to_langgraph.md` → stub match/flag/approval nodes → compile with `MemorySaver` + `interrupt_before=["approval_node"]` → end-to-end run on one fixture. Real match/flag logic, eval harness wrapped around graph runs, Supabase migration, FastAPI HITL endpoint follow as pace allows — ordered next-steps, not hard-scheduled to days.

## 2026-05-04 — Day 2 (Product model + inventory loader)

`Product` Pydantic model and `load_products()` landed. 146-row real CSV loads clean; 7 tests pin the loader behavior.

**Schema additions in `src/procure_agent/schemas.py`:**
- `Category` StrEnum — closed set of the six categories present in `data/inventory/inventory.csv` (bearings_drive, cover_crop_seed, fertilizer, hardware_mro, packaging, soil_amendment). Adding a category later requires a code change; that's a feature for v1, since it catches typos at load time.
- `UoM` StrEnum — same canonical set the prompt teaches (`kg, lb, oz, gal, l, each, case`). Inventory only exercises 5 of 7; the other 2 stay reserved so `Product.uom` and `QuoteLineItem.uom` align if `QuoteLineItem.uom` is later retrofitted.
- `Product` BaseModel, `frozen=True`. Fields mirror the CSV columns 1:1; `pack_size` and `last_paid_currency` optional, everything else required.

**Loader (`src/procure_agent/inventory.py`):**
- `DEFAULT_INVENTORY_PATH` resolved relative to the package file (not `cwd`) so the loader works regardless of where pytest / the agent is invoked.
- `_clean()` collapses empty CSV cells to `None` before Pydantic validation. Required fields with empty cells fail validation cleanly (None into non-Optional `str` raises ValidationError) — no hand-rolled "missing column" handling needed.
- Returns `dict[str, Product]` keyed by SKU. No duplicate-SKU check; the inventory CSV is checked-in and validated at authoring (build-log entry above this one names "unique SKUs" as a load-time invariant). If duplicates ever appear, the dict-comprehension silently overwrites — would surface as a row-count mismatch in the smoke test.

**Tests (`tests/test_inventory.py`, 7 passing):**
- `test_real_csv_loads_clean` — round-trips all 146 rows. The high-value smoke check; if any row goes off-spec (unknown category, malformed Decimal, bad date), this fails.
- `test_anchor_sku_matches_source_row` — exact-value pin on AL101 across every column. Cheap regression cover for type coercion (Decimal/date/int).
- `test_substitution_anchor_preserved` — `KMEAL-44` absent, `KMEAL-50` present. Build-log invariant for the NutriGrow substitution exception case.
- Edge cases: empty currency → None, unknown category fails, unknown UoM fails, default path resolves.

**Decisions worth keeping:**
- StrEnum chosen for `Category` and `UoM` over plain str. Catches data drift at load time (matches the global "StrEnum over string literals for constrained choices" rule). `QuoteLineItem.uom` stays plain `str` for now — retrofitting it to `UoM` would tighten extraction validation (non-canonical UoMs would crash extraction rather than pass through), which is a behavior change worth a separate conversation.
- `Product` is `frozen=True` since it's master data — once loaded it doesn't mutate. `Quote` / `QuoteLineItem` stay mutable since downstream nodes will attach match results.
- Loader is a function, not a class. No caching; v1 reads the CSV on every call. Caching moves to the LangGraph state when match logic lands.

**Next:** state types (`QuoteWorkflowState`, `MatchResult`, `Exception_`) and the hand-authored extract subgraph. State types are scaffolding; subgraph node bodies are the user's to write per the working agreement.

## 2026-05-04 — Day 2 (continued: LangGraph extract subgraph + smoke tests)

`QuoteWorkflowState` and the extract subgraph landed. Side-by-side run on the aloe anchor fixture produces the same `Quote` JSON as `agent.run` modulo Sonnet stochasticity on `raw_notes`. Six smoke tests cover compile/topology + pure-function routing without API calls; full suite at 22 passing.

**State (`src/procure_agent/state.py`).**
- `QuoteWorkflowState` TypedDict, `total=False`. `messages: Annotated[list[dict], operator.add]` is the substantive choice — the reducer makes node returns concatenate, so node bodies stay pure (read state, return delta) and the runtime owns appending.
- `MatchResult` and `Exception_` shipped as placeholder shells (one field each + a `line_index` pointer). Schemas firm up when match/flag bodies land — premature commitment to confidence types or a `kind` enum was the wrong call when the match logic doesn't exist yet.

**Graph (`src/procure_agent/graph.py`).**
- `extract_node` — one Anthropic turn. Reads `state["messages"]`, calls `client.messages.create(...)` with the same `(MODEL, MAX_TOKENS, SYSTEM, TOOLS)` as `agent.run`, returns `{"messages": [<assistant>]}`. On terminal turn (`stop_reason != "tool_use"`), also parses fenced JSON via `extract_json_block` and returns `{..., "quote": Quote(...)}`.
- `tools_node` — hand-rolled, NOT `langgraph.prebuilt.ToolNode`. Iterates `tool_use` blocks from the last assistant message, dispatches via the `agent.HANDLERS` table, returns one user-role message containing the `tool_result` blocks.
- `should_continue` — pure function over the last message; routes `"tools"` if any `tool_use` block, else `"match"`.
- `match_node` / `flag_node` / `approval_node` — no-op stubs returning `{}` so the graph compiles + runs end-to-end through `interrupt_before=["approval"]`. Bodies land with the match/flag work.
- `build_graph()` wires `START → extract → (tools → extract)* → match → flag → approval → END`, compiles with `MemorySaver()`. Module-level `graph = build_graph()` so other modules import the compiled artifact directly.
- `__main__` mirrors `agent.py`'s, so `uv run python -m procure_agent.graph <fixture>` is symmetric with `uv run python -m procure_agent.agent <fixture>` — same prompt, same fixture, different runtime substrate.

**Decisions worth keeping:**
- **(A) Quote parse inside `extract_node`, not a separate `parse_node`.** Single-node responsibility for "extract subgraph produces a Quote." A parse_node fragments responsibility for a one-line transform and adds graph ceremony that doesn't earn its keep.
- **(B) Hand-rolled `tools_node`, not `ToolNode` from `langgraph.prebuilt`.** ToolNode expects LangChain `BaseMessage` types and `@tool`-decorated handlers. Adopting it would mean wrapping the existing Anthropic-native message blocks and rewiring the prompt path — cost without payoff for a 98% field-match prompt that's already tuned. Hand-rolled mirrors `agent.run`'s dispatch literally, which makes the concept-mapping doc read as "the for-loop body became a node" rather than "we adopted a framework."
- **(C) `_extract_json_block` renamed to public `extract_json_block`.** Used by both `agent.py` and `graph.py` now; underscore-leak across modules is the wrong shape.
- **(D) Caller seeds `messages` at entry; nodes stay pure.** The `__main__` bootstrap builds `[{"role": "user", "content": f"Extract the quote in {fixture} as JSON."}]` and passes it in. Node bodies read state and return deltas — no auto-seeding from `fixture_filename` even though that would be a few-line shortcut.

**Smoke tests (`tests/test_graph.py`, 6 passing).** All pure / no API.
- `test_graph_compiles_with_expected_nodes` — `set(graph.nodes.keys())` matches the 6 names (5 + `__start__`).
- `test_module_level_graph_is_compiled` — pins the import-time compile.
- `test_should_continue_routes_to_tools_when_tool_use_present` / `..._to_match_when_no_tool_use` — both branches of the conditional edge.
- `test_tools_node_dispatches_read_file` — uses the real anchor fixture (`01_aloe_corp_clean_tabular.txt`); asserts `"ALOE CORP"` round-trips through the JSON-encoded `tool_result` content.
- `test_tools_node_skips_text_blocks` — only `tool_use` blocks dispatch; text blocks ignored.
- Skipped: `extract_node` parse-with-mock (low value, mostly tests the mock plumbing). Deferred: end-to-end with mocked client (pays for the setup once match/flag bodies exist).

**Side-by-side run.** Both invocations on `01_aloe_corp_clean_tabular.txt` produced identical `Quote` JSON on every field except `raw_notes` (one returned `null`, one returned `"Subtotal: 15,000.00 USD"`). Sonnet stochasticity, not a translation defect — same prompt, same model, two independent calls.

**Held drift / not done this session.** Concept-mapping doc (`docs/from_primitives_to_langgraph.md`) — section headers landed, prose still empty. Next-up.

**Next:** concept-mapping doc prose (Claude drafts, user revises ruthlessly, same shape as the README). Then real match + flag logic against the in-memory product master, with `MatchResult` and `Exception_` schemas firming up.

## 2026-05-04 — Day 2 (continued: graph.py concept mapping)

No code changes. Walked through `graph.py` end-to-end to lock in the LangGraph mental model before match/flag bodies land.

**Frame that landed.**
- `graph.py` is a literal translation of the `agent.run` while-loop: nodes for the loop body, a conditional edge for the loop condition, a typed-dict state with an `operator.add` reducer on `messages` so node returns concatenate rather than overwrite.
- `langgraph.prebuilt.create_react_agent` would give the same topology in one constructor call. Primitives path is the deliberate choice for this build.
- The runtime differences vs. `agent.py` don't show up by reading the file — they show up at invoke time: durability (checkpointer), pausability (`interrupt_before`), observability (LangSmith spans per node, free), extensibility (add-node-add-edge vs. weaving more `while` branches).

**Mental model for extension.**
- Two kinds of "more" worth keeping separate: (1) filling stub bodies (`match` / `flag` / `approval`) leaves topology unchanged and makes traces richer; (2) new nodes or branches (retry on extract failure, clarify-on-low-confidence, parallel match fanout via `Send`) grow the topology.
- `interrupt_before=["approval"]` is the structural seam between the autonomous zone (`extract → tools* → match → flag`) and the human-authorized zone (`approval → write-back`). That seam doesn't move as functionality lands.
- Supplier onboarding, BOM creation, product master are separate `StateGraph`s sharing the architecture, not branches off `quote_workflow`.

**Next:** match-node body against the in-memory product master. First node since `extract` to emit real state — first session where a LangSmith trace shows the pipeline past the ReAct loop.
