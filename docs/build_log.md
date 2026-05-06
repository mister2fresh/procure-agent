# build log

Append-only technical record. What worked, what broke, failure-mode notes.

## 2026-05-03

Designed the post-extraction quote schema (`src/procure_agent/schemas.py`)
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
  back `quotes.line_items` JSONB and the eval harness.
- Schema fields that landed beyond the minimal core: `payment_terms`, `shipping_terms`,
  `min_order_qty`. Suppliers in real procurement always state these; cheaper to model now
  than retrofit later.
- `requested_sku` and `supplier_sku` both nullable. Substitution case = both populated and ≠.

ReAct loop deferred to next session. Anthropic API key + LangSmith account need to land in
`.env` before the loop runs.

Scaffolded `src/procure_agent/agent.py` with the from-scratch
ReAct loop infrastructure: `Anthropic` client, `MODEL = claude-sonnet-4-6`, `read_file`
tool (schema + path-scoped handler with traversal guard targeting `data/synthetic_quotes/`),
and the `run()` loop itself.

Reasoning notes worth keeping:
- The minimal SDK loop is the right shape at this stage. LangGraph translation, HITL
  pause/resume, and Postgres checkpointing are deferred concerns and explicitly out of
  scope for the from-scratch loop.
- `read_file` is path-scoped via `Path.resolve()` + `QUOTES_DIR not in target.parents`
  rather than a string `startswith` check. Keeps symlinks and `..` segments honest.
- Tool result `content` is `json.dumps(...)`'d so dict/list returns survive intact rather
  than getting `repr()`'d. Trivial now (`read_file` returns str), but the convention
  carries forward to later tools that return structured data.

No live run yet, so no failure mode observed. That's tomorrow's first task.

System prompt + few-shot scaffolding landed; loop entry point still TODO.

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

Reopened the per-transaction-ref decision before more was built on top.

