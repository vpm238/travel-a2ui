#!/usr/bin/env python3
"""Builds the `a2ui-travel` catalog by extending the A2UI v1.0 basic catalog.

The basic catalog comes from the A2UI SDK itself — `a2ui.core.basic_catalog`'s
bundled v1.0 catalog — and gives us layout and form primitives. It used to be a
copy vendored from 0.9.1 and patched toward 1.0, and the patches missed things:
`Text` still offered `h1`…`h5`, which v1.0 removed (a heading is Markdown in
the text), so every heading this app drew was rejected by `@a2ui/web_core`'s
renderer, while our own validator, reading our copy, passed it. Taking the
catalog from the SDK means the two cannot disagree. A travel product needs a handful of domain components on top — a flight option, a
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
OUT = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

#: Where the protocol's shared types live, for this catalog's `$ref`s.
#:
#: 1.0, because this catalog declares 1.0 — and version-qualified rather than
#: the relative `common_types.json#/$defs/…` the spec now prefers, because a
#: relative reference is resolved against wherever the file happens to be, and
#: this one is read from three places: the SDK, the renderer, and the gallery
#: build. An absolute reference means the same thing from all of them.
COMMON = "https://a2ui.org/specification/v1_0/common_types.json#/$defs"

CATALOG_ID = "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json"

#: The protocol this catalog is written against.
#:
#: One place, read by everything downstream: the server takes its wire version
#: from the generated catalog, and the renderer is held to the same number by
#: `test_upstream_contract`. A catalog that omits this is 0.9 by the spec's
#: default, which is the quiet way to ship a 1.0 server that speaks 0.9.
PROTOCOL_VERSION = "1.0"

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
- **A list of results is one call: `Flights()` or `Stays()`.** `search_flights`
  files its rows at `/flights` and `search_hotels` at `/hotels`, and those two
  read them — bound, labelled, pressable, however many arrive. Never write a
  fare card per result: re-typing what a lookup just handed you is the largest
  thing a turn says and the only part of it that can be wrong.

      fares = Flights("Outbound · JFK → MAD", "/trip/selectedOutbound")

  Pass the heading, the path your choice is recorded at, and the hop when it is
  not the first. The macro draws that heading itself, so do not also write a
  `Text` with the same words above it: the traveller reads the line twice.
- **Draw it before you call the lookup.** The shape of the answer is known the
  moment you decide to look something up, and `Flights()` is nine characters —
  so put it on screen, then call the tool, and the traveller watches it fill in
  instead of waiting at a blank space.
- **A planning turn draws `Highlights()` first.** `get_destination` files what
  a city is worth going for at `/highlights`, and that is the one thing on a
  planning turn whose shape is known early. Writing the days into `save_trip`
  is the longest thing you say and nothing about the plan exists until it is
  written, so draw the highlights while you write it. Without this the
  traveller waits at an empty space for the whole plan.
- **And then sends the plan's heading with it.** `save_trip({days: […], draw:
  {heading: "Four days in Berlin"}})` draws `Itinerary()` the moment the write
  lands. Saying `Itinerary()` in a block of your own afterwards is correct and
  costs a whole further round for nine characters — measured at 16.7s. The
  result tells you the card is up; say one sentence and end the turn.
- Every option the user could plausibly act on needs an `action`. A flight the
  user cannot select is a screenshot, not an interface.
- And every one of them needs a name. A card is read aloud in the order it is
  written — "Iberia IB6250 18:40 JFK 08:15 +1 MAD 7h 35m Nonstop $412", every
  fact and no sentence — so write the sentence:
  `accessibility={label: "Iberia IB6250, 18:40 JFK to 08:15 next day MAD, nonstop, $412"}`.
  Name every fare, every stay, every tile anyone can press. It replaces the
  card's own text rather than adding to it, so say the whole thing.
- Money is always a preformatted display string ("$412", "€1,180 total"). Do not
  emit bare numbers and hope the host formats them.
- Times are display strings in the traveler's local time ("07:15", "Tue 14 Apr").
  The one exception is DateRangePicker, whose bound values are calendar dates
  ("2026-04-12"): a trip day is a day, not an instant in some time zone.
- When you present a set of options, bind the user's current choice into the data
  model so a later turn can read it back — e.g. `$/trip/selectedOutbound`.
- Keep a surface to one job. An inline card answers the message it is attached
  to; the sidebar refines the trip in flight; the home surface summarizes.
- `accessibility` also carries `live: "polite"` for a value that re-reckons
  itself and `hidden: true` for decoration. Leave the block off anything whose
  own text already reads as a sentence.\
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


#: A point, in the shape `@googlemaps/a2ui` uses.
#:
#: `lng`, not `lon`, and that is not a preference. This catalog's `GoogleMap` is
#: the same component Google publishes, property for property, so a payload this
#: app composes renders in their Lit host and one of theirs renders here. The
#: moment the spelling drifts that stops being true, and the only thing gained
#: is agreeing with `destinations.json`, which the agent reads anyway.
def _lat_lng(desc: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": desc,
        "properties": {
            "lat": dyn_num("Latitude, in degrees."),
            "lng": dyn_num("Longitude, in degrees."),
        },
        "required": ["lat", "lng"],
        "additionalProperties": False,
    }


def _map_pin(desc: str) -> dict[str, Any]:
    """A point on the map. Coordinates are required; the label is not.

    `label` used to be required, and it cost a turn every time somebody asked
    for a multi-city route. A marker wants a label — it is a place, and an
    unnamed pin says nothing — but the ends of a `routes` leg are the two ends
    of a drawn line, and the model writes them the obvious way:

        routes=[{origin: {lat: 37.62, lng: -122.38},
                 destination: {lat: 41.98, lng: -87.90}}]

    That failed, and failed badly. One missing `label` inside `routes[0]` takes
    down the whole `GoogleMap` branch of `allOf`, so `unevaluatedProperties`
    then reports `center`, `zoom` and `routes` as unexpected too — an error
    naming four things when one was wrong. And because a message fails whole,
    the surface with it: the traveller watched the entire form — three date
    inputs, two traveller counters — get drawn, vanish and be asked again.

    So the renderer's own view wins, because it was always the honest one: it
    reads `label` through `resolveText`, which yields an empty string when
    there is none, and route ends are already drawn with `label: ''`. An
    unlabelled point is a point.
    """
    return {
        "type": "object",
        "description": desc,
        "properties": {
            "lat": dyn_num("Latitude, in degrees."),
            "lng": dyn_num("Longitude, in degrees."),
            "label": dyn_str(
                "What the pin says on the map. Worth giving on a marker, which"
                " is a place somebody is choosing between; unnecessary on the"
                " ends of a route, which are just the ends of a line."
            ),
            "placeId": dyn_str("Google place id, when one is known."),
        },
        "required": ["lat", "lng"],
        "additionalProperties": False,
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
            # Last, and that is load-bearing: declaration order *is* the
            # positional argument order the model is taught, so a field inserted
            # next to `price` would silently renumber every argument after it
            # and invalidate every example, golden and Express block already
            # written. Appending costs nothing and breaks nothing.
            "total": dyn_str(
                "What this flight costs for everyone on this leg, when that is"
                " more than one person — preformatted, e.g. '$522 for 2'. Give it"
                " whenever the leg carries a party, and `price` is then read as"
                " the per-traveler fare."
            ),
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
            # A `DynamicStringList`, not a static array, which it was for no
            # reason the protocol gives: it is a list of strings, and 1.0 has a
            # type for a list of strings that may also be a path. Static meant
            # the compiler rejected `amenities=$amenities`, so a stay card
            # drawn once per row — the `Stays()` macro, every host-composed
            # surface — had to drop its chips altogether.
            "amenities": {
                "$ref": f"{COMMON}/DynamicStringList",
                "description": "Short amenity labels, at most five.",
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
            "onAdd": action(
                "Fired when the traveler wants something else in this day."
            ),
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
            # A day plan is a draft, not a decision. Every other surface in this
            # catalog asks a question and locks the answer; this one is a list
            # somebody pushes around — drop the museum, move the lunch — and a
            # list you cannot remove from is a list you argue with in prose.
            "onRemove": action(
                "Fired when the traveler drops this activity. Give every activity"
                " one: a day plan is theirs to edit."
            ),
        },
        required=["title"],
    ),
    "GoogleMap": component(
        "GoogleMap",
        "A real Google map, for decisions that are about distance: which stay"
        " to pick given what is near it, whether a multi-city order makes"
        " sense, how far a day's walking really is. It draws nothing and asks"
        " nothing, so pair it with the controls for the decision it"
        " illustrates — and do not use it to confirm a destination, which is"
        " a question nobody asked.",
        {
            "center": _lat_lng("Where the map is centred."),
            "zoom": dyn_num(
                "How close in. 4 spans a continent, 11 a city, 14 a"
                " neighbourhood, 16 a street. Above 16 is clamped."
            ),
            "tilt": dyn_num("Degrees of tilt. Only has an effect in satellite mode."),
            "heading": dyn_num("Compass heading, in degrees."),
            "mode": enum(
                "Map style. Leave it alone unless somebody asks to see the"
                " terrain: a road map is what people read a decision off,"
                " and satellite imagery is beautiful and hard to compare"
                " two places on.",
                ["roadmap", "satellite"],
                "roadmap",
            ),
            "anchorMarker": _map_pin("The one place this map is about, marked apart from the rest."),
            "markers": {
                "type": "array",
                "description": "Pins to drop. Static list — write them out.",
                "items": _map_pin("A pin."),
            },
            "origin": _lat_lng("Start of a single route."),
            "destination": _lat_lng("End of a single route."),
            "travelMode": enum(
                "How the route is travelled.",
                ["driving", "walking", "bicycling", "transit"],
            ),
            "routes": {
                "type": "array",
                "description": "Several legs at once, drawn end to end.",
                "items": {
                    "type": "object",
                    "properties": {
                        "origin": _map_pin("Where the leg starts."),
                        "destination": _map_pin("Where the leg ends."),
                    },
                    "required": ["origin", "destination"],
                    "additionalProperties": False,
                },
            },
        },
        required=["center", "zoom"],
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
    #: Where from, where to — as a flight search asks it.
    #:
    #: It was a `ChoicePicker` of airports, which the basic catalog draws as a
    #: column of radio buttons: twenty-one of them for "Flying from", read top
    #: to bottom to find your city. A search field that narrows as you type is
    #: the control every flight site uses for exactly this question, and it
    #: still cannot hold an airport this deployment does not fly.
    "AirportPicker": component(
        "AirportPicker",
        "A search field for one place — where the trip leaves from or goes to —"
        " with a type-ahead list of the places this deployment serves. Use it"
        " for an origin or a destination; never a ChoicePicker of airports.",
        {
            "label": dyn_str("The question, e.g. 'Where from?'."),
            "value": dyn_str(
                "Bound path the chosen option's `value` is written to, e.g."
                " `$/trip/origin`."
            ),
            "options": static_list_of(
                "Every place that may be chosen. Static values only.",
                {
                    "value": "What is stored when chosen, e.g. 'JFK' or 'Madrid'.",
                    "label": "The place as a person names it, e.g. 'New York'.",
                    "code": "Its airport code, e.g. 'JFK'.",
                    "detail": "A second line, e.g. 'Spain' or 'North America'.",
                },
            ),
            "kind": enum(
                "Which end of the trip this is; sets the icon.",
                ["origin", "destination"],
                "origin",
            ),
            "placeholder": dyn_str("Hint in the empty field, e.g. 'City or airport'."),
        },
        required=["label", "value", "options"],
        checkable=True,
    ),
    "DateRangePicker": component(
        "DateRangePicker",
        "Picks the trip's start and end dates. Both bound values are ISO 8601"
        " calendar dates with no time or offset, e.g. '2026-04-12'.",
        {
            "label": dyn_str("What the range is for, e.g. 'When are you going?'."),
            "start": dyn_str("Bound path for the start date (yyyy-MM-dd)."),
            "end": dyn_str("Bound path for the end date (yyyy-MM-dd)."),
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
    "TripCalendar": component(
        "TripCalendar",
        "The trip's dates on a month grid: the travel days drawn as one"
        " highlighted band, with a glyph on any day worth marking. Read-only —"
        " use it wherever a traveler should *see* when they are going (the panel,"
        " the home surface, beside a chosen flight), and DateRangePicker when they"
        " are still choosing.",
        {
            "start": dyn_str(
                "First travel day as yyyy-MM-dd, e.g. '2027-04-12'. Bind it to"
                " the trip — `$/trip/startDate` — so the band moves when the"
                " dates do."
            ),
            "end": dyn_str(
                "Last travel day as yyyy-MM-dd. Omit for a single day; the band"
                " runs from `start` to here inclusive."
            ),
            "marks": static_list_of(
                "Days worth a glyph, in date order. Static values only — a"
                " departure, a check-in, the one thing booked that day.",
                {
                    "date": "The day, as yyyy-MM-dd.",
                    "icon": (
                        "A short glyph for the day: an emoji, or one of 'plane',"
                        " 'bed', 'food', 'sight', 'transit', 'outdoors', 'event'."
                    ),
                    "label": "What the glyph means, e.g. 'Fly out' — shown in the key.",
                },
            ),
            "title": dyn_str("Heading, e.g. 'Madrid' or 'Six nights in April'."),
            "caption": dyn_str("One line under the grid, e.g. '6 nights · flights booked'."),
            "action": action("Fired when the traveler taps the calendar, e.g. to change the dates."),
        },
        required=["start"],
    ),
}


#: Travel arithmetic the client can do for itself.
#:
#: A2UI functions run *in the renderer*, so a label bound to one recomputes the
#: instant a date changes: no model turn, no round trip, no token. Nights is the
#: number every stay question hangs off ("3 nights, $291 a night").
#:
#: Written in the v1.0 shape the catalog schema requires: the call name under
#: `@call`, and `returnType` at the top level. Where a function may run is the
#: spec's `allowedCallers`, which defaults to the renderer.
TRAVEL_FUNCTIONS: dict[str, dict[str, Any]] = {
    #: Whether two values are the same, for a card that should be marked chosen.
    #:
    #: A list row's `selected` is a boolean, and what the trip records is an id.
    #: Binding the one to the other gave every row the chosen id — a string,
    #: which no renderer reads as `true` — so the fare you picked was never
    #: marked on any list. The comparison has to happen per row, where the row's
    #: own id is in scope, and the basic catalog has no equality function.
    "equals": {
        "type": "object",
        "returnType": "boolean",
        "description": (
            "Returns true when the two values are equal, compared as text. For marking a "
            "list row chosen: selected=equals(a: ${id}, b: ${/trip/selectedFlight})."
        ),
        "properties": {
            "@call": {"const": "equals"},
            "args": {
                "type": "object",
                "properties": {
                    "a": dyn_str("The first value, usually the row's own id."),
                    "b": dyn_str("The second value, usually what the trip recorded."),
                },
                "required": ["a", "b"],
                "unevaluatedProperties": False,
            },
        },
        "required": ["@call", "args"],
    },
    "calcNights": {
        "type": "object",
        "returnType": "number",
        "description": (
            "Returns the number of nights between two ISO-8601 dates (yyyy-MM-dd), "
            "counting the nights slept rather than the days spanned: a 12th-to-15th "
            "stay is 3. Returns 0 when either date is missing or the range is "
            "inverted, so a half-filled form shows a zero rather than nonsense."
        ),
        "properties": {
            "@call": {"const": "calcNights"},
            "args": {
                "type": "object",
                "properties": {
                    "start": dyn_str("The check-in date, as yyyy-MM-dd."),
                    "end": dyn_str("The check-out date, as yyyy-MM-dd."),
                },
                "required": ["start", "end"],
                "unevaluatedProperties": False,
            },
        },
        "required": ["@call", "args"],
    },
}


def _own_properties_lead(component: dict[str, Any]) -> dict[str, Any]:
    """Puts a component's own properties ahead of the shared ones in `allOf`.

    `allOf` is unordered as far as JSON Schema is concerned: every branch has to
    hold and nothing about validation depends on which comes first. What does
    depend on it is the Express notation — the SDK's schema helper crawls
    `[schema, *schema["allOf"]]` in order, and that crawl *is* the positional
    argument order the model is taught. Whichever block comes first owns
    argument one.

    The `$ref`s came first, here and in the upstream basic catalog, and that was
    survivable only by accident: a2ui-core 0.1.1 left a local `$ref`
    unresolved, so `CatalogComponentCommon` contributed no properties and `text`
    kept first place. Core 0.2.0 resolves it. `weight` — a layout hint nobody
    passes positionally — became argument one of every component in the
    catalog, `Text("Madrid")` compiled to `{"component": "Text", "weight":
    "Madrid"}`, and every surface in the app failed validation at once.

    Applied to the basic catalog's components as well as this one's, because
    the upstream ones are where `Text` and `Column` come from and they had the
    same ordering. Stating it here rather than relying on how a dependency
    treats a `$ref` is the point: `Text` is `text, variant, weight`, `Column` is
    `children, justify, align, weight`.
    """
    out = json.loads(json.dumps(component))
    all_of = out.get("allOf")
    if not isinstance(all_of, list):
        return out
    own = [s for s in all_of if isinstance(s, dict) and isinstance(s.get("properties"), dict)]
    shared = [s for s in all_of if s not in own]
    out["allOf"] = [*own, *shared]
    return out


def _label_leads(component: dict[str, Any]) -> dict[str, Any]:
    """Moves `label` to the front of a component's properties, and requires it.

    Declaration order *is* the positional argument order the model is taught —
    the module docstring says so — and `DateTimeInput` arrives from the basic
    catalog ordered `(value, enableDate, enableTime, min, max, label)`. Every
    other input in this catalog is label-first: `TextField(label, value)`,
    `TravelerCounter(label, value)`, `DateRangePicker(label, start, end)`,
    `CheckBox(label, value)`.

    So a model that has learned the pattern from all of those writes
    `DateTimeInput("Departure", $/trip/startDate)` — and the label lands on
    `value`, the binding lands on `enableDate`, and `enableDate` is static, so
    the surface does not compile. The one component that breaks the pattern is
    the one every date question needs, which is why "it almost always fails on
    date input" was a fair description.

    Reordering is safe on both sides: renderers read properties by name, and the
    compiler emits them by name. The only thing that changes is the order the
    model is taught to pass them in.

    The `required` half is not optional, and leaving it out was its own bug. A
    leading argument that may be omitted makes the *rest* of the positions
    ambiguous, and nothing downstream can tell which reading was meant:

        DateTimeInput($/trip/startDate)

    is the natural way to write the one required property, and it compiled —
    silently — to a component whose binding had landed on `label` and which had
    no `value` at all. The compiler had no complaint, so the first objection
    came from the whole-message validator at the end of the turn, as a schema
    dump naming no component and no property. `validate` covers every message,
    so the surface died entire: one date field, and nothing on the screen.

    Every other label-first input in this catalog already requires its label —
    `TextField`, `TravelerCounter`, `CheckBox`, `DateRangePicker` — which is
    exactly why none of them has this hole. `DateTimeInput` was the one that led
    with an optional argument. Requiring the label closes it, and a model that
    omits it now gets a compile error that names the component and the property,
    in time for the repair turn to fix it.
    """
    out = json.loads(json.dumps(component))
    for sub in out.get("allOf", []):
        props = sub.get("properties")
        if not isinstance(props, dict) or "label" not in props:
            continue
        sub["properties"] = {
            "component": props["component"],
            "label": props["label"],
            **{k: v for k, v in props.items() if k not in ("component", "label")},
        }
        required = sub.get("required")
        if isinstance(required, list) and "label" not in required:
            # After `component`, so the order still reads as the signature does.
            sub["required"] = [required[0], "label", *required[1:]]
    return out


#: What 1.0 says a component may carry for assistive technology.
#:
#: Copied rather than `$ref`-ed at the spec, because the catalog is read by the
#: renderer as well as the SDK and the renderer has no schema resolver. The
#: shape is the spec's `AccessibilityAttributes` exactly — a short `label`, a
#: longer `description`, an ARIA `live` politeness, and `hidden` for decoration
#: a screen reader should skip.
ACCESSIBILITY = {
    "type": "object",
    "description": (
        "Attributes to enhance accessibility when using assistive technologies "
        "like screen readers."
    ),
    "properties": {
        "label": {
            "$ref": f"{COMMON}/DynamicString",
            "description": (
                "A short string, typically 1 to 3 words, conveying the purpose of "
                "this element — 'Outbound flight', 'Remove activity'."
            ),
        },
        "description": {
            "$ref": f"{COMMON}/DynamicString",
            "description": (
                "More, where the label is not enough: instructions, a format, or "
                "what pressing this will do."
            ),
        },
        "live": {
            "type": "string",
            "enum": ["off", "polite", "assertive"],
            "default": "off",
            "description": (
                "Announce changes to this element as they happen. `polite` waits "
                "for a pause, `assertive` interrupts. Use it on something that "
                "updates by itself — a price that re-reckons, a list that fills."
            ),
        },
        "hidden": {
            "$ref": f"{COMMON}/DynamicBoolean",
            "description": "Hide this from assistive technology — decoration only.",
        },
    },
    "additionalProperties": False,
}


#: Where the SDK's basic catalog points its shared types: relative, as the spec
#: now writes them. Made absolute here; see `COMMON` for why.
SDK_COMMON = "common_types.json#/$defs"


def _at_declared_version(node: Any) -> Any:
    """Every reference to the shared types, written one way: absolute, at 1.0.

    The SDK's catalog writes them relative (`common_types.json#/$defs/…`), and a
    relative reference resolves against wherever the file is read from — the
    SDK, the renderer and the gallery build read this one from three places.
    """
    if isinstance(node, dict):
        return {
            key: (
                COMMON + value[len(SDK_COMMON):]
                if key == "$ref" and isinstance(value, str) and value.startswith(SDK_COMMON)
                else _at_declared_version(value)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_at_declared_version(item) for item in node]
    return node


def _defs_for_1_0(defs: dict[str, Any]) -> dict[str, Any]:
    """The basic catalog's definitions, and what the travel components share.

    The travel components carry `accessibility` through `CatalogComponentCommon`.
    1.0 made plumbing it normative for renderers, and it is the one thing in the
    protocol the agent cannot route around: a traveller using a screen reader
    gets whatever the agent labelled.
    """
    out = dict(defs)
    out["AccessibilityAttributes"] = ACCESSIBILITY

    shared = dict(out.get("CatalogComponentCommon") or {"type": "object", "properties": {}})
    shared["properties"] = {
        "weight": {"$ref": "#/$defs/Weight"},
        **(shared.get("properties") or {}),
        "accessibility": {
            "$ref": "#/$defs/AccessibilityAttributes",
            # Names the keys rather than describing the idea, because the
            # positional signature the model is taught shows the argument but
            # not its shape, and a property you cannot see the shape of is a
            # property nobody can set. One line, repeated on every component,
            # so it is worth the four words it costs.
            "description": "Assistive technology: {label, description, live, hidden}.",
        },
    }
    out["CatalogComponentCommon"] = shared
    return out


def build() -> dict[str, Any]:
    """The travel catalog: the SDK's v1.0 basic catalog, derived.

    `Catalog.derive` keeps every basic component and function, adds the travel
    ones, and writes the `anyComponent` and `anyFunction` unions to match, so
    nothing here patches a union by hand. What is added after is this
    catalog's own: its document fields, the shared accessibility definition,
    and the order the model is taught positional arguments in.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from a2ui.core.basic_catalog import BasicCatalog
        from a2ui.core.catalog import ComponentApi, FunctionApi

    basic = BasicCatalog(PROTOCOL_VERSION)
    date_time_input = _label_leads(basic.to_json()["components"]["DateTimeInput"])
    derived = basic.derive(
        catalog_id=CATALOG_ID,
        components=[
            *basic.components,
            ComponentApi("DateTimeInput", date_time_input, from_document=True),
            *(ComponentApi(name, schema, from_document=True) for name, schema in TRAVEL_COMPONENTS.items()),
        ],
        functions=[
            *basic.functions,
            *(
                FunctionApi(
                    name,
                    return_type=schema["returnType"],
                    schema=schema,
                    is_definition=True,
                    from_document=True,
                )
                for name, schema in TRAVEL_FUNCTIONS.items()
            ),
        ],
        instructions=CATALOG_INSTRUCTIONS,
    ).to_json()

    catalog: dict[str, Any] = {
        "$schema": derived["$schema"],
        "$id": CATALOG_ID,
        "catalogId": CATALOG_ID,
        # Which protocol this catalog is written against, and therefore which
        # protocol the server speaks: `brain/catalog.py` reads it from here
        # rather than carrying a second copy.
        "protocolVersion": PROTOCOL_VERSION,
        "title": "A2UI Travel Catalog",
        "description": CATALOG_DESCRIPTION,
        "instructions": CATALOG_INSTRUCTIONS,
        # Every component, ours and the basic catalog's alike. This decides the
        # positional argument order the model is taught, and leaving it to
        # `allOf` order as written made `weight` argument one.
        "components": {
            name: _own_properties_lead(schema) for name, schema in derived["components"].items()
        },
        "functions": derived["functions"],
        "$defs": _defs_for_1_0(derived["$defs"]),
    }

    # Last, so it catches the basic components, the basic functions and the
    # definitions alike. Idempotent on what already points at `COMMON`.
    return _at_declared_version(catalog)


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
