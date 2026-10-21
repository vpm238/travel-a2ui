"""The data, read straight from `data/`.

The CSV and JSON a person edits: airports, airlines and their hubs, the
destinations and the places inside them, the curated stays, the words a
generated hotel name is built from. No build step, because the server has a
filesystem — `scripts/build_fixtures.py` exists only for a Cloudflare Worker,
which does not.

Everything here is loaded once at import and read-only afterwards. Adding a city
is editing a file in `data/`, which is the point.
"""

from __future__ import annotations

import csv
import json
import re
from typing import Any

from .... import ROOT
from ..types import Provenance

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
_AIRLINES = [
    {
        "code": r["code"],
        "name": r["name"],
        #: Where it flies from. A carrier is offered on a route when one end is
        #: one of these, or when one of these is on the way.
        "hubs": tuple(code for code in (r.get("hubs") or "").split("|") if code),
        #: Blank means no cap.
        "maxKm": float(r["maxKm"]) if r.get("maxKm") else None,
    }
    for r in _rows("airlines.csv")
]
_ORIGINS = [{"code": r["code"], "city": r["city"]} for r in _rows("origins.csv")]

#: Stays somebody wrote down, by airport code. See `data/hotels.json`.
_HOTELS: dict[str, list[dict[str, Any]]] = json.loads(
    (_DATA / "hotels.json").read_text("utf-8")
)["cities"]


def _fold(place: str) -> str:
    """A place name as somebody types it, for comparing two of them.

    "Kurfürstendamm", "kurfurstendamm" and "Kurfürsten-damm" are one avenue.
    Accents go, case goes, and anything that is not a letter or a digit goes,
    because the alternative is a neighbourhood filter that works for the people
    who can reach the u-umlaut.
    """
    import unicodedata

    stripped = unicodedata.normalize("NFKD", place)
    return "".join(
        char for char in stripped.lower() if char.isalnum() and not unicodedata.combining(char)
    )
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
        # Pins, for the surfaces that draw a map. Absent on a generated city,
        # deliberately: see the note in `destinations.json`.
        "places": [dict(p) for p in entry.get("places", ())],
    }
    for entry in _DESTINATIONS
]

_BY_CODE = {entry["airport"]: entry for entry in _DESTINATION_LIST}
_BY_ALIAS: dict[str, dict[str, Any]] = {}
for _index, _entry in enumerate(_DESTINATIONS):
    for _alias in _entry["aliases"]:
        _BY_ALIAS[_alias] = _DESTINATION_LIST[_index]
