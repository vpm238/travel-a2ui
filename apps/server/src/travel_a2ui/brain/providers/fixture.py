"""The deterministic fixture provider.

Reads `data/` directly — the CSV and JSON a person edits. There is no build step
here and there does not need to be: `scripts/build_fixtures.py` exists only
because a Cloudflare Worker has no filesystem, and this server does.

Determinism is the point. The same query returns the same flights on every run,
so a screenshot stays true and a test can assert on a price. Which means this
port has a harder job than looking right: it has to reproduce the TypeScript's
arithmetic exactly, down to the last dollar, and
`apps/worker/test/__golden__/travel.json` is what says whether it does.

**Three pieces of JavaScript arithmetic had to be emulated rather than
translated.** Each is commented where it lives:

  * bitwise operators coerce to 32 bits, so the seeded RNG needs masking that
    Python's arbitrary-precision integers do not do on their own;
  * `Math.imul` multiplies as 32-bit, keeping the low half;
  * `toFixed` rounds halves away from zero where Python's formatting rounds
    them to even, which is a tenth of a star on a hotel rating.
"""

from __future__ import annotations

from ... import ROOT

import csv
import json
import math
import pathlib
import re
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Sequence

from .types import Found, Outcome, Provenance, found, not_found

_ROOT = ROOT
_DATA = _ROOT / "data"

FIXTURE_PROVENANCE = Provenance(
    source="fixture",
    live=False,
    label="Sample data",
    detail=(
        "Prices, schedules and hotels are generated for this demo and are not real. "
        "City guidance is real. Set AMADEUS_CLIENT_ID to search live inventory."
    ),
)


def _rows(name: str) -> list[dict[str, str]]:
    """Rows from a CSV in `data/`, with `#` comment lines skipped.

    `csv.DictReader` has no notion of a comment, and the comments in those files
    are load-bearing — they are the only place recording that row order seeds
    the picker.
    """
    lines = [
        line
        for line in (_DATA / name).read_text("utf-8").splitlines()
        if not line.startswith("#")
    ]
    return [dict(row) for row in csv.DictReader(lines)]


_DESTINATIONS: list[dict[str, Any]] = json.loads(
    (_DATA / "destinations.json").read_text("utf-8")
)["destinations"]
_AIRLINES = [{"code": r["code"], "name": r["name"]} for r in _rows("airlines.csv")]
_ORIGINS = [{"code": r["code"], "city": r["city"]} for r in _rows("origins.csv")]
_ORIGIN_CODES = {entry["code"] for entry in _ORIGINS}

#: Where each airport is, and what part of the world it is in.
#:
#: The fixtures had no geography and every symptom of it was visible on the
#: first screen: SFO to JFK connecting in Frankfurt, a nonstop to anywhere
#: taking between seven and nine hours, and a fare that did not move with
#: distance while the documentation said it did.
_PLACE: dict[str, dict[str, Any]] = {
    row["code"]: {
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "region": row["region"],
    }
    for row in _rows("origins.csv")
    if row.get("lat")
}

#: Where a connecting flight actually stops.
#:
#: Airports this deployment already knows, so a connection is somewhere the app
#: could talk about rather than three letters nobody can place. Picked from the
#: regions the route touches — which is what makes a domestic hop connect
#: domestically.
_HUBS: dict[str, list[str]] = {
    "north-america": ["ORD", "DEN", "JFK", "LAX", "MIA"],
    "south-america": ["GRU"],
    "europe": ["LHR", "CDG", "FRA", "MAD", "LIS"],
    "middle-east": ["DXB"],
    "asia": ["SIN", "HKG", "NRT", "DEL"],
    "oceania": ["SYD"],
    "africa": ["JNB"],
}


