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

import csv
import json
import math
import pathlib
import re
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Sequence

from .types import Found, Outcome, Provenance, found, not_found

_ROOT = pathlib.Path(__file__).resolve().parents[5]
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
_ORIGINS = [
    {
        "code": r["code"],
        "city": r["city"],
        "zones": r["zones"].split("|"),
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
    }
    for r in _rows("origins.csv")
]
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
    """Resolution, without the substring guessing that used to invent airports."""
    trimmed = (query or "").strip()
    if not trimmed:
        return None
    exact = _BY_CODE.get(trimmed.upper())
    if exact:
        return exact
    alias = _BY_ALIAS.get(trimmed.lower())
    if alias:
        return alias
    # A phrase like "a few days in Madrid" still resolves, but only by
    # containing a name we actually know — never by slicing three characters
    # off the front.
    lowered = trimmed.lower()
    for name, entry in _BY_ALIAS.items():
        if name in lowered:
            return entry
    return None


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
        return [{**entry, "zones": list(entry["zones"])} for entry in _ORIGINS]

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
        base = 280 + random() * 260

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

            stops = index == 4 or random() < 0.28
            depart = math.floor(6 * 60 + random() * 15 * 60)
            leg = math.floor((620 if stops else 430) + random() * 140)
            price = base * multiplier * (0.82 if stops else 1) * (0.9 + random() * 0.4)

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
                    "stops": f"1 stop · {_pick(_CONNECTIONS, random)}" if stops else "Nonstop",
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

        start = date.fromisoformat(start_date) if start_date else date.today()
        random = _rng(_seed(f"weather-{resolved['city']}-{start_date or ''}"))
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