Schema delta:
- `Quote.rfq_ref: str | None` — buyer-side transaction reference this quote responds to (RFQ #, "Buyer Ref:", "Your Ref:", "Buyer Reference:"). Distinct from `customer_ref` (the persistent customer ID).

The earlier session's plan was to call this field `buyer_ref` if/when it came back. That name was wrong: `buyer_ref` reads as a synonym for `customer_ref` — both name "the buyer/customer's identifier from the supplier's POV." The per-transaction concept needs a distinct name that signals transaction-specificity. Settled on per-document-type naming: `rfq_ref` on Quote; PO and Invoice models, when they arrive, will carry `po_ref` / `invoice_ref`. Same pattern as `supplier_ref` already being document-type-scoped. A downstream doc can also carry an upstream ref (a PO might carry `rfq_ref` linking back to the originating RFQ) without overloading a single polymorphic field.

Cost of doing it now vs. deferring: every fixture already has the data in source text, the prompt was already spending a paragraph telling the model to throw it away, and post-Postgres it would have meant a column migration. ~30 min of mechanical edits.

Goldens reconciled:
- Demo `marian_demo` → `rfq_ref: "RFQ-8842"` (the line that was previously dropped).
- Eval 01/02 → `rfq_ref: "RFQ-1142"` (header line on 01; subject line on the prose-email 02).
- Eval 03 → `rfq_ref: "RFQ-1143"` ("Buyer Reference:" label variant).

Prompt updates: `customer_ref` bullet's "dropped entirely" clause flipped to "those go in `rfq_ref`, not here"; new `rfq_ref` bullet covers the label variants and explicitly notes prose-inline appearance (email subject) so fixture 02's RFQ extraction has a directive.

Still untested at runtime. Adds another extraction surface to the eval set; whether the model picks up the RFQ from a prose subject line vs. only from header-shaped lines is an unknown.

`__main__` driver landed; loop is now end-to-end runnable.

Driver shape: `sys.argv[1]` (default `01_aloe_corp_clean_tabular.txt`) → `run(...)` → `_extract_json_block` → `Quote.model_validate_json` → `model_dump_json(indent=2)` to stdout. Skipped argparse — one positional arg doesn't earn a parser. `_extract_json_block` filters text blocks, regex-matches the fenced ```json``` from the output contract, and raises `ValueError` with the full response inlined when no block is found. Validation is fail-fast on purpose: each failure mode (bad fixture name, no JSON block, wrong shape, max_turns) raises a distinct exception type so the eventual eval harness can switch on them.

Prompt change: `read_file` failure clause flipped from "emit a JSON object with all fields null" to "emit a single line `ERROR: <short description>` and stop". The all-null instruction would've failed `Quote` validation anyway (`supplier_name`, `line_items`, etc. are non-optional). Considered relaxing the schema to allow null on those fields — rejected. The schema mirrors what lands in `quotes.line_items` JSONB once Postgres is in place; loosening domain types to model a *tool failure* would force every downstream consumer to null-check fields that are genuinely required for a real quote. Tool failures are "no extraction happened," not "extraction with missing fields." The `ERROR:` line short-circuits to `_extract_json_block`'s ValueError path and surfaces the model's description verbatim. If the eval harness later wants structured failure, add an `ExtractionResult = Quote | ExtractionError` union — but only when actually needed.

Live run pending — driver is wired and the API key is in place; first run + observations land in the next session.

First live runs of all three eval fixtures + design-principle clarification + reconciliation of goldens to match.

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

Loop is solid against the small corpus. Next: expand corpus to ~10-15 fixtures (tier pricing, multi-line, missing-field cases), wire the pytest eval harness with field-aware comparators, then translate to LangGraph.

## 2026-05-03 — corpus expansion batch 1

Six new fixtures cover tier pricing, multi-currency, MOQ-in-prose, SKU substitution, missing-required-fields, and stacked exceptions. Format expansion: `.csv`, `.docx`, `.md` alongside the original `.txt`.

**`read_file` tool gained docx support.** Added `python-docx`. New `_read_docx` helper walks the body in document order — paragraphs as lines, tables as pipe-delimited rows. Dispatches on suffix in `read_file`; `.txt`/`.csv`/`.md` still pass through `read_text()` unchanged. Smoke-tested on both docx fixtures (Precision Bearings, NutriGrow); table rows render cleanly and document-order interleaving holds.

**Schema bug fixed: 2dp price quantizer was lossy.** The `Price = Annotated[Decimal, AfterValidator(_to_2dp)]` validator added during the verbatim-extraction pass was wrong for high-precision quotes. Acme's fastener pricing is at 3 decimals (`$0.142`); `Decimal("0.142").quantize(Decimal("0.01"))` truncates to `0.14`, breaking line-total reconciliation against subtotals.

Resolution: dropped the validator entirely. `unit_price` and `tier_prices[].unit_price` are now plain `Decimal`. Source precision survives end-to-end. The "compare 300 vs 300.00 as the same value" responsibility moves to the eval harness comparator (numeric Decimal equality), which is where it belongs anyway. All 9 existing + new goldens validate post-fix, so the change is non-breaking.

Lesson worth keeping: **schema-layer normalization is brittle when the domain has wider precision than the canonical form assumes.** The prompt already commits the model to source-precision verbatim; the schema validator was overriding that — solving a real problem (golden-comparison stability) at the wrong layer. Comparators belong in the harness; the schema's job is structure, not display.

**Goldens scaffolded for 5 of 6.** Acme deferred — it's a price list with no order quantity stated, and the schema requires non-null `quantity`. Three resolution paths possible (synthesize a fake quoted qty, add a `quote_type` discriminator, or ERROR-on-extract). Resolution: keep the fixture and skip the golden until v1.x adds the schema branch. One fixture's worth of eval signal lost in exchange for not inventing data.

**Sidecar `.notes.md` per fixture** captures the downstream-eval rubric items the v1 schema can't carry: NCNR clauses, carton-rounding rules, substitution-acceptance routing, FX-estimate-is-reference-only, missing-freight completeness flags, faithfulness math reconciliations. These become eval targets once reconciliation/HITL/PO-generation nodes land in step 3 (LangGraph translation). Format converged on 5 sections: v1 extraction caveats, exception-flagged-when-warranted, faithfulness, completeness/HITL routing, inventory matching.

**Design questions surfaced for later:**
- TerraGreen line `GREENS-CC` ($2.85/lb, qty 200, no UoM column): golden derives `uom: "lb"` from the price modifier. Strict reading would emit `null` UoM and force HITL. Currently mild inference; need to decide whether the prompt should be tightened or this is acceptable extraction behavior.
- TerraGreen line `WORMC-1CY` (UoM in SKU stem, `1CY` = 1 cubic yard): golden defaults to `"each"` since the schema requires non-null `uom`. Same class of problem — the canonical UoM set is too narrow for this domain.
- Meridian line `LUBE-WD40-1G`: golden uses `uom: "gal"` and leaves "1 gallon" in description rather than splitting to `pack_size`. Different from the consistent pack-split applied elsewhere. The prompt's pack-split rule kicks in only when there's a separate pack form vs. UoM; here they collide.
- The canonical UoM set (`{kg, lb, oz, gal, l, each, case}`) is forcing too many real-world UoMs (`BAG`, `PAIL`, `BALE`, `ROLL`, `BOX`, `PR`) to collapse to `each`. Fine for v1 but loses a lot of detail.

No agent runs against the new fixtures yet — saved for next session. Goldens are aspirational targets per the prompt's strict reading; harness-driven divergence will surface real signal once step 2 wires up.

Next: pull next batch of fixtures, then go wide on agent-run testing.

## 2026-05-03 — corpus expansion batch 2 goldens

Six more fixtures target extraction edge cases — refs, pack-size variations, date formats, multi-row qty breaks, lead-time prose, and a revised-quote ref trap. `.expected.json` for all 6 landed in the same pass. No `.notes.md` sidecars this batch — fixtures are narrower and the wrinkles are encoded in the goldens directly.

**Convention reinforcement (batch 1 → batch 2 carry-over):**
- Non-canonical UoM tokens (`bag`, `bale`, `pail`, `drum`, `tote`) → `uom: "each"` (or `"case"` when literal); pack form preserved in `pack_size`.
- Bare `$` symbol → `currency: null`; explicit ISO code → that code.
- `customer_ref` (persistent customer ID) and `rfq_ref` (per-transaction) stay separate even when both restate in a footer reminder line.

**Pack-size placement rule pinned:** UoM-column word (`bag`/`bale`/`drum`) goes into `pack_size` *only when not already in description*. Pacific amendments' `PEAT-BALE-3.8` left "bale" in description; fixture 7's `PM-C-2.2` pulled "bale" into `pack_size: "2.2 cu ft bale"` because the description didn't carry it. Provisional pending more fixtures.

**Judgment calls, batch-2-specific:**
- Fixture 9 (Northstar): slash-format date `05/04/2026` only appears in prose, kept verbatim in `raw_notes`. Structured `issued_date` / `valid_through` come from unambiguous `dd-MMM-yyyy` and `Month DD, YYYY` formats elsewhere in the email. Locale ambiguity not pinned by the golden — it's a downstream-normalization concern.
- Fixture 10 (Continental Ingredients qty break): same SKU appearing in two rows at different qty/price collapses to one line item with `tier_prices` populated. `quantity` = larger tier qty, `unit_price` = price at that tier. Cottonseed (single-row) gets empty `tier_prices`.
- Fixture 12 (Riverway revised quote): `supplier_ref` = live ref `"RW-2026-0419-R2"` (not the prominent old ref). Item 2 qty = 12; the parenthetical "(was qty 8 in original)" did not bleed into the line item. Supersession context lives in `raw_notes`.
- Fixture 11 (Harbor): per-line lead-time status went into `notes` per item (`"in stock — can ship today"`, `"8-10 week lead time — must commit by 5/15"`, etc.). `valid_through` derived from "Valid: 30 days from quote date" → 2026-05-29.

No agent runs yet against batch 2 either. Next: agent test pass across full corpus (batches 1 + 2), then pytest harness.

## 2026-05-03 — first agent pass on batch 2 corpus

First end-to-end agent runs on the batch-2 fixtures. Started 0/6 byte-matching the goldens; ended with 1 clean match (fixture 10) and the rest narrowed to a single class of remaining drift (signature stripping). Four prompt rules added en route.

**Drift buckets surfaced on the first pass:**
- **Schema/shape misses.** Fixture 10 (qty-break multirow) collapsed three CSV rows into three line items with the lowest tier as headline and one tier hoisted into `tier_prices`. Fixture 11 emitted `valid_through: null` despite source saying "Valid: 30 days from quote date".
- **Convention drift.** `currency: "USD"` over-inferred where source had only `$`; `pack_size` dropped UoM-column nouns (`"50 lb"` instead of `"50 lb bag"`); `uom: "case"` for a `bag` UoM column where the canonical set has no entry.
- **Prose hygiene.** raw_notes kept signatures and admin metadata (`Salesperson: K. Tomlinson`); `\n\n` separator compliance loose; `[ADDED]` verbatim vs golden's paraphrase.
- **Edge cases.** Pack info bleeding into description; parenthetical pack reordering (`"drum (55 gal)"` vs golden's `"55 gal drum"`).

**Four conventions decided this session and encoded in the prompt:**

1. **valid_through derivation reversed.** Old prompt rule: never derive from issued_date. New rule: derive when source states explicit math (`"valid 30 days from quote date"`, `"expires 2 weeks from issue"`); strict-null only when source is silent or vague (`TBD`/`upon request`). Triggered by fixture 11 where the golden encoded the derived date and the prompt forbade it — golden was right, prompt was wrong.
2. **Multi-row same-SKU is not a tier table.** Original golden 10 collapsed same-SKU rows into one line item with `tier_prices` populated and the top-tier qty as headline. Summing-as-headline was considered and rejected: differing prices on same-SKU rows is the signature of supplier tier offers, not buyer split-lot orders, and summing invents a buyer commitment that isn't in the source. Settled rule: each CSV/table row is its own `QuoteLineItem`; `tier_prices` only populates when a single row carries an inline tier-break statement. Faithful row-by-row extraction; downstream decides duplicates. Golden 10 rewritten from 3 line items to 5.
3. **pack_size UoM-column rule pinned into the prompt.** When a CSV/table has a separate UoM column with a packaging noun (`bag`, `bale`, `pail`, `drum`, `tote`), fold it into `pack_size` only if not already in the description. Rule had only existed as a session-note convention; the model didn't have it, so output drifted across fixtures 07, 08, 10. Same edit also tightened the `uom` rule to enumerate the packaging nouns that route to `pack_size + uom: each`, since "what's a canonical UoM" was implicit.
4. **Currency: do not default to USD.** Existing rule said bare `$` is insufficient, but the model still defaulted to USD on fixture 07. Tightened with explicit "do not default to USD even if the supplier appears to be US-based."

**Re-run results:** fixture 10 byte-clean (was 13 diffs). Fixtures 07/08/09/11 down to 1-2 diffs each, almost entirely raw_notes signature retention. Fixture 12 still drifts on `[ADDED]` verbatim and revision-prose paraphrase.

**Single biggest source of remaining drift: signature keep/skip contradiction.** Current `raw_notes` KEEP rule says signature contact info (name, title, email, phone) belongs in raw_notes. All four affected goldens (07, 09, 11, 12) strip them. Either the rule flips (SKIP signatures) or the goldens get rewritten — same flavor of issue applies to header admin metadata (`Salesperson:`, `Freight: TBD`). Deferred for next session.

**Other minor drift left on the table:**
- Fixture 08: `pack_size: "drum (55 gal)"` (verbatim from CSV column) vs golden's `"55 gal drum"` (reordered). Prompt says "as written"; golden is normalized. Worth flipping one direction next pass.
- Fixture 09: `shipping_terms` over-split — agent put `ex-warehouse Tacoma` in raw_notes alone, golden combined as `"ex-warehouse Tacoma; freight prepay & add"`.
- Fixture 12: source-prose normalization (`**` markdown stripping, `your`→`buyer`, `[ADDED]`→`added in revision`) — agent preserves verbatim per existing rule.

**Sequence lesson worth keeping:** running the agent before harness wiring is high-signal-per-API-call. ~12 calls (two passes of 6 fixtures) surfaced four prompt rules + a golden rewrite + the next-session-blocker (signature decision). Same drift would have been masked by a harness-only run reporting per-field hit rates, because half the issues were prompt/golden contradictions where neither side was clearly correct.

**Next:** settle signature keep/skip; either flip the prompt or rewrite the four goldens. Then sweep batch 1 (remaining ~6 fixtures) for the same drift classes. Harness wiring after.

## 2026-05-03 — signature keep/skip settled

Decision: **KEEP signatures verbatim in `raw_notes`** (current prompt rule stands). No prompt edit, no golden rewrites. Goldens 07/09/11/12 will get signature blocks reinstated when their next pass runs — defer that mechanical fix to the batch-1 sweep session so it lands as one batch of golden updates rather than scattered.

Why not flip the prompt: signatures are genuinely structured supplier-contact data (name, title, email, phone) — exactly the schema supplier onboarding (handoff §week 3) needs. Designing a `Contact` model now expands extraction scope mid-build for a workflow that's two weeks out, on thin signal (signature shape varies a lot — "Thanks, Bob" through full block). Raw_notes loses no information; the structured lift is a one-prompt-change away once onboarding lands and we've seen 20+ signature variants.

Trigger for revisit: handoff doc §week 3 (Supplier onboarding) annotated with "extract signatures into structured `Contact` here" so the next-workflow-startup pass picks it up automatically.

Header admin metadata (`Salesperson:`, `Freight: TBD`) is the same shape of question but separate — those aren't signature data, they're document-header attribution. Will fall out of the batch-1 sweep when fresh fixtures with similar headers either get goldens that include them or push back on the prompt rule. No standalone decision needed yet.

## 2026-05-03 — batch-1 sweep

Eight batch-1 fixtures end-to-end (1/2/3 + Pacific / TerraGreen / Meridian / Precision / NutriGrow). Two passes, ~14 API calls. Three convention calls landed (rule A on per-line `notes` scope, rule B reframed for pack_size/UoM independence, rule C on header admin metadata kept). Four golden updates and signature reinstatement in 07/09/11/12.

**Conventions decided this session:**

1. **Rule A — `line.notes` scope.** `line.notes` populates ONLY when the source structurally attaches commentary to a single line: per-line column (`Status: in stock`), sub-bullet under that line, `Lead:` field. Global notes-section prose that *references* line numbers (`"Line 5 ships separately"`, `"MOQ for Lines 1 and 2 is 20"`) stays in `raw_notes` verbatim. Goldens 07/09/Pacific/TerraGreen/Meridian/Precision already match this; Harbor (golden 11) is the precedent for the "structurally per-line" case (Status field under each item).

2. **Rule B — pack_size/UoM independence.** The first cut had a too-broad "canonical UoM = no pack split" carve-out. The 55-gal-drum-charged-per-gallon counterexample broke it. Reframed: pack_size is the *pack constraint* (the unit you must order in); UoM is *how it is charged*. They are independent and can coexist (`pack_size: "55-gal drum"`, `uom: "gal"`). Triggers, in priority: (1) packaging noun in description → lift verbatim pack phrase to `pack_size`, strip from description; (2) unit-pack form ("case of 12") → lift verbatim; (3) packaging-noun UoM column + size in description and no description noun → combine ("50 lb" + col=BAG → "50 lb bag"). When none fire (canonical UoM column + measurement-only description, no packaging noun, e.g. "1 gallon" + uom GAL), `pack_size` stays null.

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

## 2026-05-04 — rule A carve-out + substitution-SKU prompt edits, validation sweep

Picked the two highest-confidence prompt edits from the four candidates parked the prior session; held the other two pending harness signal.

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

Per-fixture state post-edits: 2/8 byte-clean (01_aloe, 03_rootwise), same as round 2 of the prior sweep. 02_aloe down to 1 cosmetic diff (`food-grade` casing). Six fixtures with various drift; classes summarized below.

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

## 2026-05-04 — baseline capture + comparator line-key bug

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

## 2026-05-04 — Bucket C pack-noun fold, principle reframe, contamination fix

Took the first Bucket C class — pack-noun fold — through case-by-case inspection. Result: one Bucket A close-out, two real prompt-shape misses, principle reframe applied, train/test contamination averted.

**Per-fixture inspection of the 6 "pack-noun fold" mismatches changed the picture significantly.** The build log called this "6 mismatches across 3 fixtures" treated as one drift class. Reading the actual predicted-vs-golden for each:

- **Quote 07 line 1 (PM-C-2.2 peat):** model lifted `"2.2 cu ft compressed bale"` to pack_size, golden had `"2.2 cu ft bale"` with `"compressed"` left in description. Model is right — `"compressed"` describes the bale's pack state (compressed bale ≈ 2.2 cu ft, fluffs to ~4 cu ft), so it belongs in pack_size as part of the physical-pack specification. Flipped golden. **2 mismatches close out as Bucket A.**
- **Meridian line 7 (TWINE-NAT-9K):** description `"Natural fiber baling twine, 9000 ft per bale"`, model left it intact, pack_size=null. Trigger 1 of the existing rule literally lists `"per bale"` as an example. Pure compliance gap.
- **Pacific line 8 (STRAP-PP-58):** description `'Polypropylene Strapping, 5/8" x 9000 ft, machine grade'`, UoM column `ROLL`. Trigger 3 territory but the rule's example is a simple `"50 lb"` + `BAG`; multi-dim size mid-comma-list with flanking adjectives doesn't pattern-match well.

**Failure-mode lesson:** **class-level frequency ranking can hide heterogeneity within a "class".** The 6 mismatches split 2/2/2 across three different shapes — one was a golden bug, two cases share Trigger 1 weak compliance, two cases share Trigger 3 example-shape-too-narrow. Per-fixture inspection is mandatory before deciding what to fix; the harness frequency table tells you *where* to look, not *what* to do.

**Principle reframe for the pack_size rule (`prompts.py:39–44`).** Rewrote the lead from "captures pack/packaging info" to "the complete physical-pack specification — the dimensions, count, density modifiers, and packaging-form noun that together describe how the product is packed. Kept as a single coherent field. Description carries product identity; pack_size carries how it's packed." Triggers stay as priority-ordered applications of the principle. Trigger 1 examples updated to call out density modifiers and mid-comma-list span extraction; Trigger 3 rewritten with multi-dim size handling and explicit "keep flanking adjectives in description" rule.

**Train/test contamination caught and fixed.** First draft of the reframed rule used three verbatim phrases from the eval set as concrete examples (`"2.2 cu ft compressed bale"` from Quote 07, `"9000 ft per bale"` from Meridian, `'5/8" x 9000 ft'` from Pacific) — direct train/test contamination, since even paraphrased they teach the model to memorize specific eval strings rather than learn the pattern. Standard practice: **rule wording uses generic/archetypal shapes; concrete instances live only in the held-out demo.** Sanitized to `"40 lb fluffed bale"`, `"800 ft per spool"`, `'3/4" x 6000 ft'` — none in eval. Verified via grep over `data/synthetic_quotes/` that all replacement strings are absent.

**Failure-mode lesson:** **prompt examples are easy contamination vectors when drafting concrete rule examples** — the eval values are top of mind so they leak in. Worth a checklist habit going forward: any time a rule body gets a new concrete example, grep eval before committing.

**Demo enrichment.** Added two lines to `data/prompt_examples/marian_demo.{txt,expected.json}` using non-corpus products:
- `MAG-PS-09 — Pine shavings bedding, 9 cu ft fluffed bale` + UoM `BALE` → desc=`"Pine shavings bedding"`, pack_size=`"9 cu ft fluffed bale"`. Demonstrates Trigger 1 with a density modifier.
- `MAG-DT-12 — Poly drip tubing, 1/2" x 500 ft, pressure-rated` + UoM `SPOOL` → desc=`"Poly drip tubing, pressure-rated"`, pack_size=`'1/2" x 500 ft spool'`. Demonstrates Trigger 3 with multi-dim mid-comma-list size and flanking-adjective preservation.

Both products grepped clean against the eval corpus. The demo's role is concrete instances of the shapes the rule describes — covers the two failing eval cases by analogy without teaching the model their specific strings.

**Bucket C count after this session:** 30 mismatches (32 prior − 2 from Quote 07 golden flip). 4 of those 30 are the Meridian + Pacific pack-noun cases targeted by the principle reframe + demo enrichment.

**Next:** harness re-run to see what moves on Meridian + Pacific. Watch for (a) Trigger 1 firing on `"X per bale"` shape (Meridian), (b) Trigger 3 firing on multi-dim mid-description size + UoM-column noun (Pacific), (c) no regression on the 10+ fixtures where pack-noun rules already worked. If the reframe lands, move to currency over-default (next class by count) or substantive `raw_notes` paraphrasing (next class by spread).

## 2026-05-04 — prompt sweep + currency salience regression

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

**Contamination audit caught corpus-verbatim examples in the new draft AND pre-existing in the prompt.** First draft of the counter-rule used `"poly drum liner"`, `"drum pump"`, `"poly tote, 275-gal IBC"`, `"2.2 cu ft compressed bale"` — all verbatim from the eval set (quote_09, quote_12, quote_07). Re-checked all proposed examples via `rg --no-ignore -i "<term>" data/synthetic_quotes/` — replaced with synthetic equivalents, all grepped clean. **Also caught two pre-existing leaks in the same passage:** `"55-gal drum"` and `"Multi-purpose lubricant, 1 gallon"` were already in the prompt and both verbatim from the corpus (quote_11, quote_meridian). Swapped to `"200-l drum"` / `"Industrial cleaner, 5 liters"` — synthetic, grepped clean.

**Failure-mode lesson — contamination audit needs to cover *existing* prompt content, not just new edits.** Old-example leaks survive across editing rounds because the grep habit only triggers on additions. Worth a periodic full-prompt sweep against `data/synthetic_quotes/` to catch latent leakage. The prompt itself is small enough that this is cheap.

**Currency salience regression — 0 → 8 mismatches on `quote_precision_bearings`.** Post-edit harness showed 96.4% net (above baseline despite the regression). Investigation: 8 of 8 lines in precision_bearings predicted `"USD"` despite source containing only `$` symbols and no ISO code (Greenville SC supplier, Reno NV ship-to). Three consecutive single-fixture re-runs all reproduced — not Haiku stochasticity, real prompt regression. The original currency rule's wording (*"Do not default to USD when no ISO code is stated"*) had previously held compliance; the edit lengthened the field-specific list above it, pushing currency further down and degrading attention.

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

## 2026-05-04 — inventory CSV + LangGraph plan

Inventory master at `data/inventory/inventory.csv`: 146 rows (51 anchors + 95 filler), 12 columns. Two-pass prompt to claude.ai — anchors-first to bound single-shot risk on row count + distribution constraints, filler in a second turn applying constraints across the full set. All 51 anchor SKUs from the eval corpus present verbatim. `KMEAL-44` absent on purpose (preserves the NutriGrow substitution exception case). Validated: unique SKUs, canonical UoM/category sets, all prices parse Decimal, all dates ISO. Distribution: 5 low-stock, 3 empty-currency, 4 stale-dated, 2 CAD anchors.

Three exception signals baked in by design (worth knowing about as match logic lands):
- `KMEAL-50` / `PEAT-BALE-3.8` in CAD — fires currency mismatch against corpus quotes that emit `currency: null` (Pacific Coast Amendments uses bare `$`).
- `STRAP-PP-58` master pack `"6000 ft coil"` vs corpus `'5/8" x 9000 ft'` / UoM `ROLL` — fires pack-size variance + noun divergence (coil vs roll).
- `AL101` master pack `"5 kg pail"` vs corpus 50 kg order — tests bulk-vs-pail handling on the match node.

v1 schema is denormalized — `last_paid_*` and `on_hand_qty` / `reorder_point` / `lead_time_days` collapse what an ERP would split into `products` / `price_history` / `inventory_levels` tables. Explicit v1 simplification; production split named in the README design-decisions section.

**Plan from here.** Product Pydantic model + CSV loader (in-memory `dict[str, Product]`) → state types (`QuoteWorkflowState`, `MatchResult`, `Exception_`) → hand-authored LangGraph extract subgraph (`extract_node` + `ToolNode` + `should_continue`; speak-in-primitives, not `create_react_agent`) → concept-mapping doc at `docs/from_primitives_to_langgraph.md` → stub match/flag/approval nodes → compile with `MemorySaver` + `interrupt_before=["approval_node"]` → end-to-end run on one fixture. Real match/flag logic, eval harness wrapped around graph runs, Supabase migration, FastAPI HITL endpoint follow as pace allows — ordered next-steps, not hard-scheduled to days.

## 2026-05-04 — Product model + inventory loader

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

**Next:** state types (`QuoteWorkflowState`, `MatchResult`, `Exception_`) and the hand-authored extract subgraph.

## 2026-05-04 — LangGraph extract subgraph + smoke tests

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

**Next:** concept-mapping doc prose. Then real match + flag logic against the in-memory product master, with `MatchResult` and `Exception_` schemas firming up.

## 2026-05-04 — graph.py concept mapping

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

## 2026-05-04 — postgres schema + migrations

Local docker postgres + hand-rolled SQL migrations + DB-as-master for the product catalog. End-to-end works against `procure_agent` namespace; 146 products seeded from `data/inventory/inventory.csv`. Full suite at 26 passing (4 new DB tests).

**Files landed.**
- `docker-compose.yml` — `postgres:16`, named volume, `pg_isready` healthcheck.
- `migrations/0001_init.sql` — `procure_agent` schema, `category` + `uom` enums (mirror the `StrEnum`s in `schemas.py`), tables: `products`, `quotes`, `quote_line_items`, `agent_runs`. UUID PKs via `gen_random_uuid()`. `tier_prices` is `jsonb`. Partial indexes on `quote_line_items.supplier_sku` / `requested_sku` (skip the NULLs).
- `migrations/0002_seed_products.sql` — 146-row `INSERT` generated by `scripts/generate_seed_sql.py` from the CSV. Committed; regenerate when CSV changes.
- `scripts/migrate.py` — psycopg-direct runner. Bootstraps `procure_agent.schema_migrations` itself (separate from `0001_init` so the runner owns its own tracking), applies pending `*.sql` in lexical order, idempotent.
- `scripts/generate_seed_sql.py` — reads inventory via the existing `load_products()` loader (shares Pydantic validation with the runtime path), emits the seed migration.
- `tests/test_migrations.py` — drops and re-migrates the schema, asserts version recording, row count vs. CSV, AL101 anchor row column-for-column, and idempotent re-run.
- `.github/workflows/ci.yml` — postgres service container + `DATABASE_URL` env so DB tests run in CI.
- `.env.example` — both URL forms documented (plain `localhost` for normal docker hosts, OrbStack note for the VM-on-Mac case).

**Decisions worth keeping.**
- **(A) Hand-rolled SQL migrations, not alembic.** Real DDL on the page in the repo, no ORM coupling for schema, plain text portable to Supabase migrations later. Trade-off: no `--autogenerate`, downgrades not modeled. With a handful of expected migrations at v1, the tooling overhead doesn't amortize.
- **(B) DB as master, CSV as seed source via generator script.** The CSV stays human-editable; the SQL is the migration. Keeping the generator in `scripts/` (not auto-running at startup) means the seed file is a committed artifact a reviewer can read directly.
- **(C) `category` and `uom` as enums on `products`; plain `text` for `quote_line_items.uom`.** Inventory is curated, so enum drift is a real signal to catch at load time. Extracted quote UoMs may be non-canonical (`gallons`, `gal.`, `Gal`); enum-rejecting them at INSERT would mask data-quality issues that the eval harness is supposed to surface.
- **(D) Runner bootstraps `schema_migrations` itself, separately from `0001_init.sql`.** First-run chicken-and-egg: the tracking table has to exist before the first migration's row is recorded. Cleaner than threading the bootstrap into 0001.
- **(E) Schema scope for v1.** `products`, `quotes`, `quote_line_items`, `agent_runs` only. `supplier_name` stays denormalized on `quotes` until supplier-onboarding lands. `boms` and `purchase_orders` deferred. `agent_runs.langsmith_run_id` is the seam to LangSmith for traced-sample runs.

**OrbStack environment note.** Docker daemon runs on the Mac, not in this Linux VM. Installed `docker.io` for the CLI, disabled the VM-local daemon, set `DOCKER_HOST=unix:///opt/orbstack-guest/run/docker.sock` in `/etc/profile.d/`, chowned that socket to `:docker` and added the user to the `docker` group. The published port is on the Mac's loopback, so from inside this VM the container is reachable at `procure-pg.orb.local:5432` (OrbStack auto-DNS) — `localhost:5432` and `host.docker.internal:5432` both miss it. `.env.example` documents the portable case (`localhost`); local `.env` uses the orb DNS name.

**Held drift / not done.**
- `LangGraph` `MemorySaver` still in `graph.py`; `PostgresSaver` swap deferred until match/flag bodies and the FastAPI HITL endpoint exist (no resumable run to checkpoint until then).
- `sqlalchemy` is still in `pyproject.toml` deps but unused. Decide on the query layer (psycopg directly vs. sqlalchemy core) when the match node lands.
- Socket permissions persistence across an OrbStack VM restart not verified — may need a systemd path unit if `chown` doesn't survive.

**Next:** match-node body. Read `quote.line_items[*]`, look up by SKU against `procure_agent.products`, populate `MatchResult` with whatever the schema needs to firm up. First node where the DB earns its keep.

## 2026-05-05 — query layer + match/flag state shape

psycopg-direct query layer against `procure_agent.products`, pg_trgm enabled with GIN indexes for fuzzy SKU/description match, and `state.py` refactored to firm up `MatchResult` / `Exception_` / the cascade enum. Match/flag node bodies still no-op stubs; their docstrings now spell out the contract. Full suite at 34 passing (8 new DB tests).

**Files landed.**
- `pyproject.toml` — `sqlalchemy` removed (unused; psycopg-direct picked for the query layer).
- `migrations/0003_pg_trgm.sql` — `CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public`, plus GIN trigram indexes on `products.sku` and `products.description`.
- `src/procure_agent/db.py` — `connect()` context manager (reads `DATABASE_URL`, sets `row_factory=dict_row` and `search_path=procure_agent,public`), `get_product()`, `find_products_by_sku_similarity()`, `find_products_by_description_similarity()`. All return `Product` instances; the trigram `score` column is silently dropped by Pydantic's default `extra='ignore'`.
- `src/procure_agent/state.py` — added `MatchMethod` (StrEnum, 6 values: one per cascade rung + `unmatched`) and `ExceptionKind` (StrEnum: `unmatched`, `price_variance`, `currency_mismatch`, `pack_size_drift`, `uom_mismatch`). `Exception_` is now `(kind, detail)`; `MatchResult` is now `(line_index, matched_sku, match_method, confidence, flags)`. `QuoteWorkflowState.exceptions` removed — flags live on each `MatchResult`.
- `src/procure_agent/graph.py` — `match_node` / `flag_node` docstrings spell out the cascade order, short-circuit semantics, and the four flag types so the contract is in the file.
- `tests/test_db.py` (8 passing) — exact lookup hit + miss; SKU similarity recovers `STRAPPP58` → `STRAP-PP-58`; ranks exact match first; respects `limit`; garbage input returns empty; description similarity finds `STRAP-PP-58` from "polypropylene strapping" and ranks `AL101` first for "Aloe vera extract food grade".
- `tests/test_migrations.py` — expected version list derived from disk (`migrations/*.sql` stems) so adding a migration no longer breaks an unrelated test.

**Decisions worth keeping.**
- **(A) psycopg-direct over SQLAlchemy core.** Three query shapes today (exact lookup, fuzzy SKU, fuzzy description), no joins until `suppliers` / `purchase_orders` land. ORM would add a parallel `ProductORM` model that converts to the existing `Product` Pydantic for no gain; query builder doesn't pay for itself at this query count. Same SQL runs unchanged against Supabase. Can revisit if join count climbs.
- **(B) `pg_trgm` installed in `public`, not `procure_agent`.** Explicit `WITH SCHEMA public` so the `similarity()` function and `%` operator resolve regardless of search_path. Supabase pre-installs it in `extensions`; the `IF NOT EXISTS` short-circuits there and no-ops.
- **(C) GIN trigram indexes on both `products.sku` and `products.description`.** Both columns are queried by similarity in the cascade; without GIN, `similarity()` is a sequential scan. Cheap insurance even at 146 rows; mandatory if the catalog grows.
- **(D) Flags-on-MatchResult, not flat exceptions list.** A flag without a match it varies from has no domain meaning — the data is naturally hierarchical. Removes `line_index` from `Exception_` (one fewer field to keep in sync), and "show every flag on this quote" is one flatten: `[f for m in match_results for f in m.flags]`. Quote-level flags (header drift, supplier address mismatch) are out of scope until supplier-onboarding ships.
- **(E) Short-circuit cascade with granular `MatchMethod`.** Six values, one per cascade rung: `supplier_sku_exact` → `requested_sku_exact` → `supplier_sku_fuzzy` → `requested_sku_fuzzy` → `description_fuzzy` → `unmatched`. Eval and HITL can distinguish a strong exact-SKU match from a weak description-fuzzy hit. Supplier_sku precedes requested_sku because a supplier quote's supplier_sku is what they actually offered to sell.
- **(F) `match_node` attaches the `UNMATCHED` flag itself; `flag_node` only handles divergence flags (price/currency/pack/UoM).** Keeps each node's contract narrow: match decides identity, flag decides divergence. Both return `{"matches": [...]}` so flag's enriched list replaces match's via the default LangGraph reducer.
- **(G) `test_migrations` derives expected versions from disk.** The first cut hard-coded `["0001_init", "0002_seed_products"]`; adding `0003_pg_trgm` broke the test for unrelated reasons. Reading `migrations/*.sql` stems makes the assertion durable across future migrations.

**Held drift / not done.**
- `match_node` and `flag_node` still no-op stubs returning `{}`. Docstrings firm; bodies land next session.
- pg_trgm `threshold=0.3` default in `db.py` is a guess. Tune against the synthetic-quote corpus once the eval harness wraps graph runs.
- `confidence` semantics: 1.0 for exact, trigram score for fuzzy, 0.0 for unmatched. May want to migrate unmatched to `None` once the HITL UI exists and "no confidence" needs to render distinctly from "zero confidence."
- pack_size / UoM normalization rules for the flag node not picked yet — open question is whether to canonicalize at match time (keep DB and quote in same shape) or at flag time (compare-with-tolerance like the eval comparator does for prose).

**Next:** `match_node` body — straight cascade calling into `db.py`. Then a couple of integration tests in `tests/test_graph.py` exercising exact / fuzzy / unmatched paths. Then `flag_node` body for the four comparison flags.

**CI miss.** First green CI run on `main` after the migrations push went red: all 8 `tests/test_db.py` cases failed with `relation "products" does not exist`. Workflow stood up the postgres service container and exported `DATABASE_URL` but never ran `scripts/migrate.py` between `uv sync` and `uv run pytest`. `test_migrations.py` masked it because that suite spins up its own fresh DB and runs the migrator inline; `test_db.py` connects to the shared service DB and assumed the schema was there. Fix: one `Apply migrations` step in `.github/workflows/ci.yml` before the test step. Lesson: when a suite splits between "owns its own DB" and "uses the shared one", a passing migration test is not evidence the shared DB has been migrated.

## 2026-05-05 — match_node body + ScoredProduct refactor

**Shipped.**
- `match_node` body lands. Cascade explicit, five tiers + UNMATCHED fallthrough, short-circuit per line. Split into `_match_line(conn, line_index, line)` (the cascade) and `match_node(state)` (opens connection, maps the helper over `state["quote"].line_items`, returns `{"matches": [...]}`). One `connect()` per node, threaded into every line.
- `db.py` fuzzy helpers now return `list[ScoredProduct]` (`@dataclass(frozen=True, slots=True)` wrapping `Product` + trigram `score`). Was `list[Product]` with `score` silently dropped via Pydantic's `extra='ignore'` — leaving SQL-computed similarity on the floor. `match_node` reads `hits[0].score` straight into `MatchResult.confidence`, no second roundtrip. `get_product` unchanged (exact lookup has no score). New `_hydrate_scored` helper strips `score` from the row dict before model_validate. `test_db.py` updated to read `hit.product.sku` / `results[0].product.sku`; new `test_sku_similarity_score_in_unit_range` proves the score round-trips through the dataclass; existing exact-match test tightened to assert score 1.0.
- Smoke against `quote_pacific_amendments_2026-04-25.expected.json` — 8/8 lines hit tier 1 (`supplier_sku_exact`) at confidence 1.0. Helper works end-to-end against real Postgres. Tiers 3–5 (fuzzy + unmatched) untested by this run because Pacific Amendments is the happy-path fixture.

**Decisions worth keeping.**
- **(A) `ScoredProduct` over raw `(Product, float)` tuples.** Tuple unpacking gets ugly when threaded through several callers. Three-line frozen dataclass keeps `match_node` legible (`hit.product.sku`, `hit.score`) and gives the eventual HITL "did you mean…?" UI a clean shape too. Real reason for the refactor isn't roundtrip avoidance — it's that `similarity()` is already computed in SQL and throwing it away on the way out leaks information the cascade needs.
- **(B) Helper + node split, not one fat node.** `_match_line` is the part defended in an interview ("walk me through how matching works"). Lifting it out names it and lets `match_node` read as "open conn, map over lines." Three-line node body, ~70-line helper.
- **(C) Explicit five-tier cascade over data-driven loop.** `[(method, callable), ...]` table iterated until something hits is cute; reading five `if` blocks is what someone defends under questioning. The cascade *is* the domain logic. Verbosity is the feature.
- **(D) 70-line helper over the 40-line cap.** Each tier is a repeating-shape block (guard → query → return MatchResult). Slimming options all hurt: a "build MatchResult" constructor helper hides which `MatchMethod` goes where; a data-driven loop is option (C). Land the violation as architectural exception, flag if a reviewer pushes.
- **(E) One connection per node, threaded into every line.** Don't open per-line. The DB tests already prove the helpers reuse a connection cleanly; pooled connect cost dominates the per-line query cost otherwise.
- **(F) Don't catch DB errors in `match_node`.** `psycopg.OperationalError` propagates. The node failing loudly is right; silent UNMATCHEDs would mask DB outages as data-quality issues.
- **(G) UNMATCHED `Exception_.detail` includes all three signals tried** (`supplier_sku`, `requested_sku`, `description` with `!r` so `None` shows up unambiguously). The HITL operator reads this string — they need to know what the agent saw, not just that it gave up.

**Held drift / not done.**
- Fuzzy + unmatched cascade tiers aren't covered by smoke yet. Need a fixture with a typo'd or substituted SKU (the handoff edge-case list has these — `quote_acme_fasteners` typo case is a candidate) to fire tiers 3–5 + the UNMATCHED fallthrough.
- Match integration tests in `tests/test_graph.py` deferred to next session. Pure-function checks today (no API), exercising exact / fuzzy / unmatched against the seeded DB and the three baked-in inventory signals.
- pg_trgm `threshold=0.3` default unchanged. Still a guess; tune once eval wraps the graph.
- `flag_node` still no-op stub. Bodies land after the match integration tests.

**Next:** match integration tests in `tests/test_graph.py` exercising the three cascade outcomes (exact / fuzzy / unmatched) against the seeded DB. Then `flag_node` body for the four comparison flags (PRICE_VARIANCE, CURRENCY_MISMATCH, PACK_SIZE_DRIFT, UOM_MISMATCH).

## 2026-05-05 — cascade tier tests + normalize + flag_node

Closed out match/flag node work in one push. match_node integration coverage for tiers 3–5 + UNMATCHED fallthrough, then a small `normalize` module with tolerance comparators (`same_uom`, `same_pack_size`), then `flag_node` body wired through them with the four-flag cascade. Suite at 82 passing (+4 match_node, +32 normalize, +11 flag_node).

**Files landed.**
- `tests/test_graph.py` (+15) — four cascade rung tests (tier 3 supplier_sku fuzzy via `STRAPPP58` → `STRAP-PP-58`, tier 4 requested_sku fuzzy with `supplier_sku=None` skipping by guard, tier 5 description fuzzy via `"Aloe vera extract food grade"` → `AL101`, UNMATCHED with the flag detail proving every tried signal). Then 11 `flag_node` integration tests: clean / variance above + below threshold / currency / pack_size substantive + cosmetic / uom substantive (Pacific Amendments STRAP-PP-58 ROLL scenario) + cosmetic / all-four-flags / UNMATCHED passthrough / multi-line independence. DB-skip is per-test (`_require_db` fixture, function-scoped) so the existing pure-function smoke tests still run when postgres is unreachable.
- `src/procure_agent/normalize.py` — `same_uom(a, b)` and `same_pack_size(a, b)`. Pure leaf utilities, no DB, no Pydantic. Private canonicalizers; public API is the two predicates. UoM uses a static alias map (closed set of 7 from the `UoM` StrEnum); pack_size collapses cosmetic drift via lowercase + digit-letter split + whitespace squeeze + trailing-punct strip.
- `tests/test_normalize.py` (+32) — table-driven via `pytest.mark.parametrize`. Symmetry asserted on every case. Off-canonical tokens (`ROLL`, `box`) intentionally don't alias-map so they fire UOM_MISMATCH against any catalog UoM. `same_pack_size(None, None)` is True; asymmetric None is False.
- `src/procure_agent/graph.py` — `flag_node` body: one `connect()` per node, mutates `match.flags` in place, returns `state["matches"]`. `PRICE_VARIANCE_THRESHOLD = Decimal("0.10")` at module level. UNMATCHED lines pass through untouched (their flag was attached by match_node).

**Decisions worth keeping.**
- **(A) Tolerance comparators in their own module, used only at flag time.** Schema decision C (extracted UoM is `text`, not enum) keeps drift visible to the eval harness; the `same_*` predicates collapse cosmetic drift only at flag emission. DB still stores `"Gal"` / `"5kg pail"` verbatim. Pack-size canonicalization at extraction time was the alternative — punted on the rabbit hole of building a reliable parser when the comparator pattern already worked for the eval prose comparator.
- **(B) Off-canonical UoM tokens fall through unchanged.** The alias map is curated for the 7 canonical values only. A token like `roll` or `box` deliberately survives normalization and fires UOM_MISMATCH against any catalog UoM — that's the Pacific Amendments STRAP-PP-58 ROLL case as a feature, not a bug.
- **(C) Drop the parallel `enriched` list.** The loop is side-effecting on `match.flags`; building a parallel list documented intent but was paperwork. `return {"matches": state["matches"]}` says what it does.
- **(D) Mutate `match.flags` in place.** `MatchResult` is not `frozen`, so `.append` works. Trade-off: not strictly pure, but a `model_copy(update=...)` rebuild adds ceremony for no observable difference. Land the violation; revisit if a future reducer change makes it bite.
- **(E) v1 lets every divergence flag fire on `DESCRIPTION_FUZZY` matches.** A 0.32-confidence "this might be the same product" plus a PRICE_VARIANCE flag is noisy, but per call: let everything fire, see what surfaces at HITL time. Could gate on `confidence >= threshold` later if the noise dominates the signal.
- **(F) Both-None pack_size is no-flag; asymmetric-None fires.** A supplier asserting "5 kg pail" against a catalog row with no recorded pack_size is a divergence the operator should know about; a clean both-omit isn't.
- **(G) DB-skip is per-test, not module-scope.** test_graph.py mixes pure-function smokes with DB-required cascade and flag tests. Module-autouse skip would have hidden the structural tests under a stopped postgres; per-test injection of `_require_db` keeps them running.

**Held drift / not done.**
- Currency comparison is exact-match (`!=`). Two known false-positives: bare-symbol `$` extracted as None vs. catalog `"USD"`, and case drift (`"usd"` vs `"USD"`). Per (E), let v1 fire and see how often it bites.
- pg_trgm `threshold=0.3` still default. Untouched until the eval harness wraps the graph and we have a baseline.
- The asymmetric-None pack_size flag per (F) might be noise on prose-only quotes that don't restate pack size. Watch.
- End-to-end smoke through the full graph (extract → match → flag) with a real Anthropic call still untested; only sub-node coverage so far.

**Next:** wrap the full graph in the eval harness — extract → match → flag → interrupt against the synthetic quote corpus. Observe failure modes, drop them in here. Tune trigram threshold once a baseline exists. After: FastAPI HITL endpoint.

**README draft — node naming + reconciliation split.**

Stashing the design-decisions narrative now so the README pass doesn't rebuild it from scratch. The original plan listed `parse → extract → match → reconcile → flag → approval`; what shipped is `extract → match → flag → approval`. Worth being deliberate about why before the architecture diagram locks it in.

*Architecture-diagram caption (proposed):*

> The graph runs `extract → match → flag → approval`. `match` and `flag` are grouped under a brace labeled "reconciliation."

*Design-decisions bullet (proposed, ready for ruthless revise):*

> **Reconciliation splits into identity and divergence.** `match` decides which catalog product a quote line refers to (cascade through five SKU/description tiers, UNMATCHED on fallthrough). `flag` decides where the matched offer diverges from our last reference (price >10%, currency, pack size, UoM). Splitting them earns trace separability — each is its own LangSmith span — independent eval scoring (identity precision vs. flag-emission precision), and a HITL surface that can render identity decisions and divergence flags as two sections. A merged `reconcile` node would have collapsed both into one span.

*Drift-from-original-plan notes worth a sentence in design-decisions or "what changed during the build":*
- `parse` collapsed into `extract` — a one-line JSON transform off the model's terminal turn doesn't need its own node.
- `reconcile` was planning scaffolding; once built, identity and divergence had naturally distinct contracts and merging them would have hidden which decision a regression came from.

## 2026-05-05 — full-corpus eval baseline + cascade/flag observability

First end-to-end run of the full graph (`extract → match → flag → interrupt`) against all 14 synthetic-quote fixtures (65 line_items, ~12 Sonnet calls). Goal was observation — corpus-level cascade-tier distribution and flag-firing rates — not tuning. Artifact: `evals/runs/20260505T181616Z.json`.

**Headline numbers.**
- Field-match: **98.0%** (768/784) — extraction baseline holds across the corpus.
- Cascade: 54 supplier_sku_exact, 1 requested_sku_exact, 0 supplier_sku_fuzzy, 0 requested_sku_fuzzy, 3 description_fuzzy, 7 unmatched.
- Flags raised: 52 currency_mismatch, 45 price_variance, 27 pack_size_drift, 7 unmatched.

**Cascade is bimodal in this corpus.** SKU-bearing fixtures (11 of 14) hit `supplier_sku_exact` on every line; the 3 prose fixtures with all-`None` supplier_skus (`09_date_formats`, `11_leadtime_prose`, `12_revised`) drop straight to `description_fuzzy` or `unmatched`. **Both fuzzy SKU tiers (3, 4) saw zero hits** — the corpus has no SKU-typo cases, so tier 3/4 is unit-test-only behavior right now. Adding one substitution-typo fixture (e.g., `STRAPPP58` from the unit test promoted into a quote) would close the cascade-coverage gap.

**Description_fuzzy is producing wrong matches.** All 3 hits land at confidence 0.33–0.40, into catalog SKUs that aren't actually right:
- `09_date_formats L0/L1` → `LINER-DRUM-CL` (catalog: liner, roll of 50). Quote prose: "drum heat seal closures, kraft" / "drum 1/2-mil liner, FDA". `LINER-DRUM-CL` shares the "DRUM" / "LINER" tokens by trigram coincidence; it isn't the same product. Bogus divergence flags cascade: price_variance 92.3% / 94.9%, plus pack_size_drift on the asymmetric-None.
- `11_leadtime_prose L2` → `SULK-50` (catalog: sulk, 50 lb). Quote prose: "Sulfur, agricultural-grade, 50 lb bag". Trigram match through "sulf"/"sulk" letter overlap; wrong product. Cascades a 53.8% price_variance.

This is **the prior session's decision (E) playing out exactly as predicted**: low-confidence description-fuzzy matches cascade bogus divergence flags, and the noise looks like signal at HITL time. Two fixes worth weighing: (a) raise the pg_trgm threshold from 0.3 → 0.45 (would push these to UNMATCHED, where they belong); (b) gate divergence-flag emission on `confidence >= 0.5` in `flag_node` (keeps the match for HITL "did you mean…?" but suppresses bogus price/pack flags). (a) is structurally cleaner — UNMATCHED already encodes the "we didn't find it" signal; (b) leaks the cascade's confidence into flag logic.

**Currency_mismatch is 90% noise.** Of 52 currency_mismatch flags, **47 are `None vs USD`** — the bare-`$` extraction-shape false-positive flagged earlier as held drift. 4 are legitimate `CAD vs USD` (nutrigrow + one Canadian quote line). 1 is `None vs CAD`. The flag is firing on 90% of matched lines and the noise dominates the signal completely.

The cleanest fix is at extraction: bare `$` in dollar-formatted prose should canonicalize to `"USD"` (not `None`). That's a prompt change, not a flag-logic change. The alternative — comparator treating `None ≈ USD` as cosmetic when the source has a bare symbol — leaks extraction concerns into flag code. Defer the prompt edit until the per-field audit pass so we don't flush other tuning.

**Pack_size_drift is mostly substantive.** Of 27 firings: **8 asymmetric-None** (catalog has data, quote prose didn't restate it — the prior session's predicted noise pattern, confirmed); **19 both-real** divergences. The both-real bucket is mostly legitimate, but a few are cosmetic that `same_pack_size` should arguably collapse:
- `'1 gal' != '1 gal jug'` — same numeric, container token missing on the quote side
- `'drum (55 gal)' != '55 gal drum'` — extraction word-order (also surfaces as a value_mismatch on extraction; root cause is upstream)
- `'2.2 cu ft compressed bale' != '2.2 cu ft bale'` — qualifier difference, possibly substantive (compressed peat ships denser)
- `'bag' != '30 lb bag'` — partial pack_size missing the weight (this IS substantive — a bare "bag" with no weight is ambiguous)

The `same_pack_size` predicate's tokenizer (lowercase + digit-letter split + whitespace squeeze) doesn't currently collapse word-order or trailing-token differences. Keep as-is for v1; revisit if the cosmetic cases bite at HITL.

**The cascade caught one real substitution.** `quote_nutrigrow_2026-04-25 L4`: supplier offered `KMEAL-44` (their packing, 44 lb bag, missing from product master), buyer's requested SKU was `KMEAL-50` (catalog hit). Match cascade: tier 1 supplier_sku_exact misses → tier 2 requested_sku_exact hits at confidence 1.0. `pack_size_drift` then fires correctly: `44 lb bag != product 50 lb bag`. **This is exactly the supplier-substitution workflow the cascade was designed for** — supplier and buyer transacting against different SKUs for the same product, divergence flagged at the packing level. Canonical "why we cascade" example for the README.

**Extraction-side mismatches surfaced (15 value_mismatch + 1 format_drift).** Most are `raw_notes` Sonnet stochasticity (already-known noise from prior side-by-side runs). Material ones:
- `terragreen` × 3: `'50# bag'` extracted verbatim vs. golden `'50 lb bag'` — the `#` pound-abbreviation convention isn't being normalized. Prompt-tuning candidate (per the prompt-edit checklist).
- `pacific_amendments`: `'Sphagnum Peat Moss, compressed'` description vs. golden `'Sphagnum Peat Moss'`, with the `compressed` qualifier instead landing in pack_size — the quote prose put `compressed` in the description column and the model split it ambiguously. Edge case.
- `quote_08 L0`: `'drum (55 gal)'` vs. golden `'55 gal drum'` — extraction word-order. Same root cause as the cosmetic pack_size_drift firing above.

**Failure modes that did NOT show up in the corpus.**
- No supplier_sku_fuzzy or requested_sku_fuzzy hits — the cascade's typo-recovery tiers are unexercised.
- No quote-level field failures (currency at quote-level, valid_through, dates) — extraction stable.
- No FAIL fixtures — graph end-to-end ran clean on all 14.

**Decisions for the README design-decisions section.**
- Lead the cascade narrative with the **nutrigrow KMEAL-44→KMEAL-50 substitution catch** — it's the single most legible "why this architecture" moment in the corpus.
- Acknowledge the **description_fuzzy false-positive failure mode** explicitly. Either (a) document the pg_trgm threshold tune that fixes it, or (b) keep the v1 behavior and call out "low-confidence description matches cascade noisy divergence flags" as a known trade-off the HITL operator is in the loop for. Either is defensible; pick before the section locks.
- Acknowledge the **currency-mismatch extraction-shape noise** the same way. The README can either show the post-fix numbers or be honest about v1 noise; the latter is more credible if the demo is going to surface a `None vs USD` flag.

**Held drift / not done this session.**
- pg_trgm threshold still 0.3. Decision deferred.
- Bare-`$` → `USD` extraction normalization deferred.
- No SKU-typo fixture in the corpus to exercise tiers 3–4 of the cascade. Worth adding.
- Asymmetric-None pack_size flag not gated; per (F), watching it.
- `evals/run.py` doesn't compute extraction-vs-match correlation (e.g., when did extraction value_mismatch *cause* a downstream match/flag failure?). Today's analysis was manual via the artifact JSON. If we run the eval more than 2-3 more times, worth adding a "joint failures" report.

**Next:** FastAPI HITL endpoint + frontend. The eval harness is the observability tool to run before/after each tuning change; today's artifact is the baseline to diff against.

## 2026-05-05 — pg_trgm threshold (description) 0.3 → 0.45

Took fix (a) from yesterday's description_fuzzy noise diagnosis: bumped `find_products_by_description_similarity` default threshold to 0.45 in `src/procure_agent/db.py`. Left the SKU threshold at 0.3 (cascade had zero fuzzy SKU hits in the corpus, so re-tuning it would be speculative). Re-ran the full eval; new artifact `evals/runs/20260505T183700Z.json`.

**Diff vs. baseline (`20260505T181616Z.json`).**
- Cascade: `description_fuzzy=3 → 0`, `unmatched=7 → 10`. The 3 wrong matches (LINER-DRUM-CL ×2 in `09_date_formats`, SULK-50 in `11_leadtime_prose`) all sat below 0.45 (0.333 / 0.362 / 0.404) and now correctly land in UNMATCHED.
- Flags: `price_variance 45 → 42` (the bogus 92.3% / 94.9% / 53.8% drifts gone), `pack_size_drift 27 → 25` (the asymmetric-Nones on the LINER-DRUM-CL hits gone), `currency_mismatch 52 → 49` (the `None vs USD` flags on the same 3 lines gone — these would have been killed by fix (b) anyway).
- `unmatched` flag count: `7 → 10`, exactly tracking the cascade movement.
- No regression on `supplier_sku_exact=54` or `requested_sku_exact=1`. Field-match holds at 98.0%.

**What this means for the HITL surface.** UNMATCHED is now the only signal carrying the "we didn't find this product" decision — no low-confidence fuzzy hits leaking through to the flag layer with bogus divergence. The HITL queue should render those 10 lines as "did you mean / create new SKU" prompts, not as "review this 95% price drift on a product we're not actually sure we matched."

**Next:** the bare-`$` → `USD` extraction prompt edit. After that, today's artifact gets superseded by the post-prompt-edit run as the new locked baseline.

## 2026-05-05 — currency rule pivot, flag gating, prompt caching → locked baseline

Three changes landed in sequence. New artifact `evals/runs/20260505T193415Z.json` is the locked baseline.

**(1) Currency rule pivot — strict-null → application-default-USD.**

Initial draft was a strict rule (bare `$` → USD; no symbol → null) with priorities 1-4 covering ISO codes, compound symbols, bare `$`, and bare `€`/`£`/`¥`. First post-edit eval revealed extraction was over-predicting USD on no-symbol fixtures (q08, q10 CSVs of plain numbers; terragreen ALFM-50 with siblings using `$`) — 14 lines diverged from strict-rule goldens, dragging field-match to 95.8%.

Reframed: this tool serves US-anchored procurement workflows. The strict rule was over-engineered against a deployment context that doesn't exist (truly currency-ambiguous SMB workflows). The "anti-inference" muscle was specifically about *supplier metadata* (address/zip/area-code), which is sound and stays. What's different is *application-context defaults* — when the document is silent, USD is the correct default for a US tool.

Final rule: `Default is "USD"`, override only on explicit ISO code, compound-symbol token (`C$`/`A$`/`HK$` etc.), or bare `€`/`£`/`¥` (which emit `null`). Anti-supplier-metadata language preserved — "A Toronto letterhead with no `$`, no compound-symbol token, and no `CAD` mention → `USD` per the application default. If the supplier meant CAD, they would say so."

The principle change worth recording: **extraction defaults are application-context, not source inference.** This is the same kind of decision a system makes when it picks a default timezone or locale. Inferring from supplier metadata is still forbidden — that's the actual landmine. Everything in `data/synthetic_quotes/` got walked fixture-by-fixture; goldens now reflect the new rule.

**(2) Flag-layer gate on `currency_mismatch`.**

`graph.py:flag_node` now requires *both* `line.currency` and `product.last_paid_currency` to be non-null before firing `CURRENCY_MISMATCH`. Before this, `None vs USD` (catalog gap or extraction silence) fired bogus flags identical to real CAD/USD divergence. The gate makes the flag signal-only.

The **separation of concerns** this earned is what's worth recording for the README design-decisions section: extraction stays principled (null = source genuinely silent — happens only on bare `€`/`£`/`¥` now); flag layer stays signal-only (no flag when either side is unknown — there's nothing to compare). Ambiguity is encoded in the field value, not as a divergence flag.

Symmetric handling of the four cases:
- `quote=USD, last_paid=USD` → no flag (clean match)
- `quote=CAD, last_paid=USD` → flag (real divergence)
- `quote=null, last_paid=USD` → no flag (gated; source ambiguous)
- `quote=USD, last_paid=null` → no flag (gated; catalog gap)

Two new tests in `test_graph.py` cover the asymmetric null cases.

**(3) Prompt caching on the system prompt.**

Wrapped `SYSTEM` in `[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]` in both `agent.py` and `graph.py:extract_node`. Verified working: `cache_read_input_tokens: 4507` on consecutive calls, `input_tokens: 325` (just the user message + tools structure billed at full rate). Effective cut: ~85% on system-prompt input cost per call. Across a 14-fixture eval run, this is the single biggest cost lever short of swapping models.

**Locked baseline diff vs. the prior eval baseline:**
- Field-match: 98.0% → **97.7%** (within Sonnet stochasticity band; per-field breakdown shows `line_items.*.currency` gone entirely from failures, replaced by the usual description/notes/raw_notes flux).
- `currency_mismatch` flags: 52 → **5** (47 noise eliminated; remaining 5 are the legit pacific_amendments CAD lines + 1 nutrigrow USD-vs-catalog-CAD).
- `description_fuzzy` cascade hits: 3 (all wrong) → **0** (all 3 now correctly UNMATCHED).
- `unmatched` cascade hits: 7 → 10 (the 3 wrong fuzzy matches moved here).
- Match-tier distribution: 54 supplier_sku_exact, 1 requested_sku_exact, 10 unmatched — no regression on SKU matching.

**Next:** Haiku 4.5 swap as a single-variable change. Today's artifact (`20260505T193415Z.json`) is the Sonnet baseline to diff against. If field-match holds within ~1% on Haiku, commit; otherwise revert. The HITL endpoint then starts on the cheaper extraction path.

## 2026-05-05 — Haiku 4.5 swap + customer_ref tightening (locked)

One-line change in `agent.py:29` (`MODEL = "claude-sonnet-4-6"` → `"claude-haiku-4-5"`). `MODEL` is the single source — `graph.py:extract_node` imports it. Eval ran clean, no extraction failures.

**Sonnet → Haiku diff (artifact `20260505T194307Z.json` vs Sonnet baseline `20260505T193415Z.json`):**
- Field-match: 766/784 (97.7%) → 757/784 (96.6%), -1.1pt.
- Match-tier counts and line P/R **bit-identical** — routing layer unaffected. All drift is in extraction.
- Regressions cluster on prose-verbatim fields (`raw_notes`, `description`, `payment_terms`) and two strict-null violations: `customer_ref="2Fresh Ingredients"` on rootwise (golden=None — Haiku put the customer **name** in an ID field), and `pack_size="1 gallon"` on meridian's "Multi-purpose lubricant, 1 gallon" line.
- Flags: pack_size_drift -2, uom_mismatch +2, others unchanged.

**Customer_ref tightening (the win that stuck).** Added a "**Names are not IDs**" clause to the customer_ref field-spec at `prompts.py:64`: "when the source shows only the buyer's company name (e.g., 'Bill To: <Buyer Name Inc.>') with no alphanumeric account code alongside, emit `null` — customer names are not captured anywhere in this schema." Targeted at the rootwise failure; landed exactly as expected (rootwise 18/19 → 19/19). The semantic is load-bearing for the round-trip: a name in `customer_ref` would silently break downstream PO generation that expects the supplier's stable account ID.

**Pack_size iterations that didn't pan out (worth recording to avoid retrying).** Two attempts on the meridian "1 gallon" / terragreen "1 cy" failures, both regressed:
1. **Structural inversion** — moved the null fallback to lead with "Default null; lift only when..." and reframed the three rules as exceptions. Haiku read "Lift when packaging noun..." as a stronger trigger and started over-lifting: 12_revised IBC sizes (golden=None) got pulled in, 08 lifted as `"drum (55 gal)"` instead of `"55 gal drum"`, terragreen started lifting `"1 cy"`. Net 754/784 (-3 vs Haiku baseline). Pack_size mis went 5 → 10.
2. **Surgical reinforcements** — kept original ordering, added IBCs to the saleable-unit counter-rule and a second `"Hydraulic fluid, 1 gallon"` example to the null fallback. Worse: 749/784 (-8 vs baseline). Pack_size mis went to 11; 12_revised cratered to 31/39. Adding rules made Haiku less coherent, not more.

**Lesson.** The original pack_size structure was already tight. Haiku interprets additional inline rules more liberally than Sonnet — adding examples or restructuring the priority order both pulled it toward over-lifting. The meridian/terragreen failures may not be reachable through prompt-tuning alone; they likely need a different angle (a few-shot demo case showing this exact pattern, or accepted as Haiku's noise floor on pack_size).

**Caught one corpus-contamination slip.** First reinforcement pass had `"275-gal IBC"` and `"330-gal IBC"` as counter-rule examples — both verbatim from `quote_12_revised`. Post-edit grep flagged both. Reworded to generic category language before reverting the whole iteration. Reinforces the discipline: run the contamination check **after every edit**, not just once at the end.

**Final state — locked baseline:**
- Artifact: `evals/runs/20260505T201012Z.json`.
- Field-match: **760/784 (96.9%)** — beats pre-tightening Haiku baseline by +3, closes Sonnet gap from -9 to -6.
- Pack_size mis back to 5 (matching pre-tightening Haiku); customer_ref miss eliminated.
- Match-tier distribution: 54 supplier_sku_exact, 1 requested_sku_exact, 10 unmatched. Routing layer untouched throughout.

**Decision: stick with Haiku.** -0.8pt accuracy vs Sonnet is acceptable for the cost/latency profile of an extraction call. The CLAUDE.md split (Sonnet planner, Haiku extraction) holds.

**Next:** FastAPI HITL approval endpoint, on the locked Haiku extraction path.

## 2026-05-05 — PostgresSaver + HITL schema + approval_node + FastAPI

Eval baseline locked, pivoted to the HITL stack. Four chunks landed.

**(1) PostgresSaver swap.** Retired `MemorySaver`; `build_graph(checkpointer)` now requires the checkpointer explicitly — caller picks. Module-level `graph = build_graph()` removed (couldn't survive without a connection in scope), so eval/test callers build their own with `MemorySaver` and prod callers (CLI, FastAPI) pass `PostgresSaver`. New `scripts/setup_checkpointer.py` runs `PostgresSaver.setup()` idempotently.

**Schema-split footgun worth recording.** First setup attempt put checkpoint tables in `procure_agent` (manual `SET search_path` before `setup()`). Broke at first invoke: `PostgresSaver.from_conn_string` opens connections with default search_path, `get_tuple` queried `public.checkpoints` → `UndefinedTable`. Resolution: keep checkpoint tables in `public`, domain tables in `procure_agent`. They're conceptually different (LangGraph internals vs. our domain model) and trying to consolidate them breaks at runtime. Don't re-litigate.

**(2) HITL data shapes.** `LineAction` enum (approve/reject/override), `LineDecision` (with pydantic validator: `override_sku` required iff `action==OVERRIDE`), `HumanDecision` (reviewer + decided_at + line_decisions + overall_notes). `MatchResult` gained `human_action: LineAction | None`; `MatchMethod` gained `HUMAN_OVERRIDE` as a real cascade tier. Per-line for v1, not per-flag — per-flag is closer to real procurement HITL but adds UX complexity beyond v1 scope; deferred to the supplier-onboarding workflow.

**(3) approval_node body.** Three-way dispatch:
- APPROVE — sets `human_action`; original cascade match + flags untouched.
- REJECT — sets `human_action`; preserves the original match + flags as audit trail of *what was rejected* (distinct from "no match found"). Line excluded from PO downstream — `human_action == REJECT` is the marker.
- OVERRIDE — swap `matched_sku`, change method to `HUMAN_OVERRIDE`, confidence=1.0, drop the prior (wrong) flags, re-run `_flag_one` against the override product.

The `_flag_one` extraction is the refactor that earned the override path. `flag_node` is now a four-line wrapper iterating the same helper. No behavior change for the initial pass; the override re-flagging is a new use case.

**Re-running flags after override is the safety lever.** Smoke test: overriding aloe-vera (`kg`) line to `STRAP-PP-58` (`each`) fired a fresh `uom_mismatch` flag the original cascade didn't have. Operator sees divergence against the override SKU before the line goes downstream — this is what stops a typo override from silently becoming a bad PO line.

**(4) FastAPI HITL endpoint** at `src/procure_agent/api.py`. Endpoints:
- `GET /fixtures` — Streamlit dropdown source.
- `POST /runs` — invoke graph until interrupt; returns thread_id + matches + flags.
- `GET /runs/{thread_id}` — current snapshot (status: pending_approval / completed / in_progress).
- `POST /runs/{thread_id}/resume` — inject HumanDecision, run to END.

Connection strategy: per-request `PostgresSaver.from_conn_string` context manager. Traffic at v1 is single-digit-concurrent; pool optimization deferred. (Documented in api.py docstring so it doesn't get "optimized" without context.)

**Validation lives at the boundary** by design. Three layers:
1. Pydantic on `LineDecision` — override_sku presence, mutually exclusive with non-override actions.
2. `_validate_decisions` — one-decision-per-match cardinality + index-set alignment.
3. `_validate_override_skus` — every override resolves in catalog (cheap `WHERE sku = ANY(%s)`).

Domain code (approval_node) trusts these and doesn't double-check. Operator typos surface as 422 with the missing SKU listed before the graph resumes.

**Held drift / not done this session.**
- LangGraph deserialization warnings on `Quote` / `MatchResult` / Anthropic `TextBlock` / `ToolUseBlock` (`allowed_msgpack_modules`). Currently advisory; will block in a future LangGraph version. Tidy after deploy.
- `agent_runs` table still unused. Wire when the traced-sample-runs README section needs it.
- UI and Railway deploy outstanding.

**Where this leaves the HITL stack.** Hard architecture decisions (data shapes, validation strategy, connection lifecycle, override semantics) are settled. What's left is UI scaffolding + deploy.

## 2026-05-05 — UI: Next.js + FastAPI as a two-service product foundation

**The shape of the deploy changed.** The earliest plan called for Streamlit as the simplest single-screen wrapper. Pivoted to Next.js frontend + FastAPI as a separate Railway service so the API is the integration boundary, not a script behind a UI. The agent core is the artifact; everything around it is a real product foundation rather than a single-screen wrapper.

**FastAPI promoted from local-dev contract to product surface.** Up to this point the API was the "local API consumers / integration" layer — nice to have, but not the deployed thing. With a separate web service consuming it over HTTP, the API is now the actual integration boundary. Future consumers (ERP webhook, Slack bot, MCP server, third-party FE) plug into the same surface; the Next.js app is just the first client. The FastAPI work that landed earlier today is suddenly load-bearing rather than incidental — same code, more weight.

**Stack.** Next.js 16.2 (App Router, server components by default), TypeScript strict, Tailwind v4, shadcn/ui (now base-ui-backed, not Radix), Zod 4 as the FE single source of truth, Biome for lint/format. `pnpm`, single repo, two services.

**Two-service Railway, single public URL.** Service `api` (root `/`, Dockerfile, uvicorn) and service `web` (root `/web`, multi-stage Dockerfile, Next.js standalone). Web proxies `/api/*` to api via `API_INTERNAL_URL` (Railway internal DNS in prod, `localhost:8000` in dev). One public URL; CORS is moot in prod (same-origin); dev still uses a CORS allowlist for direct browser pokes against the API.

**FastAPI prep.** Two additions to `src/procure_agent/api.py`: `CORSMiddleware` reading a comma-separated `CORS_ORIGINS` env var, and a cheap `GET /health` (no DB) wired as the Railway healthcheck.

**Type discipline at the boundary.** Per the global TS rule (Zod as the FE single source of truth): `web/src/lib/schemas.ts` mirrors the Pydantic models by hand. Every API response is runtime-parsed in `lib/api.ts` so any future Pydantic ↔ Zod drift surfaces as a parse error at the boundary instead of a silent UI bug. Decimals/dates arrive as strings (FastAPI JSON-mode serialization); the Zod schemas reflect that exactly rather than coercing eagerly.

**Server actions, not browser fetch.** All FE → API traffic goes through Next.js server actions or server components. The browser never speaks directly to FastAPI. Three reasons: keeps the API origin off the wire, lets `revalidatePath` invalidate cached snapshots after a resume, and keeps the Zod-parsing fetch wrappers behind `import "server-only"` so client bundles stay lean.

**Boundary translation pattern, applied.** `resumeRunAction` catches `ApiError` and returns a typed `{ ok: false, error }` for the form to render inline; everything else re-throws to Next.js's error boundary. Same pattern as the FastAPI 422/409 boundary on the Python side — domain code throws, the seam translates.

**shadcn quirk worth recording.** Latest shadcn defaults to `@base-ui/react` instead of Radix. The new `Button` does not expose `asChild`. To wrap a `Link` with button styles, use `buttonVariants()` to get the className string and apply it to the `Link` directly. Caught by `tsc --noEmit`; lint alone wouldn't have caught it.

**Smoke test passed end-to-end.** Postgres up, uvicorn on 8000, Next.js dev on 3000:
- `GET /api/fixtures` populates the dropdown via server-side fetch through the rewrite proxy.
- `POST /runs` (server action) → graph runs to `interrupt_before=["approval"]` → redirect to `/runs/{thread_id}`.
- The pending-approval page renders header + line cards + decision form (verified `Approve & resume` in SSR output).
- The completed page renders the PO preview, including divergence flags retained on approved lines (verified against an end-to-end curl-driven approve flow that produced `price_variance` + `pack_size_drift` flags on AL101).
- `next build` succeeds with `output: "standalone"` (Docker runtime stage is a thin node copy of `.next/standalone`).
- `pnpm typecheck` clean, `pnpm lint` clean, FastAPI `ruff check` clean.

**Cleanup.** Dropped `streamlit>=1.39.0` from `pyproject.toml` after the repositioning — `uv lock && uv sync` removed 100+ transitive deps including `watchdog`, `toml`, `six`, `smmap`. Trimmed image surface area for the api service.

**What ships next.**
1. `railway login` + create two services pointing at this repo (one with root = `/`, one with root = `/web`).
2. Attach a Postgres plugin to the api service (Railway auto-injects `DATABASE_URL`).
3. Set the env vars from `.env.example` per service via the dashboard.
4. After the first api deploy: run `uv run python scripts/bootstrap_prod_db.py` once via Railway's run console (applies migrations + creates LangGraph checkpoint tables in `public`).
5. Wire `API_INTERNAL_URL` on the web service to `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` (Railway template-string syntax for cross-service references).
6. Public URL = the web service's `*.up.railway.app`.

**Backlog updates** (in the planning doc): the random fresh-quote generator and the file-upload entries now reference Next.js. Newly captured items the new architecture absorbs without rework: NextAuth, multi-tenant scoping, real-time SSE progress while extraction runs, MCP server wrap of the same FastAPI surface.

**Where this leaves the HITL stack.** Frontend and API both shipped to a smoke-tested local state. Next: the Railway deploy + a README rewrite that frames the API surface as the product, not the script behind a UI.

## 2026-05-06 — Railway deploy

Stack live end-to-end on Railway: Postgres + api + web in one project. Path from green-build to live URL surfaced five Railway-specific landmines, each one a single-line config change.

**Config landmines, in order hit.**
1. `uv.lock` was in `.gitignore` (Python-template default). Railway clones from GitHub, so the Dockerfile's `COPY pyproject.toml uv.lock ./` failed at the build step. Removed the line, committed the lockfile.
2. `startCommand` runs without a shell, so `--port $PORT` was passed literally. Wrapped in `sh -c '...'` so `$PORT` expands.
3. `DATABASE_URL` reference variable resolved to a literal string until set via Railway's "Add Reference" UI rather than typed by hand. Typed references look identical in the value cell but don't always bind.
4. `${{api.PORT}}` doesn't auto-resolve across services — Railway only injects `PORT` into the runtime env of the service that owns it. Set `PORT=8000` explicitly on the api service so the cross-service reference (and the in-container `$PORT`) both resolve.
5. Railway's private network is IPv6-only. `--host 0.0.0.0` makes web→api fail with `ECONNREFUSED`. Switched to `--host ::`. Railway's healthcheck probe then started failing — the `::` socket in the container did not accept the IPv4 probe. Dropped `healthcheckPath` from `railway.toml`; private-network traffic is what matters, the probe was gravy.

**Final `railway.toml` shape (api).**
- `preDeployCommand = "uv run python scripts/bootstrap_prod_db.py"` runs migrations + LangGraph checkpoint setup before every uvicorn start. Idempotent, so leaving it in permanently means new migrations auto-apply on push.
- `startCommand = "sh -c 'uv run --no-dev uvicorn procure_agent.api:app --host :: --port $PORT'"` — IPv6 binding, shell-expanded port.
- No healthcheck.

**Web service config.**
- `API_INTERNAL_URL = http://api.railway.internal:8000` — Railway's private DNS resolves the api service's IPv6 address; port hardcoded to match the explicit `PORT=8000` on api.
- `node server.js` start command unchanged; Next.js standalone reads `PORT` from env directly.

**Smoke test.** Public web URL renders the fixture-picker home page. Server component fetches `/fixtures` from the api over the private network. No errors in either service's runtime logs.

## 2026-05-06 — fixture naming + landing-page source preview

**Fixture filenames now key on supplier quote ref.** Old corpus mixed three conventions: numbered prefixes (`01_aloe_corp_clean_tabular.txt`), descriptive labels (`quote_07_customer_and_rfq_refs.txt`), and supplier-plus-date (`quote_meridian_supply_2026-04-24.md`). Renamed the lot to `<supplier-slug>_<quote-ref-or-date>.<ext>` — keys on the supplier's own quote number when present (the field a procurement folder actually indexes by in practice), falls back to supplier-plus-date for the two informal fixtures with no ref in source (`aloe-corp_2026-04-21-followup`, `terragreen_2026-04-23`). Sorts grouped by supplier in the dropdown.

**Why the supplier-issued ref over a date.** Real procurement systems track quotes by the supplier's quote number — that's the artifact the supplier reissues against, the one the buyer cites in PO communications, the one revisions are anchored to (e.g. `RW-2026-0419` → `RW-2026-0419-R2`). Date-only filenames lose that anchor. Filename-as-quote-ref makes the fixture set legible at a glance to anyone who's worked procurement.

**Rename mechanics.** All 35 source/.expected.json/.notes.md files moved with `git mv` so blame/history follow. Updated `agent.py:DEFAULT_FIXTURE`, the tool docstring example, and `test_graph.py` references. Sidecar `.notes.md` headers updated to match new stems. Historical `evals/runs/*.json` left untouched — those are frozen artifacts of past runs, rewriting their `fixture_filename` fields would falsify the record.

**Landing-page source preview.** Dropdown previously showed filenames only; user couldn't see the quote shape until after starting a run. Pulled the picker out into a `<FixturePicker>` client component that fetches the selected fixture's source through the Next rewrite proxy on selection change and renders it inline above the submit button. Server still SSRs the initial fixture's source so first paint isn't blank.

**Why the proxy fetch and not the server-only wrapper.** `lib/api.ts` is `import "server-only"`; the client component can't call `fetchFixtureSource` directly. Hitting `/api/fixtures/{filename}` from the client goes through the same Next rewrite that backs `lib/api.ts` server-side, so the API surface stays single-source. Trade-off: the browser sees the proxied URL shape, but that's already the case for any client-driven fetch in this app.

**Adjacent api.py improvement, not this session.** `GET /fixtures/{filename}` previously did `path.read_text(encoding="utf-8")` on every fixture — fine for `.txt`/`.csv`/`.md`/`.eml`, raises `UnicodeDecodeError` on the two `.docx` fixtures (zip files). Frontend silently caught and rendered "Source unavailable." The fix (delegate to `agent.read_file` so docx is rendered to plain text the same way the extraction pipeline reads it) is in the working tree from a parallel WIP thread; not bundled into this commit but worth flagging here as a paired improvement that lights up docx in the preview path.

## 2026-05-06 — review-page reconciliation surface

**Source viewer next to extraction.** `GET /fixtures/{filename}` returns the raw fixture text via `PlainTextResponse`. Run page restructured into a 2-column grid: source on the left, decision form / PO preview on the right. Closes the gap where reviewers saw extracted line items with nothing to compare them against. Path-traversal guard rejects names containing `/`, `\`, or leading `.`; suffix must be in `SOURCE_EXTS`.

**Docx in the source path.** Initial implementation called `path.read_text(encoding="utf-8")` directly — `.docx` fixtures (zip-packaged XML) raised `UnicodeDecodeError`, caught silently in the FE and rendered "Source unavailable." Fixed by delegating to `agent.read_file`, which already dispatches `.docx` to the python-docx renderer the extraction pipeline uses. One reader, two consumers — no parallel docx logic to maintain.

**Inline matched-master detail.** `RunSnapshot` extended with `matched_products: dict[str, Product]` keyed by SKU. The API handler bulk-fetches every SKU referenced by `matches` and bundles the catalog rows into the snapshot. One DB hit per snapshot vs. an N-per-line fan-out from the FE. New `MatchedProduct` card renders description, pack_size, uom, on_hand, last-paid price/date, and preferred supplier directly under each line's metadata grid — reviewer sees quote-side and master-side fields side by side without leaving the card.

**Searchable override picker.** Override flow previously required the reviewer to type a SKU from memory — workable for a demo, broken in practice. Added `GET /products/search?q=&limit=` (ILIKE on SKU and description, SKU hits ranked first via a `CASE WHEN` ordering column). Free-text override input replaced with a `ProductCombobox` client component: debounced 180ms, fetches `/api/products/search` through the Next rewrite proxy, click-outside to close. Server-side `_validate_override_skus` still rejects unknown SKUs at resume — defensive against stale picker state.

**Card overflow landmine.** First combobox draft used `absolute z-10` positioning under a `relative` wrapper — got clipped on every line card because shadcn's `Card` carries `overflow-hidden` for rounded-corner clipping. Switched to inline-flow (dropdown pushes the radios down while open). No `createPortal` + position-tracking machinery to maintain; trade-off is the card grows briefly during search, which is acceptable when the override flow is the user's only intent at that moment.

**Decimal serialization between Pydantic v2 and Zod.** `Product.last_paid_unit_price` is `Decimal`. FastAPI/Pydantic v2's JSON serialization isn't perfectly stable across configs — it can land as a JSON string or a JSON number depending on the model_dump path. A strict `z.string()` on the FE would parse-fail silently and leave the matched-master card blank. Defended by accepting `z.union([z.string(), z.number()]).transform(String)` and normalizing to string for display. Same pattern applies anywhere Decimal crosses the wire.

**Combobox failure mode now visible.** Original error handling swallowed every fetch failure as "no matches." When the override search misbehaved in production, there was no way to tell whether the API was unreachable, the DB had no products, or Zod was parse-failing on the response shape. Added an explicit `error` state — fetch failures (excluding `AbortError` from debounce churn) render `Search failed: <message>` in the dropdown. Surfaces actual cause without dev tools.

**Backlog captured.** Two review-page UX gaps surfaced during the work, deferred post-ship: (a) create new product inline from the override flow — currently the override is gated on the SKU already existing in the catalog, so a missing-product case forces the reviewer to abort, (b) upload new quote — currently restricted to the seeded synthetic-fixtures dropdown, which limits demo to known-good shapes. Both are workflow-completeness items a real procurement reviewer would hit immediately; both are scope creep on the 7-day build.