def _distance_km(origin: str, destination: str) -> float | None:
    """Great-circle kilometres between two airports we know.

    `None` when either is unknown, so every caller has to say what it does
    without geography rather than quietly pretending the distance is zero.
    """
    import math

    a, b = _PLACE.get(origin), _PLACE.get(destination)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def _connection(origin: str, destination: str, random: Callable[[], float]) -> str | None:
    """Somewhere a flight between these two would plausibly stop, or nothing.

    `None` means no hub is on the way, and the honest answer is then that this
    route does not have a connecting option — which is true of short ones.
    London to Paris is 347 km and every hub that is not London or Paris adds
    more than double the journey; a "1 stop · FRA" on it is not a cheaper
    alternative, it is a joke at the traveller's expense.

    A hub has to be roughly *on the way*. Region alone is not enough: picking
    from the regions at either end still offered San Francisco to Tokyo via New
    York, and New York to Madrid via Los Angeles — both of them flying several
    thousand kilometres backwards before setting off.

    So every hub is scored by how far it drags the journey — the two legs
    against the direct distance — and only those within a reasonable detour are
    candidates. That is also what makes a domestic hop connect domestically,
    without having to say so: Frankfurt is not on the way from San Francisco to
    New York, so it scores itself out.

    A route between airports we have no geography for falls back to every hub we
    know, which is the old behaviour and at least claims nothing.
    """
    direct = _distance_km(origin, destination)
    candidates = [
        hub
        for hubs in _HUBS.values()
        for hub in hubs
        if hub not in (origin, destination) and hub in _PLACE
    ]

    if direct:
        detours: list[tuple[float, str]] = []
        for hub in candidates:
            first, second = _distance_km(origin, hub), _distance_km(hub, destination)
            if first is None or second is None:
                continue
            detours.append(((first + second) / max(direct, 1.0), hub))
        # A quarter over the direct distance is about where a real connection
        # stops being worth it, and it is tight enough to rule out the ones that
        # fly backwards: San Francisco to Tokyo via Denver is only a third
        # longer and is still pointed the wrong way.
        #
        # Sorted so the pick is stable for a seed regardless of dict order.
        near = sorted(hub for ratio, hub in detours if ratio <= 1.25)
        return _pick(near, random) if near else None

    pool = sorted(hub for hub in candidates if hub not in (origin, destination))
    if not pool:
        pool = sorted(_CONNECTIONS)
    return _pick(pool, random)


_CURRENCY_SYMBOL = {r["code"]: r["symbol"] for r in _rows("currencies.csv")}

_LODGING: dict[str, list[str]] = {}
for _row in _rows("lodging.csv"):
    _LODGING.setdefault(_row["kind"], []).append(_row["value"])

_HOTEL_WORDS = _LODGING["word"]
_HOTEL_NAMES = _LODGING["name"]
_AMENITIES = _LODGING["amenity"]
_CONNECTIONS = _LODGING["connection"]

#: Destinations in the shape the rest of the app wants, without `aliases`.
_DESTINATION_LIST: list[dict[str, Any]] = [
    {
        "city": entry["city"],
        "country": entry["country"],
        "airport": entry["airport"],
        "currency": entry["currency"],
        "bestMonths": entry["bestMonths"],
        "summary": entry["summary"],
        "highlights": [dict(h) for h in entry["highlights"]],
        "neighbourhoods": list(entry["neighbourhoods"]),
    }
    for entry in _DESTINATIONS
]

_BY_CODE = {entry["airport"]: entry for entry in _DESTINATION_LIST}
_BY_ALIAS: dict[str, dict[str, Any]] = {}
for _index, _entry in enumerate(_DESTINATIONS):
    for _alias in _entry["aliases"]:
        _BY_ALIAS[_alias] = _DESTINATION_LIST[_index]

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
    import math

    return items[math.floor(random() * len(items)) % len(items)]


def _js_round(value: float) -> int:
    """`Math.round`: halves toward positive infinity, unlike Python's `round`."""
    import math

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


