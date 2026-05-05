"""Tolerance comparators for catalog-vs-quote field equality checks.

The DB stores extracted ``QuoteLineItem.uom`` and ``pack_size`` as raw
supplier strings (per the migration's text-not-enum decision) so the eval
harness can see drift. The flag layer doesn't want to surface that drift as
UOM_MISMATCH or PACK_SIZE_DRIFT noise — `"Gal"` vs `"gal"` and `"5kg pail"`
vs `"5 kg pail"` are cosmetic, not divergence.

These helpers compare with tolerance: cosmetic drift collapses, substantive
drift survives. Used by ``flag_node``; kept pure so the HITL surface and
eval harness can reuse them later.
"""

from __future__ import annotations

import re

# Maps a free-form UoM token to canonical lowercase. The canonical set is
# closed (7 values from procure_agent.schemas.UoM), so a static alias map
# covers it. Identity entries omitted — the .get fallback handles them.
_UOM_ALIASES: dict[str, str] = {
    "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "lbs": "lb", "pound": "lb", "pounds": "lb",
    "ozs": "oz", "ounce": "oz", "ounces": "oz",
    "gals": "gal", "gallon": "gal", "gallons": "gal",
    "lt": "l", "ltr": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ea": "each", "unit": "each", "units": "each",
    "cases": "case", "cs": "case",
}


def _canon_uom(s: str) -> str:
    """Lowercase, strip whitespace + trailing dot, then map through aliases.

    Returns the cleaned token unchanged when it's not in the alias map. That
    lets off-canonical values (`"roll"`, `"box"`, `"set"`) flow through as
    legitimate divergence signals — UOM_MISMATCH should fire on those.
    """
    cleaned = s.strip().lower().rstrip(".")
    return _UOM_ALIASES.get(cleaned, cleaned)


def same_uom(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` denote the same canonical UoM.

    Args:
        a: One UoM string (typically ``QuoteLineItem.uom``).
        b: The other (typically ``Product.uom`` — a ``UoM`` StrEnum, which
            is also a ``str``).

    Returns:
        ``True`` iff both canonicalize to the same value.
    """
    return _canon_uom(a) == _canon_uom(b)


_DIGIT_LETTER = re.compile(r"(\d)([a-z])")
_LETTER_DIGIT = re.compile(r"([a-z])(\d)")
_WHITESPACE = re.compile(r"\s+")


def _canon_pack_size(s: str) -> str:
    """Cosmetic normalization for pack_size strings.

    Lowercases, splits glued digit/letter pairs (`"5kg"` → `"5 kg"`),
    collapses whitespace runs, strips trailing punctuation. Decimal points
    inside numbers (`"2.2 cu ft bale"`) are preserved — only digit-letter
    boundaries get a separator inserted.
    """
    s = s.strip().lower()
    s = _DIGIT_LETTER.sub(r"\1 \2", s)
    s = _LETTER_DIGIT.sub(r"\1 \2", s)
    s = _WHITESPACE.sub(" ", s)
    return s.rstrip(".,")


def same_pack_size(a: str | None, b: str | None) -> bool:
    """True when ``a`` and ``b`` describe the same pack size up to cosmetic drift.

    Both ``None`` is treated as same (neither side claimed a pack size).
    One ``None`` and one populated is a real divergence — the supplier
    asserted a pack the catalog doesn't, or vice versa.

    Args:
        a: Pack size as written on a ``QuoteLineItem`` (nullable).
        b: Pack size on the matched ``Product`` (nullable).

    Returns:
        ``True`` iff both sides agree after cosmetic normalization.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return _canon_pack_size(a) == _canon_pack_size(b)
