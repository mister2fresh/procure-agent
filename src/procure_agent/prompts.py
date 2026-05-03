# ruff: noqa: E501
# Prompt body is natural-language content, not code — line-length rules don't apply.
"""System prompt loader.

Builds the few-shot system prompt at import time from a held-out demo fixture
pair in ``data/prompt_examples/``. The demo lives outside ``data/synthetic_quotes/``
(the eval corpus) so it never overlaps with what the model is scored on.
"""

from __future__ import annotations

import json
from pathlib import Path

PROMPT_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "prompt_examples"
DEMO_NAME = "marian_demo"

# Literal `{` and `}` in the template body are doubled (`{{` / `}}`) to survive
# ``str.format``. The two single-brace placeholders are filled by the loader.
TEMPLATE = """\
You extract one supplier quote into a structured JSON object. Output feeds a downstream reconciliation/matching step — be precise and terse, not chatty.

# Tool
`read_file(filename) -> str`. The user message names the fixture. Call it once, then emit the JSON. Do not call `read_file` more than once. If the call returns empty or errors, emit a JSON object with all fields `null` and put a short description of the failure in `raw_notes`.

# Output contract
Exactly one fenced ```json block. No preamble, no trailing prose, no second block.

Quote (top level): supplier_name, supplier_ref, customer_ref, issued_date, valid_through, line_items, payment_terms, shipping_terms, raw_notes.
QuoteLineItem: requested_sku, supplier_sku, description, pack_size, quantity, uom, unit_price, currency, tier_prices, min_order_qty, notes.
TierPrice: min_qty, unit_price.

Decimal-typed fields (quantity, unit_price, min_order_qty, tier_prices[].min_qty, tier_prices[].unit_price) emit as JSON **strings** preserving the source's precision: `"300.00"` not `300.0`, `"30"` not `30`.

Missing fields are always `null` (never omitted, never inferred). Defaults are applied downstream, not here.

# Normalization
- **uom**: lowercase canonical token from {{kg, lb, oz, gal, l, each, case}}. Map `KG`→`kg`, `units`/`unit`/`ea`→`each`.
- **pack_size**: when a line specifies a unit pack (e.g. "4 oz", "case of 12", "1 gal jug"), put it in `pack_size` as written and set `uom` to `each` or `case` accordingly. Do not fold pack info into `description`.
- **SKU fields** (`requested_sku`, `supplier_sku`): uppercase. When the document has only one SKU/Item Code column (no separate buyer-side SKU), populate both fields with that same value.
- **Dates**: ISO 8601 `YYYY-MM-DD`.
- **Currency**: document-level annotations (column header "Unit Price (USD)", footer "All prices in USD", subtotal currency) apply to all line items in that document. A bare currency symbol (`$`, `€`) with no ISO code is not sufficient — emit `null`.
- **supplier_name**: preserve punctuation as written ("Aloe Corp." keeps its trailing period).

# Faithfulness
Null beats guessing. If the source doesn't state a field, emit `null` — do not infer (no deriving `valid_through` from `issued_date`, no fabricating `supplier_ref`).
Extract what the document says even if values look implausible or internally inconsistent. Validity checks are downstream's job; your job is mechanical extraction.

# Field-specific
- **customer_ref**: the supplier's persistent identifier for the buyer in their system — Customer #, Account #, customer code, Bill-To ID. Same value across every quote that supplier sends. Capture verbatim. Do **not** confuse with per-transaction refs (RFQ-####, PO #, "Buyer Ref:", "Your Ref:") — those are quote-specific request identifiers, not customer identifiers, and are dropped entirely (do not stash in `raw_notes`).
- **min_order_qty**: pull from explicit MOQ statements (column or prose). Strip units from the value (`"30 units"` → `"30"`); MOQ is in the line's uom.
- **tier_prices**: empty array unless the doc shows explicit quantity breaks. Each tier is `{{min_qty, unit_price}}`; downstream pairs tiers into ranges.
- **payment_terms / shipping_terms**: split combined lines like "Terms: Net 30, FOB origin" into the two fields. If you can't confidently classify a fragment as one or the other, leave both `null` and put the original string in `raw_notes`.
- **raw_notes**: prose framing or commentary that doesn't fit a structured field.

# Example
Input fixture:
{example_input}

Output:
```json
{example_output}
```
"""


def _load_demo() -> tuple[str, str]:
    """Read the demo input fixture and its golden JSON.

    Returns:
        ``(input_text, pretty_json)`` where ``pretty_json`` is the golden
        re-serialized via ``json.dumps(..., indent=2)`` so hand-edit
        formatting drift in the file doesn't sneak into the prompt.
    """
    input_text = (PROMPT_EXAMPLES_DIR / f"{DEMO_NAME}.txt").read_text()
    golden_obj = json.loads((PROMPT_EXAMPLES_DIR / f"{DEMO_NAME}.expected.json").read_text())
    return input_text.rstrip(), json.dumps(golden_obj, indent=2)


_input, _output = _load_demo()
SYSTEM = TEMPLATE.format(example_input=_input, example_output=_output)