def _relax_until_non_empty(
    all_items: Sequence[dict[str, Any]],
    filters: list[tuple[str, Callable[[dict[str, Any]], bool]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drops filters until something survives, and reports what was dropped.

    Order is a judgement: a price cap is the constraint a traveller is most
    often willing to hear about being exceeded, while a nonstop requirement is
    often non-negotiable, so the cap goes first.
    """
    active = list(filters)
    relaxed: list[str] = []
    while True:
        items = [item for item in all_items if all(keep(item) for _, keep in active)]
        if items or not active:
            return items, relaxed
        relaxed.append(active.pop(0)[0])


class FixtureProvider:
    """Deterministic travel data, generated from the rows in `data/`."""

    provenance = FIXTURE_PROVENANCE

    async def resolve_destination(self, query: str) -> dict[str, Any] | None:
        return _resolve(query)

    async def destinations(self) -> list[dict[str, Any]]:
        return _DESTINATION_LIST

    async def origins(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in _ORIGINS]

    async def search_flights(self, query: dict[str, Any]) -> Outcome:
        destination = _resolve(query.get("destination") or "")
        if not destination:
            return _unknown_destination(query.get("destination") or "")

        origin = (query.get("origin") or "")[:3].upper()
        sampled: list[str] = []
        if not origin:
            if not query.get("indicative"):
                return not_found(
                    "unknown-origin",
                    FIXTURE_PROVENANCE,
                    "Flights need somewhere to leave from.",
                    [f"{entry['city']} ({entry['code']})" for entry in _ORIGINS[:6]],
                )
            # An explicitly rough question can be answered without a departure
            # city, but not by pretending to have one. The sample is named.
            stand_in = _ORIGINS[0]
            origin = stand_in["code"]
            sampled.append(
                f"no departure city — sampled from {stand_in['city']} ({stand_in['code']})"
            )

        when = query.get("date") or ""
        cabin = query.get("cabin") or "economy"
        random = _rng(_seed(f"{origin}-{destination['airport']}-{when}-{cabin}"))
        multiplier = {"economy": 1, "premium": 1.7, "business": 3.4, "first": 5.6}.get(cabin, 1)

        # How far it actually is, and what that costs.
        #
        # `base` was `280 + random() * 260` — stable per route, and completely
        # unrelated to the route. San Francisco to New York and San Francisco to
        # Sydney were the same price, while the architecture doc claimed prices
        # moved with distance. They do now: a floor for the seat and the airport,
        # plus a rate per kilometre, and the random part narrowed to the spread
        # you would actually see between carriers on one day.
        km = _distance_km(origin, destination["airport"])
        base = (55 + km * 0.055) if km else (280 + random() * 260)

        import math

        all_flights: list[dict[str, Any]] = []
        used: set[str] = set()
        for index in range(5):
            airline = _pick(_AIRLINES, random)
            guard = 0
            while airline["code"] in used and guard < 8:
                airline = _pick(_AIRLINES, random)
                guard += 1
            used.add(airline["code"])

            # Whether it stops, and where. Asked in that order and then
            # reconciled: a route with nowhere sensible to stop has no
            # connecting option at all, however the dice landed.
            wants_stop = index == 4 or random() < 0.28
            hub = _connection(origin, destination["airport"], random) if wants_stop else None
            stops = hub is not None
            depart = math.floor(6 * 60 + random() * 15 * 60)

            # How long it takes, from how far it is.
            #
            # This was `(620 if stops else 430) + random() * 140`: seven to nine
            # and a half hours for a nonstop, whether that nonstop was London to
            # Paris or San Francisco to Sydney. Now it is taxi, climb and descent
            # plus cruise at a shade under 900 km/h — and a stop adds the detour
            # through the hub and an hour or so on the ground.
            if km:
                cruise = 45 + km / 14.0
                leg = math.floor(cruise * (1.18 if stops else 1.0) + (65 + random() * 55 if stops else random() * 25))
            else:
                leg = math.floor((620 if stops else 430) + random() * 140)

            # A connection is cheaper than the nonstop, which is why anyone takes
            # one, and carriers differ by a little rather than by half.
            price = base * multiplier * (0.82 if stops else 1) * (0.92 + random() * 0.22)

            all_flights.append(
                {
                    "id": f"{airline['code']}{1000 + math.floor(random() * 8000)}",
                    "airline": airline["name"],
                    "flightNumber": f"{airline['code']}{100 + math.floor(random() * 899)}",
                    "origin": origin,
                    "destination": destination["airport"],
                    "departTime": _clock(depart),
                    "arriveTime": _clock(depart + leg),
                    "duration": f"{leg // 60}h {leg % 60}m",
                    "stops": f"1 stop · {hub}" if hub else "Nonstop",
                    "price": _money(price, "USD"),
                    "priceValue": _js_round(price),
                    "cabin": cabin,
                }
            )

        filters: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []
        if query.get("maxPrice"):
            cap = query["maxPrice"]
            filters.append(
                (f"the {_money(cap, 'USD')} cap", lambda flight: flight["priceValue"] <= cap)
            )
        if query.get("nonstopOnly"):
            filters.append(("nonstop only", lambda flight: flight["stops"] == "Nonstop"))

        items, dropped = _relax_until_non_empty(all_flights, filters)
        relaxed = sampled + dropped

        items.sort(key=lambda flight: flight["priceValue"])
        items[0]["badge"] = "Cheapest"
        fastest = sorted(items, key=lambda f: _duration_minutes(f["duration"]))[0]
        if fastest["id"] != items[0]["id"]:
            fastest["badge"] = "Fastest"

        shown = items[:4]
        where = f"{origin} → {destination['airport']}" + (f" on {when}" if when else "")
        note = " ".join(
            part
            for part in [
                (
                    f"Nothing matched {' and '.join(dropped)} — closest {len(shown)} for {where}."
                    if dropped
                    else f"{len(shown)} option(s) for {where}."
                ),
                f"Typical fares: {'; '.join(sampled)}." if sampled else "",
            ]
            if part
        )

        return found(shown, FIXTURE_PROVENANCE, note, relaxed, "USD")

    async def search_hotels(self, query: dict[str, Any]) -> Outcome:
        destination = _resolve(query.get("destination") or "")
        if not destination:
            return _unknown_destination(query.get("destination") or "")

        import math

        code = destination["airport"]
        currency = destination["currency"]
        nights = query.get("nights") if query.get("nights") is not None else 5
        neighborhood = query.get("neighborhood") or ""
        random = _rng(_seed(f"hotels-{code}-{nights}-{neighborhood}"))
        areas = destination["neighbourhoods"] or ["Centre"]

        all_hotels: list[dict[str, Any]] = []
        for index in range(5):
            nightly = 95 + random() * 240
            amenity_count = 2 + math.floor(random() * 3)
            amenities: list[str] = []
            # Bounded, like the airline picker beside it. Drawing distinct
            # values out of a seeded sequence terminates in practice and not by
            # construction — and when it does not, an unbounded loop here is a
            # hung request rather than a wrong answer. Found by breaking the
            # RNG's 32-bit masking on purpose and watching the test run for
            # seven minutes instead of failing.
            guard = 0
            while len(amenities) < amenity_count and guard < 32:
                guard += 1
                amenity = _pick(_AMENITIES, random)
                if amenity not in amenities:
                    amenities.append(amenity)
            all_hotels.append(
                {
                    "id": f"h_{code}_{index}",
                    "name": f"{_pick(_HOTEL_WORDS, random)} {_pick(_HOTEL_NAMES, random)}",
                    "neighborhood": neighborhood or _pick(areas, random),
                    "rating": f"{_to_fixed(3.9 + random() * 1.05, 1)} ({200 + math.floor(random() * 1800)})",
                    "price": f"{_money(nightly, currency)} / night",
                    "priceValue": _js_round(nightly),
                    "amenities": amenities,
                }
            )

        filters: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []
        if query.get("maxNightly"):
            cap = query["maxNightly"]
            filters.append(
                (
                    f"the {_money(cap, currency)} a night cap",
                    lambda hotel: hotel["priceValue"] <= cap,
                )
            )

        items, relaxed = _relax_until_non_empty(all_hotels, filters)

        items.sort(key=lambda hotel: hotel["priceValue"])
        items[0]["badge"] = "Best value"
        if len(items) > 2:
            items[-1]["badge"] = "Most central"

        shown = items[:4]
        note = (
            f"Nothing under {' and '.join(relaxed)}. Closest {len(shown)} in {destination['city']}."
            if relaxed
            else f"{len(shown)} stay(s) in {destination['city']} for {nights} night(s)."
        )

        return found(shown, FIXTURE_PROVENANCE, note, relaxed, currency)

    async def get_weather(
        self, destination: str, start_date: str | None = None, days: int = 5
    ) -> Outcome:
        resolved = _resolve(destination)
        if not resolved:
            return _unknown_destination(destination)

        # The clock is the last resort, not the default: every caller in this
        # app passes the day its turn is happening on, precisely so that what
        # comes back does not depend on the day the process runs. See
        # `TravelProvider.get_weather`.
        start = date.fromisoformat(start_date) if start_date else date.today()
        random = _rng(_seed(f"weather-{resolved['city']}-{start.isoformat()}"))
        conditions = ["sun", "sun", "cloud", "cloud", "rain", "fog"]
        weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

        forecast: list[dict[str, str]] = []
        high = 14 + random() * 12
        for index in range(min(max(days, 1), 7)):
            high += random() * 6 - 3
            low = high - (5 + random() * 4)
            day = start + timedelta(days=index)
            forecast.append(
                {
                    # JavaScript's `getUTCDay` is 0 for Sunday; Python's
                    # `weekday()` is 0 for Monday.
                    "day": weekdays[(day.weekday() + 1) % 7],
                    "high": f"{_js_round(high)}°",
                    "low": f"{_js_round(low)}°",
                    "condition": _pick(conditions, random),
                }
            )

        wet = sum(1 for entry in forecast if entry["condition"] == "rain")
        note = (
            "Rain on more than one day — pack a shell."
            if wet > 1
            else "Mostly dry; a light jacket is enough."
        )

        return found(
            [{"place": resolved["city"], "days": forecast, "note": note}],
            FIXTURE_PROVENANCE,
            note,
        )
