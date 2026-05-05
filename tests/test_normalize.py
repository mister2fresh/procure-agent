"""Tests for the tolerance comparators in procure_agent.normalize.

Table-driven: each case names the supplier-vs-catalog pair, the expected
equality verdict, and an inline note on which drift class it covers.
"""

from __future__ import annotations

import pytest

from procure_agent.normalize import same_pack_size, same_uom


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        # Identity — canonical-on-canonical is always equal.
        ("kg", "kg", True),
        ("each", "each", True),
        # Case drift — cosmetic.
        ("Gal", "gal", True),
        ("KG", "kg", True),
        # Trailing punctuation — cosmetic.
        ("gal.", "gal", True),
        ("ea.", "each", True),
        # Pluralization / spelled-out — alias-mapped.
        ("kgs", "kg", True),
        ("gallons", "gal", True),
        ("ounces", "oz", True),
        ("kilogram", "kg", True),
        ("liters", "l", True),
        ("cases", "case", True),
        ("ea", "each", True),
        # Real divergence — different canonical.
        ("kg", "lb", False),
        ("each", "case", False),
        ("gal", "l", False),
        # Off-canonical token — preserved as-is, fires divergence against
        # any catalog UoM. ROLL is what Pacific Amendments uses for
        # STRAP-PP-58 against a catalog row of `each`.
        ("ROLL", "each", False),
        ("box", "each", False),
    ],
)
def test_same_uom(a: str, b: str, expected: bool) -> None:
    assert same_uom(a, b) is expected
    # Symmetry is part of the contract.
    assert same_uom(b, a) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        # Both None — neither side claimed a pack size, no divergence.
        (None, None, True),
        # One None — substantive (one side asserted, the other didn't).
        ("5 kg pail", None, False),
        (None, "5 kg pail", False),
        # Identity.
        ("5 kg pail", "5 kg pail", True),
        # Case drift — cosmetic.
        ("5 KG Pail", "5 kg pail", True),
        # Whitespace runs collapsed.
        ("5  kg  pail", "5 kg pail", True),
        # Glued digit/letter — supplier writes "5kg", catalog has "5 kg".
        ("5kg pail", "5 kg pail", True),
        ("50lb bag", "50 lb bag", True),
        # Trailing punctuation.
        ("case of 12.", "case of 12", True),
        # Decimals preserved (no spurious split inside the number).
        ("2.2 cu ft bale", "2.2 cu ft bale", True),
        # Substantive — different number.
        ("5 kg pail", "10 kg pail", False),
        # Substantive — different unit token.
        ("5 kg pail", "5 lb pail", False),
        # Substantive — extra token.
        ("case of 12", "case of 12 ct", False),
        # Substantive — different container word.
        ("50 lb bag", "50 lb sack", False),
    ],
)
def test_same_pack_size(a: str | None, b: str | None, expected: bool) -> None:
    assert same_pack_size(a, b) is expected
    assert same_pack_size(b, a) is expected
