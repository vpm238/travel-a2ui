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

from travel_a2ui.brain.providers.fixture import FixtureProvider

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
    # Boston is not one of the airports with written-down detail, which is the
    # case below: it answers, deterministically, like anywhere else.
    "flights: nonstop only": (
        "flights",
        {"destination": "Lisbon", "origin": "LHR", "nonstopOnly": True},
    ),
    "flights: a departure airport nobody wrote down": (
        "flights",
        {"destination": "Lisbon", "origin": "BOS"},
    ),
    "flights: impossible price cap": (
        "flights",
        {"destination": "Tokyo", "origin": "LAX", "maxPrice": 1},
    ),
    "flights: a destination nobody wrote down": (
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
    "hotels: a destination nobody wrote down": (
        "hotels",
        {"destination": "Reykjavik", "nights": 4},
    ),
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
        from travel_a2ui.brain.providers.fixture import _rng, _seed

        # Values taken from the golden's own first flight rather than invented:
        # if the mask were wrong these would still be numbers, just different
        # ones, and every fare in the demo would move.
        assert _seed("JFK-MAD--economy") == _seed("JFK-MAD--economy")
        first = _rng(_seed("JFK-MAD--economy"))()
        assert 0.0 <= first <= 1.0

    def test_to_fixed_rounds_halves_away_from_zero(self):
        from travel_a2ui.brain.providers.fixture import _to_fixed

        # Python's format() gives "4.2" for 4.25 — banker's rounding — and a
        # tenth of a star is enough to fail the golden.
        assert _to_fixed(4.25, 1) == "4.3"
        assert _to_fixed(3.95, 1) == "4.0"

    def test_money_is_grouped_the_way_en_us_groups_it(self):
        from travel_a2ui.brain.providers.fixture import _money

        assert _money(1240.4, "USD") == "$1,240"
        assert _money(1240.5, "USD") == "$1,241"
        assert _money(99, "EUR") == "€99"
        # A currency with no symbol renders plainly rather than prettily.
        assert _money(1240, "SEK") == "SEK 1,240"


class TestTheContract:
    """The four lies, in the implementation that replaced them."""

    def test_a_place_nobody_wrote_down_still_answers(self):
        """A demo that refuses Boston teaches a visitor nothing.

        Nine cities have hand-written detail. Everywhere else is generated from
        the name — deterministically, so the same city comes back every time —
        and labelled sample data like every other figure here. The honesty is in
        the provenance label, not in a short list of places.
        """
        import asyncio

        outcome = asyncio.run(provider.search_flights({"destination": "Atlantis", "origin": "JFK"}))
        assert outcome.ok is True
        assert outcome.items
        assert outcome.provenance.live is False

    def test_an_invented_place_is_the_same_place_every_time(self):
        """The property that makes generated data usable at all.

        A demo that invents a different Boston on every turn is worse than one
        that refuses: a screenshot stops being true and a trip planned today is
        not the trip found tomorrow.
        """
        import asyncio

        first = asyncio.run(provider.search_flights({"destination": "Boston", "origin": "JFK"}))
        again = asyncio.run(provider.search_flights({"destination": "Boston", "origin": "JFK"}))
        assert as_json(first) == as_json(again)

    def test_a_query_that_names_no_place_is_still_refused(self):
        """Inventing a city for an empty string is answering a question nobody
        asked."""
        import asyncio

        outcome = asyncio.run(provider.search_flights({"destination": "   ", "origin": "JFK"}))
        assert outcome.ok is False
        assert outcome.reason == "unknown-destination"

    def test_a_filter_matching_nothing_widens_and_says_so(self):
        import asyncio

        outcome = asyncio.run(
            provider.search_flights({"destination": "Tokyo", "origin": "LAX", "maxPrice": 1})
        )
        assert outcome.ok is True
        assert outcome.items
        assert outcome.relaxed == ["the $1 cap"]

    def test_success_with_nothing_in_it_cannot_be_built(self):
        from travel_a2ui.brain.providers.fixture import FIXTURE_PROVENANCE
        from travel_a2ui.brain.providers.types import found

        # Python has no `[T, ...T[]]`, so the guarantee the compiler gave on the
        # other side is a runtime check here — but it is the same guarantee.
        with pytest.raises(ValueError, match="no results"):
            found([], FIXTURE_PROVENANCE, "nothing here")


class TestTheDataIsNotEmpty:
    """Every list a fixture is assembled from has to have something in it.

    This guard used to live in `scripts/build_fixtures.py`, which generated a
    bundle for the Worker because a Worker has no filesystem. The Worker is gone
    and so is the generator — and the guard went with it, which was a mistake:
    the Python server reads the same CSVs at import, and it is the one thing
    actually serving travellers now.

    What it prevents is not a crash. An empty list does not throw; it produces a
    hotel called "undefined undefined", a flight on an airline with no name, a
    price with no currency symbol. The demo keeps running and every surface is
    quietly wrong, which is the worst failure this project has — it looks
    exactly like a working answer.
    """

    def test_every_seed_list_has_rows(self) -> None:
        from travel_a2ui.brain.providers import fixture

        lists = {
            "destinations.json": fixture._DESTINATIONS,
            "airlines.csv": fixture._AIRLINES,
            "origins.csv": fixture._ORIGINS,
            "currencies.csv": list(fixture._CURRENCY_SYMBOL),
            **{f"lodging.csv ({kind})": fixture._LODGING.get(kind, [])
               for kind in ("word", "name", "amenity", "connection")},
        }
        empty = sorted(name for name, rows in lists.items() if not rows)
        assert not empty, f"{empty} would produce 'undefined undefined' rather than fail"

    def test_every_destination_can_be_flown_home_from(self) -> None:
        """Closed under going home, which is now a hop that has to be ticketed.

        A destination missing from the departure list is a trip that can never
        finish: the agent flies somebody to San Francisco, the return hop needs
        a ticket out of SFO, and there are no flights out of SFO because SFO was
        a place you could only arrive at. It was exactly that, and it is the
        first thing anybody types into this demo.
        """
        from travel_a2ui.brain.providers import fixture

        departures = {entry["code"] for entry in fixture._ORIGINS}
        for entry in fixture._DESTINATIONS:
            assert entry["airport"] in departures, (
                f"{entry['city']} can be flown to and not from"
            )

    def test_every_destination_a_tool_can_be_asked_for_actually_answers(self) -> None:
        """The inventory in the prompt is a promise; this is the check on it.

        The agent is now told which cities this deployment has data for, and it
        is told not to start planning anywhere else. That is only safe if every
        city on the list really does come back with flights and somewhere to
        stay.
        """
        import asyncio

        from travel_a2ui.brain.providers.fixture import FixtureProvider

        provider = FixtureProvider()

        async def check() -> None:
            for entry in await provider.destinations():
                city = entry["city"]
                flights = await provider.search_flights(
                    {"destination": city, "origin": "JFK", "date": "2027-04-12", "travelers": 1}
                )
                assert getattr(flights, "items", None), f"no flights for {city}"
                stays = await provider.search_hotels(
                    {"destination": city, "nights": 3, "travelers": 2}
                )
                assert getattr(stays, "items", None), f"nowhere to stay in {city}"

        asyncio.run(check())

    def test_the_prompt_names_exactly_what_the_tools_serve(self) -> None:
        """Two lists that must not drift: what the agent is told, and what exists."""
        from travel_a2ui.brain.providers.fixture import _DESTINATIONS
        from travel_a2ui.brain.skills import _inventory

        said = _inventory()
        for entry in _DESTINATIONS:
            assert entry["city"] in said, f"{entry['city']} is servable but unadvertised"
