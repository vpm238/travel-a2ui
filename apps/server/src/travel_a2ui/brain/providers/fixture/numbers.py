"""The arithmetic, which has to match JavaScript's rather than Python's.

Determinism is the point of the whole provider: the same query returns the same
flights on every run, so a screenshot stays true and a test can assert on a
price. That makes this the fussiest file in the project, because the numbers
have to come out identical to the TypeScript's, down to the last dollar.

**Three pieces of JavaScript arithmetic are emulated rather than translated.**
Each is commented where it lives:

  * bitwise operators coerce to 32 bits, so the seeded RNG needs masking that
    Python's arbitrary-precision integers do not do on their own;
  * `Math.imul` multiplies as 32-bit, keeping the low half;
  * `toFixed` rounds halves away from zero where Python's formatting rounds
    them to even, which is a tenth of a star on a hotel rating.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Sequence

from .tables import _CURRENCY_SYMBOL, _DESTINATIONS

def code_for_seed(query: str) -> str:
    """A destination as the airport code the seed is built from.

    Seeding an estimate on the *text* rather than the resolved code means
    "Madrid", "madrid" and "MAD" each produce a different set of prices for the
    same trip — plausible numbers every time, so nothing looks wrong, and the
    figure moves when a traveller happens to type the code instead of the name.

    Falls back to the trimmed text, so somewhere the provider has never heard
    of still seeds deterministically rather than raising.
    """
    trimmed = (query or "").strip()
    upper, lowered = trimmed.upper(), trimmed.lower()
    for entry in _DESTINATIONS:
        if entry["airport"] == upper:
            return entry["airport"]
        if lowered in entry["aliases"]:
            return entry["airport"]
    return trimmed


_MASK = 0xFFFFFFFF


def _seed(text: str) -> int:
    """FNV-1a, as 32-bit arithmetic.

    `Math.imul(hash, 0x01000193)` is a 32-bit multiply keeping the low half;
    Python's integers are unbounded, so the mask is what makes the two agree.
    """
    h = 0x811C9DC5
    for char in text:
        h ^= ord(char)
        h = (h * 0x01000193) & _MASK
    return h & _MASK


def _rng(state: int) -> Callable[[], float]:
    """xorshift32, the same sequence the TypeScript produces.

    JavaScript's bitwise operators coerce their operands to 32 bits and the
    shifts wrap; Python's do neither, so every step is masked. Getting this
    wrong does not throw — it produces a different, perfectly plausible set of
    flights, which is why the golden compares prices rather than shapes.
    """
    value = state or 1

    def nxt() -> float:
        nonlocal value
        value ^= (value << 13) & _MASK
        value &= _MASK
        value ^= value >> 17
        value ^= (value << 5) & _MASK
        value &= _MASK
        return value / 0xFFFFFFFF

    return nxt


def _pick(items: Sequence[Any], random: Callable[[], float]) -> Any:

    return items[math.floor(random() * len(items)) % len(items)]


def _js_round(value: float) -> int:
    """`Math.round`: halves toward positive infinity, unlike Python's `round`."""

    return math.floor(value + 0.5)


def _to_fixed(value: float, digits: int) -> str:
    """`toFixed`: halves away from zero, where Python's format rounds to even.

    A tenth of a star on a hotel rating, and enough to fail the golden.
    """
    from decimal import ROUND_HALF_UP, Decimal

    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _money(amount: float, currency: str) -> str:
    symbol = _CURRENCY_SYMBOL.get(currency, f"{currency} ")
    return f"{symbol}{_js_round(amount):,}"


def _clock(minutes: int) -> str:
    wrapped = ((minutes % 1440) + 1440) % 1440
    next_day = " +1" if minutes >= 1440 else ""
    return f"{wrapped // 60:02d}:{wrapped % 60:02d}{next_day}"


def _duration_minutes(duration: str) -> int:
    match = re.search(r"(\d+)h\s*(\d+)?", duration)
    if not match:
        return 0
    return int(match.group(1)) * 60 + int(match.group(2) or 0)
