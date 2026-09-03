#!/usr/bin/env python3
"""Builds the `a2ui-travel` catalog by extending the upstream A2UI basic catalog.

The A2UI basic catalog (vendored at ``catalogs/basic/catalog.json`` from
google/a2ui ``specification/v0_9_1``) gives us layout and form primitives. A
travel product needs a handful of domain components on top — a flight option, a
hotel card, an itinerary day, a price summary — so that the agent composes
*travel* nouns instead of re-deriving them from rows and columns every turn.

Component schemas here follow exactly the shape the basic catalog uses, because
the Express prompt generator and compiler both crawl `allOf` sub-schemas for
`properties` in declaration order. Declaration order *is* the positional
argument order the model sees, so the order of `props()` entries below is a
prompt-engineering decision, not an implementation detail.

Usage:
    python3 scripts/build_catalog.py [--check]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASIC = ROOT / "catalogs" / "basic" / "catalog.json"
OUT = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

COMMON = "https://a2ui.org/specification/v0_9/common_types.json#/$defs"

CATALOG_ID = "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"

CATALOG_DESCRIPTION = (
    "Plans trips as interactive UI: flight and hotel options, day-by-day"
    " itineraries, price breakdowns, and trip dashboards."
)

CATALOG_INSTRUCTIONS = """\
You are composing travel UI. A few house rules that matter more than anything else:

- Prefer a travel component over hand-assembling one out of Row/Column/Text. If
  you are showing a flight, use FlightOption. If you are showing a night's stay,
  use HotelCard. The host styles these natively and they carry semantics the
  plain layout primitives do not.
- Every option the user could plausibly act on needs an `action`. A flight the
  user cannot select is a screenshot, not an interface.
- Money is always a preformatted display string ("$412", "€1,180 total"). Do not
  emit bare numbers and hope the host formats them.
- Times are display strings in the traveler's local time ("07:15", "Tue 14 Apr").
  The one exception is DateRangePicker, whose bound values are RFC 3339.
- When you present a set of options, bind the user's current choice into the data
  model so a later turn can read it back — e.g. `$/trip/selectedOutbound`.
- Keep a surface to one job. An inline card answers the message it is attached
  to; the sidebar refines the trip in flight; the home surface summarizes.\
