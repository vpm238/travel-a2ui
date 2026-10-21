"""Finding the place somebody asked for, and inventing one when it is not here.

`data/destinations.json` has a few dozen cities in it and travellers ask about
all of them. A provider that said "I do not know that city" for everything else
would make the agent look broken rather than the fixture look small, so an
unknown destination is invented — deterministically, from the name — and
labelled as invented in its provenance, which is what keeps it honest.
"""

from __future__ import annotations

from typing import Any

from ..types import not_found
from .numbers import _pick, _rng, _seed
from .tables import FIXTURE_PROVENANCE, _BY_ALIAS, _BY_CODE, _DESTINATION_LIST

def _resolve(query: str) -> dict[str, Any] | None:
    """The destination this names, invented if nobody wrote it down.

    Nine cities have hand-written detail — real neighbourhoods, real highlights,
    the month the weather turns. Everything else is generated, deterministically,
    from the name itself.

    That is the right trade for a demo. Refusing Boston because nobody typed
    Boston into a JSON file teaches a visitor nothing about generative UI and
    makes the agent look broken; a plausible Boston, labelled sample data like
    every other number here, shows exactly what the interface does. The honesty
    lives in the provenance label, which travels with every figure, rather than
    in a short list of places.

    What is still refused is a query that names no place at all — an empty
    string, a stray punctuation mark — because inventing a city for *that* is
    answering a question nobody asked.
    """
    trimmed = (query or "").strip()
    if not trimmed:
        return None
    exact = _BY_CODE.get(trimmed.upper())
    if exact:
        return exact
    alias = _BY_ALIAS.get(trimmed.lower())
    if alias:
        return alias
    # A phrase like "a few days in Madrid" still resolves to the written-down
    # Madrid, rather than inventing a city called "a few days in madrid".
    lowered = trimmed.lower()
    for name, entry in _BY_ALIAS.items():
        if name in lowered:
            return entry
    return _invent_destination(trimmed)


#: What a generated destination is built from.
#:
#: Written as pools rather than sentences so the result reads like a place and
#: not like a template: "Dense, walkable and late-running" is Madrid's, and a
#: generated city gets its own combination rather than Madrid's words with the
#: name swapped.
_INVENTED_SUMMARY = (
    "Compact enough to walk, with the good part a few streets back from the obvious one.",
    "Low-rise and slow until about nine, then busy until very late.",
    "A working city that happens to be beautiful, best out of season.",
    "Water on one side, hills on the other, and the food better than the guidebooks say.",
    "Old centre, new edges, and a tram that takes you between them for almost nothing.",
)
_INVENTED_MONTHS = (
    "April–June, September–October",
    "March–May, October",
    "May–July",
    "September–November",
    "February–April, November",
)
_INVENTED_AREAS = (
    ("Old Town", "Riverside", "The Market Quarter", "Hillside", "The Docks"),
    ("Centro", "North Bank", "The Gardens", "Station District", "Upper Town"),
    ("The Lanes", "Harbour", "Museum Quarter", "Greenway", "Southgate"),
)
_INVENTED_HIGHLIGHTS = (
    ("The city museum", "sight", "Free on the first Sunday"),
    ("The covered market", "food", "Lunch counters at the back, not the front"),
    ("The old quarter on foot", "sight", "An hour, unhurried, before the tour groups"),
    ("The park above the town", "outdoors", "Best light in the last hour of daylight"),
    ("An evening at the waterfront", "free", "Where everyone else goes, and rightly"),
)


def _invent_destination(name: str) -> dict[str, Any]:
    """A place the data does not have, made up the same way every time.

    Seeded on the name, so "Boston" is the same Boston on every turn, in every
    session and in every screenshot — which is the property that makes generated
    data usable at all. A demo that invents a different city each time you ask
    is worse than one that refuses.
    """
    cleaned = " ".join(word.capitalize() for word in name.split())[:60]
    random = _rng(_seed(f"destination-{cleaned.lower()}"))
    areas = _pick(_INVENTED_AREAS, random)
    highlights = [
        {"name": item[0], "category": item[1], "note": item[2]} for item in _INVENTED_HIGHLIGHTS
    ]

    # A three-letter code from the name rather than a real IATA lookup: it is
    # only ever used to seed prices and to show beside the city, and inventing a
    # code that belongs to a *different* real airport would be worse than one
    # that obviously belongs to nothing.
    letters = [character for character in cleaned.upper() if character.isalpha()]
    code = "".join(letters[:3]) if len(letters) >= 3 else (cleaned.upper() + "XXX")[:3]

    return {
        "airport": code,
        "city": cleaned,
        "country": "",
        "currency": "USD",
        "bestMonths": _pick(_INVENTED_MONTHS, random),
        "summary": _pick(_INVENTED_SUMMARY, random),
        "aliases": [cleaned.lower()],
        "neighbourhoods": list(areas),
        "highlights": highlights,
        # No `places`, and that is the point. Everything else here is invented
        # and labelled as invented, which a reader can discount. A coordinate
        # cannot be discounted: it does not look generated, it looks surveyed,
        # and a map is believed in a way a sentence is not. So a city nobody
        # wrote down gets no pins, and the surface that wanted a map draws
        # something else.
        "places": [],
        # Said plainly, because everything downstream shows provenance and this
        # is a stronger claim than "sample data": nobody wrote this city down.
        "invented": True,
    }


def _elsewhere() -> list[str]:
    return [f"{entry['city']}, {entry['country']}" for entry in _DESTINATION_LIST]


def _unknown_destination(query: str):
    places = _elsewhere()
    return not_found(
        "unknown-destination",
        FIXTURE_PROVENANCE,
        # Counted rather than written down. It said "six cities" for exactly as
        # long as it took to add three more.
        f"This demo does not have data for “{query}”. It covers {len(places)} cities.",
        places,
    )
