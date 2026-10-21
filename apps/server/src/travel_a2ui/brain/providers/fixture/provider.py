"""The provider itself: the eight lookups, answered from the tables.

One class, one method per thing the agent can look up, each returning the
`Found`/`NotFound` the tools expect. Everything it needs to be *deterministic*
is in `numbers`, everything it needs to be *plausible* is in `routes` and
`places`, and everything it knows is in `tables`.
"""

from __future__ import annotations

import math

from datetime import date, timedelta
from typing import Any, Callable

from ..types import Found, Outcome, found, not_found
from .numbers import (
    _clock,
    _duration_minutes,
    _js_round,
    _money,
    _pick,
    _rng,
    _seed,
    _to_fixed,
)
from .places import _resolve, _unknown_destination
from .routes import _carriers_for, _distance_km
from .tables import (
    FIXTURE_PROVENANCE,
    _AIRLINES,
    _AMENITIES,
    _DESTINATION_LIST,
    _HOTELS,
    _HOTEL_NAMES,
    _HOTEL_WORDS,
    _ORIGINS,
    _fold,
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

        # What to price in, and why the caller decides.
        #
        # A trip used to show its fares in dollars and its stays in the
        # destination's currency, and then totalled them together: a card
        # reading "€112 / night" became "$336" three nights later in the same
        # summary. One currency per trip fixes it, and only the caller knows
        # what a trip's currency is — the provider is handed one hop and cannot
        # tell a Copenhagen–Berlin outbound from the Berlin–Copenhagen return.
        # Unset keeps dollars, which is what every direct caller got before.
        fare_currency = str(query.get("currency") or "USD")


        # Carriers that actually fly this route, and how — see `_carriers_for`.
        # An empty pool means a route between airports we have no geography for,
        # and then every carrier is back in, which claims nothing.
        pool = _carriers_for(origin, destination["airport"], km) or [
            {**carrier, "nonstop": True, "via": []} for carrier in _AIRLINES
        ]

        all_flights: list[dict[str, Any]] = []
        used: set[str] = set()
        for index in range(5):
            airline = _pick(pool, random)
            guard = 0
            # Distinct carriers while the pool has them. A short hop with three
            # airlines on it legitimately has two SAS departures in a day, and
            # insisting on five different names is how Delta ended up on it.
            while airline["code"] in used and guard < 8 and len(used) < len(pool):
                airline = _pick(pool, random)
                guard += 1
            used.add(airline["code"])

            # Whether it stops, and where — through a hub this carrier has.
            #
            # The hub used to be picked independently of the airline, so a
            # quarter of the itineraries were things like Iberia via Paris or
            # Delta via Lisbon. A carrier that cannot fly the route nonstop
            # always connects, through its own hub; one that can connects only
            # when the dice say so and it has a hub on the way.
            wants_stop = index == 4 or random() < 0.28
            hub = (
                _pick(airline["via"], random)
                if airline["via"] and (wants_stop or not airline["nonstop"])
                else None
            )
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
                    "price": _money(price, fare_currency),
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

        return found(shown, FIXTURE_PROVENANCE, note, relaxed, fare_currency)

    async def search_hotels(self, query: dict[str, Any]) -> Outcome:
        destination = _resolve(query.get("destination") or "")
        if not destination:
            return _unknown_destination(query.get("destination") or "")


        code = destination["airport"]
        currency = destination["currency"]
        nights = query.get("nights") if query.get("nights") is not None else 5
        neighborhood = query.get("neighborhood") or ""
        random = _rng(_seed(f"hotels-{code}-{nights}-{neighborhood}"))
        areas = destination["neighbourhoods"] or ["Centre"]

        # Stays somebody wrote down, where there are any.
        #
        # The generated ones below are fine for a city nobody is looking at
        # closely and poor for the one on screen: "Casa Verano, Salamanca" at a
        # plausible rate says nothing about why you would take it over the line
        # above. `data/hotels.json` has real-reading stock for the cities this
        # demo is driven through — a pension off the avenue, a business hotel by
        # the station, one place that is too expensive and knows it — and every
        # other city keeps the picker.
        curated = _HOTELS.get(code)
        if curated:
            listed = [
                {
                    "id": hotel["id"],
                    "name": hotel["name"],
                    "neighborhood": hotel["neighborhood"],
                    "rating": hotel["rating"],
                    "price": f"{_money(float(hotel['nightly']), currency)} / night",
                    "priceValue": _js_round(float(hotel["nightly"])),
                    "amenities": list(hotel.get("amenities") or []),
                    **({"note": hotel["note"]} if hotel.get("note") else {}),
                }
                for hotel in curated
            ]
            # The neighbourhood *filters* rather than being written onto every
            # hotel that comes back. It used to be stamped on, so all five
            # claimed to be exactly where you asked, wherever they actually
            # were — "close to Kurfürstendamm" was answered by relabelling
            # Neukölln. A hotel two streets off the avenue is a hit, through its
            # own `near` list; one across the city is not, and when nothing
            # matches `_relax_until_non_empty` says so rather than inventing.
            near_filters: list[tuple[str, Callable[[dict[str, Any]], bool]]] = []
            if neighborhood:
                wanted = _fold(neighborhood)
                places = {
                    hotel["id"]: {_fold(hotel["neighborhood"]), *(_fold(place) for place in hotel.get("near") or [])}
                    for hotel in curated
                }
                near_filters.append(
                    (
                        f"being near {neighborhood}",
                        lambda hotel: any(
                            wanted in place or place in wanted
                            for place in places.get(hotel["id"], set())
                        ),
                    )
                )
            if query.get("maxNightly"):
                cap = query["maxNightly"]
                near_filters.append(
                    (
                        f"the {_money(cap, currency)} a night cap",
                        lambda hotel: hotel["priceValue"] <= cap,
                    )
                )
            items, relaxed = _relax_until_non_empty(listed, near_filters)
            return self._hotel_outcome(items, relaxed, destination, nights, currency)

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
        return self._hotel_outcome(items, relaxed, destination, nights, currency)

    def _hotel_outcome(
        self,
        items: list[dict[str, Any]],
        relaxed: list[str],
        destination: dict[str, Any],
        nights: Any,
        currency: str,
    ) -> Outcome:
        """The same answer whether the stays were written down or generated."""
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
