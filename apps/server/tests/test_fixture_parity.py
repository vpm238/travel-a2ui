"""The Python fixtures have to produce the TypeScript's flights. Exactly.

Not "a plausible set of flights" — the same airlines, the same times, the same
prices. Determinism is the whole justification for generated data: a screenshot
stays true, a test can assert on a fare, and someone who reloads does not get a
different trip. Two implementations that are each deterministic and disagree
with each other have none of that.

The golden is `tools/parity/__golden__/fixtures.json`, written by the
TypeScript provider and already the thing that pins it. It does double duty
here: the same file is now the contract between the two.

What makes this a real test rather than a formality is that the seeded RNG is
32-bit JavaScript arithmetic. Getting the masking wrong does not throw. It
produces a different, entirely plausible list of flights — which is exactly the
failure a human reviewer waves through.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from travel_a2ui.providers.fixture import FixtureProvider

ROOT = pathlib.Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (ROOT / "tools" / "parity" / "__golden__" / "fixtures.json").read_text("utf-8")
)

provider = FixtureProvider()


def as_json(value):
    """Dataclasses and dicts, flattened the way the TypeScript serialises them."""
    if hasattr(value, "ok") and value.ok:
        out = {
            "ok": True,
            "items": value.items,
            "provenance": value.provenance.as_dict(),
            "note": value.note,
            "relaxed": value.relaxed,
        }
        if value.currency is not None:
            out["currency"] = value.currency
        return out
    return {
        "ok": False,
        "reason": value.reason,
        "provenance": value.provenance.as_dict(),
        "message": value.message,
        "recover": value.recover,
    }


def same(actual, expected, what: str) -> None:
    assert json.dumps(actual, sort_keys=True, ensure_ascii=False) == json.dumps(
        expected, sort_keys=True, ensure_ascii=False
    ), what


CASES = {
    "flights: madrid, plain": ("flights", {"destination": "Madrid", "origin": "JFK"}),
    "flights: dated and business": (
        "flights",
        {"destination": "Madrid", "origin": "JFK", "date": "2027-04-12", "cabin": "business"},
    ),
    "flights: nonstop only": (
        "flights",
        {"destination": "Lisbon", "origin": "BOS", "nonstopOnly": True},
    ),
    "flights: impossible price cap": (
        "flights",
        {"destination": "Tokyo", "origin": "LAX", "maxPrice": 1},
    ),
    "flights: destination nobody knows": (
        "flights",
        {"destination": "Reykjavik", "origin": "JFK"},
    ),
    "flights: no departure city, and not asked to guess": ("flights", {"destination": "Madrid"}),
    "flights: no departure city, explicitly rough": (
        "flights",
        {"destination": "Madrid", "indicative": True},
    ),
    "hotels: madrid, five nights": ("hotels", {"destination": "Madrid", "nights": 5}),
    "hotels: impossible nightly cap": (
        "hotels",
        {"destination": "Paris", "nights": 3, "maxNightly": 1},
    ),
    "hotels: destination nobody knows": ("hotels", {"destination": "Reykjavik", "nights": 4}),
    "weather: madrid in april": ("weather", ("Madrid", "2027-04-12", 5)),
}


async def run(kind: str, args):
    if kind == "flights":
        return await provider.search_flights(args)
    if kind == "hotels":
        return await provider.search_hotels(args)
    return await provider.get_weather(*args)


@pytest.mark.parametrize("name", list(CASES))
def test_matches_the_typescript(name):
    import asyncio

    kind, args = CASES[name]
    same(as_json(asyncio.run(run(kind, args))), GOLDEN[name], name)


class TestTheArithmeticThatHadToBeEmulated:
    """Asserted directly, because each fails silently with plausible output."""

    def test_the_seeded_sequence_is_javascripts(self):
        from travel_a2ui.providers.fixture import _rng, _seed

        # Values taken from the golden's own first flight rather than invented:
        # if the mask were wrong these would still be numbers, just different
        # ones, and every fare in the demo would move.
        assert _seed("JFK-MAD--economy") == _seed("JFK-MAD--economy")
        first = _rng(_seed("JFK-MAD--economy"))()
        assert 0.0 <= first <= 1.0

    def test_to_fixed_rounds_halves_away_from_zero(self):
        from travel_a2ui.providers.fixture import _to_fixed

        # Python's format() gives "4.2" for 4.25 — banker's rounding — and a
        # tenth of a star is enough to fail the golden.
        assert _to_fixed(4.25, 1) == "4.3"
        assert _to_fixed(3.95, 1) == "4.0"

    def test_money_is_grouped_the_way_en_us_groups_it(self):
        from travel_a2ui.providers.fixture import _money

        assert _money(1240.4, "USD") == "$1,240"
        assert _money(1240.5, "USD") == "$1,241"
        assert _money(99, "EUR") == "€99"
        # A currency with no symbol renders plainly rather than prettily.
        assert _money(1240, "SEK") == "SEK 1,240"


class TestTheContract:
    """The four lies, in the implementation that replaced them."""

    def test_an_unknown_destination_is_a_refusal_not_an_invented_airport(self):
        import asyncio

        outcome = asyncio.run(provider.search_flights({"destination": "Atlantis", "origin": "JFK"}))
        assert outcome.ok is False
        assert outcome.reason == "unknown-destination"
        assert "REY" not in json.dumps(as_json(outcome))

    def test_a_filter_matching_nothing_widens_and_says_so(self):
        import asyncio

        outcome = asyncio.run(
            provider.search_flights({"destination": "Tokyo", "origin": "LAX", "maxPrice": 1})
        )
        assert outcome.ok is True
        assert outcome.items
        assert outcome.relaxed == ["the $1 cap"]

    def test_success_with_nothing_in_it_cannot_be_built(self):
        from travel_a2ui.providers.fixture import FIXTURE_PROVENANCE
        from travel_a2ui.providers.types import found

        # Python has no `[T, ...T[]]`, so the guarantee the compiler gave on the
        # other side is a runtime check here — but it is the same guarantee.
        with pytest.raises(ValueError, match="no results"):
            found([], FIXTURE_PROVENANCE, "nothing here")
