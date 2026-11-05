#!/usr/bin/env python3
"""Builds what the Catalog view shows: every component's signature and a working example.

The Catalog view used to do this in the browser with `packages/express` — a
TypeScript port of the A2UI Express compiler — so a page that only *displays*
the vocabulary shipped a compiler, a schema crawler and an example generator,
and every one of them had to agree with the SDK the server actually compiles
with. Twenty-one parity goldens existed to check that they did.

It is build-time work, so it uses the reference: the A2UI SDK's own
`CatalogSchemaHelper` for the signatures (the crawl the skill generator and the
parser use, so the order shown is the order the model is taught) and the SDK's
`ExpressParser` for the examples. The browser receives JSON and renders it with
`@a2ui/web_core`, which is the whole of what a renderer should have to do.

    python3 scripts/build_catalog_reference.py            # write
    python3 scripts/build_catalog_reference.py --check    # fail if stale
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import warnings
from typing import Any

warnings.filterwarnings("ignore")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "apps" / "web" / "src" / "generated" / "catalog-reference.json"
sys.path.insert(0, str(ROOT / "apps" / "server" / "src"))

#: Hand-written where a derived example would not show the component off: a
#: list needs rows, a map needs real coordinates, and `CheckBox("Madrid", 3)`
#: compiles, draws and teaches nothing.
SPECIAL: dict[str, str] = {
    "List": '$/items/0/label = "Passport"\n$/items/1/label = "Adapter"\nrow = Text($label)\n'
    "root = List(_template($/items, row))",
    "Column": 'a = Text("#### Outbound")\nb = Text("JFK → MAD · Sun 12 Apr")\n'
    'root = Column([a, b], align="stretch")',
    "Row": 'a = Text("Total")\nb = Text("$1,236")\nroot = Row([a, b], justify="spaceBetween")',
    "Card": 'inner = Text("Anything can go in a card.")\nroot = Card(inner)',
    "Tabs": 'one = Text("Prado at opening, then lunch at Sobrino.")\n'
    'two = Text("Retiro in the morning, Malasaña after dark.")\n'
    'root = Tabs([{title: "Day 1", child: one}, {title: "Day 2", child: two}])',
    "ItineraryDay": 'a1 = ActivityItem("Prado Museum", "10:00", category="sight", duration="2h")\n'
    'a2 = ActivityItem("Lunch at Sobrino", "13:30", category="food", duration="1h 30m")\n'
    'root = ItineraryDay("Day 2 — Old Madrid", [a1, a2], date="Mon 13 Apr", '
    'summary="Art, then a long lunch")',
    "PriceSummary": 'root = PriceSummary([{label: "Flights", amount: "$824"}, '
    '{label: "Hotel · 6 nights", amount: "$1,746"}, {label: "Estimated meals", amount: "$540"}], '
    'total="$3,110", caption="2 travellers")',
    "ExpenseSplit": 'root = ExpenseSplit("Dinner at Sobrino", "€96", [{name: "You"}, {name: "Sam"}])',
    "GoogleMap": "root = GoogleMap(center={lat: 40.4168, lng: -3.7038}, zoom=12, markers="
    '[{lat: 40.4260, lng: -3.7040, label: "Malasaña"}, {lat: 40.4110, lng: -3.7100, '
    'label: "La Latina"}, {lat: 40.4153, lng: -3.6844, label: "Retiro Park"}])',
    "MapPreview": 'root = MapPreview([{label: "Madrid"}, {label: "Toledo"}], caption="Day trip, 70km south")',
    "WeatherStrip": 'root = WeatherStrip([{day: "Mon", high: "21°", low: "11°", condition: "sun"}, '
    '{day: "Tue", high: "19°", low: "10°", condition: "cloud"}, {day: "Wed", high: "17°", low: "9°", '
    'condition: "rain"}], place="Madrid", caption="Pack a light jacket for Wednesday")',
    "TripCalendar": 'root = TripCalendar("2027-04-12", "2027-04-18", marks=[{date: "2027-04-12", '
    'icon: "plane", label: "Fly out"}, {date: "2027-04-14", icon: "🎨", label: "Prado"}, '
    '{date: "2027-04-18", icon: "plane", label: "Fly home"}], title="Madrid", caption="6 nights")',
    "ChoicePicker": 'root = ChoicePicker("Cabin", "mutuallyExclusive", [{label: "Economy", value: "economy"}, '
    '{label: "Premium", value: "premium"}], $/cabin)',
    "CheckBox": 'root = CheckBox("I need somewhere to stay in Chicago", $/stops/1/needsStay)',
    "ActivityItem": 'root = ActivityItem("Prado Museum", "10:00", category="sight", '
    'location="Paseo del Prado 23", duration="2h", note="Book the timed entry")',
    "TextField": 'root = TextField("Flying from", $/trip/origin, placeholder="City or airport")',
    "Slider": '$/trip/budget = 2400\nroot = Slider("Budget, all in", 500, 6000, $/trip/budget)',
    "Button": 'face = Text("Search flights")\nroot = Button(face, action=Event("search_flights"), variant="primary")',
    "DateTimeInput": '$/trip/startDate = "2027-04-12"\n'
    'root = DateTimeInput("Departure", $/trip/startDate, enableDate=true)',
    "TravelerCounter": '$/trip/travelers = 2\nroot = TravelerCounter("Travelers", $/trip/travelers, min=1, max=9, '
    'caption="Adults on this leg")',
    "DateRangePicker": '$/trip/startDate = "2027-04-12"\n$/trip/endDate = "2027-04-19"\n'
    'root = DateRangePicker("Trip dates", $/trip/startDate, $/trip/endDate, '
    'nightsLabel=formatString("${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})} nights"))',
    "StatTile": 'root = StatTile("Nights in Madrid", "7", caption="12–19 April", tone="accent")',
    "ProgressMeter": 'root = ProgressMeter("Spent of budget", 1840, 3000, caption="$1,160 left")',
    "Text": 'root = Text("### Madrid · 2 travellers · 12–19 April")',
    "HotelCard": 'root = HotelCard("Hotel Único Madrid", "$291 / night", Event("select_hotel", {id: "unico"}), '
    'neighborhood="Salamanca", rating="9.1 · Superb", amenities=["Breakfast", "Rooftop", '
    '"Free cancellation"], badge="Best located")',
    "FlightOption": 'root = FlightOption("Iberia", "18:40", "08:15 +1", "JFK", "MAD", "$412", '
    'Event("select_flight", {id: "IB6252"}), duration="7h 35m", stops="Nonstop", '
    'flightNumber="IB6252", cabin="economy", badge="Cheapest")',
}

#: Plausible values by property name, for the components with no hand-written example.
FLAVOUR: list[tuple[str, Any]] = [
    (r"^(airline|carrier)$", "Iberia"),
    (r"^flightNumber$", "IB6250"),
    (r"^(origin|from)$", "JFK"),
    (r"^(destination|to)$", "MAD"),
    (r"^(value|current)$", 3),
    (r"^max$", 10),
    (r"^min$", 1),
    (r"(price|fare|amount|total|budget|nightly)$", "$412"),
    (r"^(caption|summary|note|description|subtitle)$", "Lands early enough for dinner"),
    (r"^(label|title|text|heading|name|place|city)$", "Madrid"),
    (r"^(url|href|src|image)$", "https://images.unsplash.com/photo-1539037116277-4db20889f2d4?w=640"),
]

BASIC = {
    "Text", "Image", "Icon", "Video", "AudioPlayer", "Row", "Column", "List", "Card",
    "Tabs", "Modal", "Divider", "Button", "TextField", "CheckBox", "ChoicePicker",
    "Slider", "DateTimeInput",
}  # fmt: skip


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _value_for(prop: str, schema: dict[str, Any] | None, enum: list[str] | None) -> str:
    if enum:
        return _quote(enum[0])
    for pattern, value in FLAVOUR:
        if re.search(pattern, prop, re.IGNORECASE):
            return _quote(value) if isinstance(value, str) else json.dumps(value)
    kind = (schema or {}).get("type")
    if kind in ("number", "integer"):
        return "1"
    if kind == "boolean":
        return "true"
    if kind == "array":
        return "[]"
    return _quote(prop)


def example(helper: Any, name: str) -> str:
    """Express that draws one component: required properties, plus any with an enum."""
    if name in SPECIAL:
        return SPECIAL[name]
    required = set(helper.get_component_required(name))
    parts: list[str] = []
    lines: list[str] = []
    named = False  # once one is skipped, everything after must be named
    for prop in helper.get_component_properties(name):
        if prop in ("component", "id"):
            continue
        schema = helper.get_property_schema(name, prop)
        enum = helper.get_property_enum(name, prop)
        if prop not in required and not enum:
            named = True
            continue
        kind = helper.get_property_type(name, prop)

        def emit(literal: str) -> None:
            nonlocal named
            positional = prop in required and not named
            if not positional:
                named = True
            parts.append(literal if positional else f"{prop}={literal}")

        if kind in ("Child", "ChildList", "ComponentId"):
            child = f"{name[0].lower()}{name[1:]}Child"
            lines.append(f'{child} = Text("Inside {name}")')
            emit(f"[{child}]" if kind == "ChildList" else child)
        elif prop == "action":
            emit(f'Event("example", {{component: {_quote(name)}}})')
        else:
            emit(_value_for(prop, schema, enum))
    lines.append(f"root = {name}({', '.join(parts)})")
    return "\n".join(lines)


def _props(helper: Any, name: str, *, function: bool = False) -> list[dict[str, Any]]:
    names = helper.get_function_properties(name) if function else helper.get_component_properties(name)
    required = set(helper.get_function_required(name) if function else helper.get_component_required(name))
    out = []
    for prop in names:
        if prop in ("component", "id", "call", "returnType"):
            continue
        schema = (
            helper.get_function_property_schema(name, prop)
            if function
            else helper.get_property_schema(name, prop)
        ) or {}
        ref = json.dumps(schema)
        entry: dict[str, Any] = {
            "name": prop,
            "required": prop in required,
            "static": not re.search(r"DataBinding|Dynamic|ChildList|ComponentId", ref),
        }
        enum = None if function else helper.get_property_enum(name, prop)
        if enum:
            entry["enum"] = list(enum)
        if isinstance(schema.get("description"), str):
            entry["description"] = schema["description"]
        out.append(entry)
    return out


def build() -> dict[str, Any]:
    from a2ui.inference_formats._shared.schema_helper import CatalogSchemaHelper

    from a2ui.utils.renderer_state import validate_payload

    from travel_a2ui.brain.catalog import CATALOG, CATALOG_ID, CATALOG_VERSION, parser_for
    from travel_a2ui.brain.express import as_wire

    helper = CatalogSchemaHelper(CATALOG)
    components = []
    for name in sorted(helper.components):
        props = _props(helper, name)
        source = example(helper, name)
        entry: dict[str, Any] = {
            "name": name,
            "travel": name not in BASIC,
            "args": ", ".join(f"{p['name']}{'' if p['required'] else '?'}" for p in props),
            "props": props,
            "express": source,
        }
        description = helper.get_component_description(name)
        if description:
            entry["description"] = description
        try:
            messages = as_wire(parser_for(f"preview_{name}").compile(source, is_final=True))
            # And validated, as a renderer validates it. The compiler let a
            # `WeatherStrip` day carry numbers where the catalog says strings;
            # `@a2ui/web_core` refused the surface and the page drew nothing.
            validate_payload([CATALOG], messages)
            entry["messages"] = messages
        except Exception as error:  # noqa: BLE001 - shown on the page, and fails --check
            entry["error"] = f"{type(error).__name__}: {error}"
        components.append(entry)

    functions = []
    for name in sorted(helper.functions):
        props = _props(helper, name, function=True)
        entry = {
            "name": name,
            "args": ", ".join(f"{p['name']}{'' if p['required'] else '?'}" for p in props),
            "props": props,
        }
        description = helper.get_function_description(name)
        if description:
            entry["description"] = description
        functions.append(entry)

    return {
        "catalogId": CATALOG_ID,
        "version": CATALOG_VERSION,
        "components": components,
        "functions": functions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the file on disk is stale")
    args = parser.parse_args()

    reference = build()
    broken = [c["name"] for c in reference["components"] if "error" in c]
    text = json.dumps(reference, ensure_ascii=False, indent=1) + "\n"
    if broken:
        for c in reference["components"]:
            if "error" in c:
                print(f"{c['name']}: {c['error']}", file=sys.stderr)
        return 1
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("The catalog reference is stale. Regenerate: python3 scripts/build_catalog_reference.py",
                  file=sys.stderr)
            return 1
        print(f"The catalog reference is current: {len(reference['components'])} components.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(reference['components'])} components, "
          f"{len(reference['functions'])} functions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