"""


def dyn_str(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/DynamicString", "description": desc}


def dyn_num(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/DynamicNumber", "description": desc}


def dyn_bool(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/DynamicBoolean", "description": desc}


def action(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/Action", "description": desc}


def child_list(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/ChildList", "description": desc}


def child(desc: str) -> dict[str, Any]:
    return {"$ref": f"{COMMON}/ComponentId", "description": desc}


def enum(desc: str, values: list[str], default: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "description": desc, "enum": values}
    if default is not None:
        schema["default"] = default
    return schema


def static_list_of(desc: str, keys: dict[str, str]) -> dict[str, Any]:
    """A static array of objects. Static == the compiler forbids `$` bindings here."""
    return {
        "type": "array",
        "description": desc,
        "items": {
            "type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in keys.items()},
            "required": list(keys.keys())[:1],
            "additionalProperties": False,
        },
    }


def component(
    name: str,
    description: str,
    props: dict[str, Any],
    required: list[str],
    checkable: bool = False,
) -> dict[str, Any]:
    all_of: list[dict[str, Any]] = [
        {"$ref": f"{COMMON}/ComponentCommon"},
        {"$ref": "#/$defs/CatalogComponentCommon"},
    ]
    if checkable:
        all_of.append({"$ref": f"{COMMON}/Checkable"})
    all_of.append(
        {
            "type": "object",
            "description": description,
            "properties": {"component": {"const": name}, **props},
            "required": ["component", *required],
        }
    )
    return {"type": "object", "allOf": all_of, "unevaluatedProperties": False}


# --------------------------------------------------------------------------
# The travel components.
#
# Property order below is the positional-argument order the model is taught.
# Put the property a human would say first, first.
# --------------------------------------------------------------------------

TRAVEL_COMPONENTS: dict[str, dict[str, Any]] = {
    "FlightOption": component(
        "FlightOption",
        "A single selectable flight itinerary leg. Use one per option when"
        " presenting a choice of flights; do not build flight rows by hand out of"
        " Row and Text.",
        {
            "airline": dyn_str("Operating carrier, e.g. 'Iberia' or 'Delta'."),
            "departTime": dyn_str("Local departure time as a display string, e.g. '07:15'."),
            "arriveTime": dyn_str(
                "Local arrival time as a display string. Append '+1' when the"
                " flight lands on the next day, e.g. '19:40 +1'."
            ),
            "origin": dyn_str("Origin airport code, e.g. 'JFK'."),
            "destination": dyn_str("Destination airport code, e.g. 'MAD'."),
            "price": dyn_str("Preformatted price including currency, e.g. '$412'."),
            "action": action(
                "Fired when the traveler selects this flight. Required — an"
                " unselectable option is not an interface."
            ),
            "duration": dyn_str("Total travel time as a display string, e.g. '7h 25m'."),
            "stops": dyn_str("Stop summary, e.g. 'Nonstop' or '1 stop · LIS'."),
            "flightNumber": dyn_str("Marketing flight number, e.g. 'IB6250'."),
            "cabin": enum(
                "Cabin the price refers to.",
                ["economy", "premium", "business", "first"],
                "economy",
            ),
            "selected": dyn_bool(
                "Whether this option is currently chosen. Bind it to the data"
                " model so the selection survives a re-render."
            ),
            "badge": dyn_str("Short editorial tag, e.g. 'Cheapest' or 'Fastest'."),
        },
        required=["airline", "departTime", "arriveTime", "origin", "destination", "price", "action"],
    ),
    "HotelCard": component(
        "HotelCard",
        "A place to stay, presented as a rich card with imagery, rating and"
        " nightly price.",
        {
            "name": dyn_str("Property name."),
            "price": dyn_str("Preformatted nightly or total price, e.g. '$186 / night'."),
            "action": action("Fired when the traveler picks or opens this property."),
            "imageUrl": dyn_str("Hero image URL. Omit for a generated placeholder."),
            "neighborhood": dyn_str("Where it is, in words a traveler uses, e.g. 'Malasaña'."),
            "rating": dyn_str("Rating as a display string, e.g. '4.6 (1,204)'."),
            "amenities": {
                "type": "array",
                "description": "Short amenity labels, at most five. Static values only.",
                "items": {"type": "string"},
            },
            "selected": dyn_bool("Whether this property is currently chosen."),
            "badge": dyn_str("Short editorial tag, e.g. 'Walkable' or 'Best value'."),
        },
        required=["name", "price", "action"],
    ),
    "ItineraryDay": component(
        "ItineraryDay",
        "One day of a trip. Its children are the day's ActivityItem components,"
        " in chronological order.",
        {
            "title": dyn_str("Day heading, e.g. 'Day 3 — Toledo'."),
            "children": child_list("The day's activities, earliest first."),
            "date": dyn_str("Date as a display string, e.g. 'Tue 14 Apr'."),
            "summary": dyn_str("One-line character of the day, e.g. 'Old town, slow pace'."),
            "action": action("Fired when the traveler opens or edits the whole day."),
        },
        required=["title", "children"],
    ),
    "ActivityItem": component(
        "ActivityItem",
        "A single scheduled thing inside an ItineraryDay — a meal, a museum, a"
        " transfer, a check-in.",
        {
            "title": dyn_str("What it is, e.g. 'Prado Museum'."),
            "time": dyn_str("Start time as a display string, e.g. '10:00'."),
            "category": enum(
                "Drives the icon and colour the host uses.",
                ["food", "sight", "transit", "stay", "outdoors", "shopping", "event", "free"],
                "sight",
            ),
            "location": dyn_str("Where it happens, e.g. 'Paseo del Prado 23'."),
            "duration": dyn_str("How long to budget, e.g. '2h'."),
            "note": dyn_str("One short practical note, e.g. 'Book the timed entry'."),
            "action": action("Fired when the traveler taps the activity."),
            "done": dyn_bool("Whether the traveler has ticked this off."),
        },
        required=["title"],
    ),
    "MapPreview": component(
        "MapPreview",
        "A lightweight schematic map of the places in play. Not a live map — it"
        " orients the traveler and is safe to render offline.",
        {
            "markers": static_list_of(
                "Places to pin. Static values only — the host lays them out"
                " relative to each other.",
                {
                    "label": "Short place name shown next to the pin.",
                    "kind": "One of 'stay', 'sight', 'food', 'transit'.",
                    "day": "Optional day number this marker belongs to.",
                },
            ),
            "caption": dyn_str("One line describing what the map shows."),
            "action": action("Fired when the traveler taps the map."),
        },
        required=["markers"],
    ),
    "PriceSummary": component(
        "PriceSummary",
        "The money view: an itemized breakdown and a total. Use this instead of"
        " a hand-built table whenever you show what a trip costs.",
        {
            "lines": static_list_of(
                "Itemized cost lines in display order. Static values only.",
                {
                    "label": "What the line is for, e.g. 'Flights (2 travelers)'.",
                    "amount": "Preformatted amount, e.g. '$824'.",
                    "note": "Optional qualifier, e.g. 'refundable'.",
                },
            ),
            "total": dyn_str("Preformatted grand total, e.g. '$2,140'."),
            "totalLabel": dyn_str("What the total is called, e.g. 'Trip total'."),
            "action": action("Primary money action, e.g. hold or book."),
            "actionLabel": dyn_str("Label for that action, e.g. 'Hold for 24h'."),
            "caption": dyn_str("Fine print, e.g. 'Estimated, taxes included'."),
        },
        required=["lines", "total"],
    ),
    "DateRangePicker": component(
        "DateRangePicker",
        "Picks the trip's start and end dates. Both bound values are RFC 3339"
        " timestamps with an offset, e.g. '2026-04-12T00:00:00Z'.",
        {
            "label": dyn_str("What the range is for, e.g. 'When are you going?'."),
            "start": dyn_str("Bound path for the start date (RFC 3339)."),
            "end": dyn_str("Bound path for the end date (RFC 3339)."),
            "action": action("Fired when the traveler commits a new range."),
            "nightsLabel": dyn_str("Derived caption, e.g. '6 nights'."),
        },
        required=["label", "start", "end"],
        checkable=True,
    ),
    "TravelerCounter": component(
        "TravelerCounter",
        "A stepper for party size. Bind `value` so the count survives a"
        " re-render and later turns can read it.",
        {
            "label": dyn_str("What is being counted, e.g. 'Adults'."),
            "value": dyn_num("Bound path holding the current count."),
            "min": {"type": "integer", "description": "Lowest allowed count.", "default": 0},
            "max": {"type": "integer", "description": "Highest allowed count.", "default": 9},
            "caption": dyn_str("Qualifier, e.g. 'Age 12+'."),
        },
        required=["label", "value"],
        checkable=True,
    ),
    "StatTile": component(
        "StatTile",
        "One number that matters, sized for a dashboard grid. Home-surface"
        " staple: days until departure, budget left, bookings confirmed.",
        {
            "label": dyn_str("What the number measures."),
            "value": dyn_str("The number as a display string, e.g. '17'."),
            "caption": dyn_str("Context under the number, e.g. 'until Madrid'."),
            "tone": enum(
                "Colour role for the tile.",
                ["neutral", "positive", "caution", "critical", "accent"],
                "neutral",
            ),
            "action": action("Fired when the traveler taps the tile."),
        },
        required=["label", "value"],
    ),
    "ProgressMeter": component(
        "ProgressMeter",
        "How far along something is — budget spent, packing done, bookings"
        " confirmed. `value` and `max` are numbers, not display strings.",
        {
            "label": dyn_str("What is progressing."),
            "value": dyn_num("Current amount."),
            "max": dyn_num("Amount that counts as complete."),
            "caption": dyn_str("Reading in words, e.g. '$1,320 of $2,000'."),
            "tone": enum(
                "Colour role for the bar.",
                ["neutral", "positive", "caution", "critical", "accent"],
                "accent",
            ),
        },
        required=["label", "value", "max"],
    ),
    "WeatherStrip": component(
        "WeatherStrip",
        "A short forecast row for the destination. Purely informational.",
        {
            "days": static_list_of(
                "Forecast entries in date order, at most seven. Static values only.",
                {
                    "day": "Short day label, e.g. 'Tue'.",
                    "high": "High temperature as a display string, e.g. '21°'.",
                    "low": "Low temperature as a display string.",
                    "condition": "One of 'sun', 'cloud', 'rain', 'storm', 'snow', 'fog'.",
                },
            ),
            "place": dyn_str("Where the forecast is for."),
            "caption": dyn_str("One line of interpretation, e.g. 'Pack a light jacket'."),
        },
        required=["days"],
    ),
    "ExpenseSplit": component(
        "ExpenseSplit",
        "Splits a shared trip cost between travelers and shows who owes what.",
        {
            "title": dyn_str("What was paid for, e.g. 'Dinner at Sobrino'."),
            "total": dyn_str("Preformatted total, e.g. '€96'."),
            "participants": static_list_of(
                "Who is splitting it. Static values only.",
                {
                    "name": "Traveler's name.",
                    "share": "Their share, preformatted, e.g. '€32'.",
                    "status": "One of 'paid', 'owes', 'settled'.",
                },
            ),
            "action": action("Fired when the traveler settles or edits the split."),
            "actionLabel": dyn_str("Label for that action, e.g. 'Settle up'."),
        },
        required=["title", "total", "participants"],
    ),
}


def build() -> dict[str, Any]:
    basic = json.loads(BASIC.read_text(encoding="utf-8"))

    catalog: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CATALOG_ID,
        "catalogId": CATALOG_ID,
        "title": "A2UI Travel Catalog",
        "description": CATALOG_DESCRIPTION,
        "instructions": CATALOG_INSTRUCTIONS,
        "extends": basic["catalogId"],
        "components": {**basic["components"], **TRAVEL_COMPONENTS},
        "functions": dict(basic["functions"]),
        "$defs": dict(basic["$defs"]),
    }

    # `anyComponent` / `anyFunction` are the catalog's own union of what it
    # offers; extending the component map without extending the union would
    # leave the travel components unvalidatable.
    any_component = catalog["$defs"].get("anyComponent")
    if isinstance(any_component, dict) and "oneOf" in any_component:
        existing = {json.dumps(x, sort_keys=True) for x in any_component["oneOf"]}
        for name in TRAVEL_COMPONENTS:
            ref = {"$ref": f"#/components/{name}"}
            if json.dumps(ref, sort_keys=True) not in existing:
                any_component["oneOf"].append(ref)

    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the checked-in catalog is stale instead of rewriting it.",
    )
    args = parser.parse_args()

    catalog = build()
    rendered = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != rendered:
            print(f"{OUT} is stale — run: python3 scripts/build_catalog.py", file=sys.stderr)
            return 1
        print(f"{OUT.relative_to(ROOT)} is up to date.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(
        f"Wrote {OUT.relative_to(ROOT)}: "
        f"{len(catalog['components'])} components "
        f"({len(TRAVEL_COMPONENTS)} travel), {len(catalog['functions'])} functions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
