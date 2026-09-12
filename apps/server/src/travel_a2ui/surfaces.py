"""The six surface builders: gen-UI carried into somebody else's agent.

These are what a *different* agent gets when it installs the plugin. Claude
calls `show_flight_options` and receives A2UI rather than prose, so the same
cards the web app draws appear inside a product that has never heard of this
one. They are also what a voice session draws with, because reading four fares
aloud is a memory test.

Each returns three things:

  `express`    the interface, as A2UI Express for the caller to compile
  `surface_id` where it goes — inline surfaces are keyed by what they show;
               `sidebar` and `home` are singular, so writing to them replaces
               the panel, which is what makes them panels rather than a feed
  `summary`    one line for the model to *say*

The summary is easy to mistake for an afterthought. It is the opposite: handing
the model the whole surface would put a flight list in its context and invite it
to recite the list, which is the single thing this mode exists to avoid. It gets
"four fares up, the Iberia one is cheapest" and the screen holds the rest.

Nothing here invents. A missing date is a refusal that says what to ask for; a
destination the provider has never heard of is a refusal that offers
alternatives. Both are raised as exceptions carrying a sentence the model can
act on, because "I don't know" has to be as easy to return as an answer.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass
from typing import Any

from . import trip as model
from .providers.types import NotFound, TravelProvider


@dataclass(frozen=True)
class Surface:
    express: str
    surface_id: str
    summary: str


class NeedsInput(Exception):
    """The caller has not asked the traveller enough to answer honestly."""

    def __init__(self, missing: list[str], what: str) -> None:
        bound = ", ".join(f"${model.binding_for(key)}" for key in missing)
        super().__init__(
            f"Cannot {what} without {model.ask_for(missing)}. Ask the traveler — draw the "
            f"controls for all of it in one surface with render_a2ui_express, bound to "
            f"{bound} with a single commit button — or pass the values as arguments. For a "
            "deliberately rough figure, call again with flexible: true and say on screen "
            "that it is indicative."
        )


class NoData(Exception):
    """The provider has nothing, said in a way the model can act on."""

    def __init__(self, outcome: NotFound) -> None:
        offer = (
            f"Offer these as choices: {', '.join(outcome.recover)}. " if outcome.recover else ""
        )
        super().__init__(
            f"{outcome.message} {offer}"
            "Do not substitute a different city, invent an airport code, or draw an empty list."
        )


def _q(value: Any) -> str:
    """A value as an Express literal.

    `json.dumps` rather than manual quoting: a hotel called `O'Neill's` or a
    note containing a quotation mark is ordinary data, and getting the escaping
    wrong produces Express that does not compile — reported to the model as a
    syntax error it did not make.
    """
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    return fallback


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _trip_of(args: dict[str, Any]) -> dict[str, Any]:
    return model.normalize(
        {
            "destination": args.get("destination"),
            "origin": args.get("origin"),
            "startDate": args.get("date") or args.get("startDate"),
            "endDate": args.get("endDate"),
            "travelers": args.get("travelers"),
            "cabin": args.get("cabin"),
            "maxFare": args.get("maxPrice"),
            "maxNightly": args.get("maxNightly"),
            "neighborhood": args.get("neighborhood"),
            "budget": args.get("budget"),
            "spent": args.get("spent"),
        }
    )


def _flow_of(args: dict[str, Any]) -> str:
    value = _str(args.get("surface"))
    return value if value in ("sidebar", "home") else "inline"


def _surface_id_for(flow: str, inline_id: str) -> str:
    """The surface id a flow writes to.

    `sidebar` and `home` are *singular*: writing to them again replaces the
    panel, which is what makes them panels rather than a feed. Inline surfaces
    are keyed by what they show, so two different questions get two cards.
    """
    return inline_id if flow == "inline" else f"mcp-{flow}"


def _limit_for(flow: str) -> int:
    """How many options a flow has room for.

    Not a style preference: a sidebar column is narrow and a home screen is a
    summary, so the same six flights that read well inline read as a wall in
    either. The model chose the flow; this honours it.
    """
    return 2 if flow == "home" else 3 if flow == "sidebar" else 4


def _money(value: int) -> str:
    """`1240` → `$1,240`, matching `toLocaleString('en-US')`."""
    return f"${value:,}"


async def build_surface(
    name: str,
    args: dict[str, Any],
    provider: TravelProvider,
    today: str | None = None,
) -> Surface:
    """One surface, by tool name.

    `today` is optional and defaults to the clock, because every caller means
    now. It is a parameter at all because two of these read the clock — the
    countdown on the dashboard and an itinerary with no start date — so what
    they produce otherwise depends on the day they run.
    """
    if name == "show_flight_options":
        return await _flights(args, provider)
    if name == "show_hotel_options":
        return await _hotels(args, provider)
    if name == "show_trip_controls":
        return await _controls(args, provider)
    if name == "show_itinerary":
        return await _itinerary(args, provider, today)
    if name == "show_trip_dashboard":
        return await _dashboard(args, provider, today)
    if name == "show_price_summary":
        return await _price(args, provider)
    if name == "render_a2ui_express":
        return Surface(
            express=_str(args.get("source")),
            summary="A custom interface.",
            surface_id=_str(args.get("surfaceId")) or "mcp",
        )
    raise ValueError(f"Unknown surface tool: {name}")


async def _place(provider: TravelProvider, query: str) -> str:
    found = await provider.resolve_destination(query)
    return found["city"] if found else query


async def _flights(args: dict[str, Any], provider: TravelProvider) -> Surface:
    flow = _flow_of(args)
    surface_id = _surface_id_for(flow, "mcp-flights")
    destination = _str(args.get("destination"))

    flexible = args.get("flexible") is True
    trip = _trip_of(args)
    missing = model.missing_for(trip, "priceFlights")
    if missing and not flexible:
        raise NeedsInput(missing, "price flights")

    outcome = await provider.search_flights(
        {
            "destination": destination,
            "origin": trip.get("origin"),
            "date": trip.get("startDate"),
            "cabin": trip.get("cabin"),
            "maxPrice": trip.get("maxFare"),
            "nonstopOnly": args.get("nonstopOnly") is True,
            "indicative": flexible or bool(missing),
        }
    )
    if not outcome.ok:
        raise NoData(outcome)

    flights = outcome.items[: _limit_for(flow)]
    place = await _place(provider, destination)

    # The heading names what these fares are for. A price with no route, date or
    # party size beside it is the thing that makes an answer untrustworthy.
    heading = model.basis_of({**trip, "destination": place}) or f"Flights to {place} · indicative"

    lines = [
        f"surface({_q(surface_id)})",
        f"head = Text({_q(heading)}, variant={_q('h4' if flow == 'home' else 'h3')})",
    ]
    for index, flight in enumerate(flights):
        badge = f", badge={_q(flight['badge'])}" if flight.get("badge") else ""
        lines.append(
            f"f{index} = FlightOption({_q(flight['airline'])}, {_q(flight['departTime'])}, "
            f"{_q(flight['arriveTime'])}, {_q(flight['origin'])}, {_q(flight['destination'])}, "
            f"{_q(flight['price'])}, "
            f'Event("select_flight", {{id: {_q(flight["id"])}, price: {_q(flight["price"])}}}), '
            f"duration={_q(flight['duration'])}, stops={_q(flight['stops'])}, "
            f"flightNumber={_q(flight['flightNumber'])}, cabin={_q(flight['cabin'])}{badge})"
        )

    # The footer says where the numbers came from. On a fixture deployment that
    # reads "Sample data"; on a live one it names the source. Neither is
    # optional: a fare with no provenance is what made this untrustworthy.
    caption = " · ".join(
        part
        for part in (
            outcome.note,
            f"Widened: {', '.join(outcome.relaxed)}." if outcome.relaxed else "",
            "Indicative dates — not priced for a specific trip." if missing else "",
            outcome.provenance.label,
        )
        if part
    )
    lines.append(f"foot = Text({_q(caption)}, variant=\"caption\")")
    body = ", ".join(f"f{index}" for index in range(len(flights)))
    lines.append(f"root = Column([head, {body}, foot])")

    indicative = " Indicative — no date was given." if missing else ""
    return Surface(
        express="\n".join(lines),
        surface_id=surface_id,
        summary=(
            f"{len(flights)} flight option(s), {heading}, cheapest {flights[0]['price']}. "
            f"{outcome.provenance.label}.{indicative}"
        ),
    )


async def _hotels(args: dict[str, Any], provider: TravelProvider) -> Surface:
    flow = _flow_of(args)
    surface_id = _surface_id_for(flow, "mcp-hotels")
    destination = _str(args.get("destination"))
    nights = _int(args.get("nights"), 5)

    outcome = await provider.search_hotels(
        {
            "destination": destination,
            "nights": nights,
            "maxNightly": _number(args.get("maxNightly")),
            "neighborhood": _str(args.get("neighborhood")) or None,
        }
    )
    if not outcome.ok:
        raise NoData(outcome)

    hotels = outcome.items[: _limit_for(flow)]
    place = await _place(provider, destination)

    lines = [
        f"surface({_q(surface_id)})",
        f"head = Text({_q(f'Stays in {place}')}, variant={_q('h4' if flow == 'home' else 'h3')})",
    ]
    for index, hotel in enumerate(hotels):
        amenities = ", ".join(_q(item) for item in hotel["amenities"])
        badge = f", badge={_q(hotel['badge'])}" if hotel.get("badge") else ""
        lines.append(
            f"h{index} = HotelCard({_q(hotel['name'])}, {_q(hotel['price'])}, "
            f'Event("select_hotel", {{id: {_q(hotel["id"])}, name: {_q(hotel["name"])}}}), '
            f"neighborhood={_q(hotel['neighborhood'])}, rating={_q(hotel['rating'])}, "
            f"amenities=[{amenities}]{badge})"
        )

    caption = " · ".join(
        part
        for part in (
            outcome.note,
            f"Widened: {', '.join(outcome.relaxed)}." if outcome.relaxed else "",
            outcome.provenance.label,
        )
        if part
    )
    lines.append(f"foot = Text({_q(caption)}, variant=\"caption\")")
    body = ", ".join(f"h{index}" for index in range(len(hotels)))
    lines.append(f"root = Column([head, {body}, foot])")

    return Surface(
        express="\n".join(lines),
        surface_id=surface_id,
        summary=(
            f"{len(hotels)} stay(s) in {place} from {hotels[0]['price']}. "
            f"{outcome.provenance.label}."
        ),
    )


async def _controls(args: dict[str, Any], provider: TravelProvider) -> Surface:
    """The sidebar flow: controls, not content.

    Everything is bound into the data model, so the host reads the traveller's
    choices out of the surface rather than parsing them from a sentence, and one
    commit action carries them all in its context.
    """
    destination = _str(args.get("destination"))
    place = await _place(provider, destination) if destination else destination
    travelers = _int(args.get("travelers"), 2)
    max_price = _int(args.get("maxPrice"), 700)
    start_date = _str(args.get("startDate"))
    end_date = _str(args.get("endDate"))

    nights = 0
    if start_date and end_date:
        start = _dt.date.fromisoformat(start_date)
        end = _dt.date.fromisoformat(end_date)
        nights = max(0, (end - start).days)

    def rfc(date: str) -> str:
        return f"{date}T00:00:00Z" if date else ""

    nights_label = f", nightsLabel={_q(f'{nights} nights')}" if nights > 0 else ""
    lines = [
        'surface("mcp-sidebar")',
        f"$/filters/start = {_q(rfc(start_date))}",
        f"$/filters/end = {_q(rfc(end_date))}",
        f"$/filters/travelers = {travelers}",
        f"$/filters/maxPrice = {max_price}",
        f"$/filters/stops = {_q('nonstop' if args.get('nonstopOnly') is True else 'any')}",
        f"title = Text({_q(f'Refine {place}' if place else 'Refine the trip')}, variant=\"h3\")",
        'dates = DateRangePicker("Travel dates", $/filters/start, $/filters/end, '
        f'action=Event("dates_changed"){nights_label})',
        'who = TravelerCounter("Travellers", $/filters/travelers, min=1, max=8)',
        'budget = Slider("Max fare", 150, 2000, $/filters/maxPrice)',
        'stops = ChoicePicker("Stops", "mutuallyExclusive", '
        '[{label: "Any", value: "any"}, {label: "Nonstop only", value: "nonstop"}], '
        "$/filters/stops)",
        'apply = Button(Text("Apply"), "primary", Event("apply_filters", '
        "{destination: $/filters/destination, start: $/filters/start, end: $/filters/end, "
        "travelers: $/filters/travelers, maxPrice: $/filters/maxPrice, stops: $/filters/stops}))",
        'root = Column([title, dates, who, budget, stops, apply], align="stretch")',
    ]
    if place:
        lines.insert(1, f"$/filters/destination = {_q(place)}")

    return Surface(
        express="\n".join(lines),
        surface_id="mcp-sidebar",
        summary=(
            f"Controls for {place}: dates, party size, fare cap and stops."
            if place
            else "Trip controls: dates, party size, fare cap and stops."
        ),
    )


#: Days to fall back on once the real highlights run out.
_FILLER = [
    {"name": "A slow morning", "category": "free", "note": "Coffee, a market, no plan"},
    {"name": "Wander {city}", "category": "outdoors", "note": "Pick a direction and walk"},
    {"name": "Dinner, late", "category": "food", "note": "Book somewhere near the hotel"},
]

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _utc_label(date: _dt.date) -> str:
    """`Mon, 12 Apr`, which is what `toUTCString().slice(0, 11)` produces.

    Emulated rather than formatted with `strftime`, because `%a, %d %b` is
    locale-dependent and would quietly render in whatever language the server
    happens to be configured for.
    """
    return f"{_WEEKDAYS[date.weekday()]}, {date.day:02d} {_MONTHS[date.month - 1]}"


async def _itinerary(
    args: dict[str, Any], provider: TravelProvider, today: str | None
) -> Surface:
    query = _str(args.get("destination"))
    destination = await provider.resolve_destination(query)
    if not destination:
        raise ValueError(f"No itinerary data for '{query}'.")

    flow = _flow_of(args)
    surface_id = _surface_id_for(flow, "mcp-itinerary")
    # The home flow is a summary, not a plan: one day, the next one.
    days = 1 if flow == "home" else min(max(_int(args.get("days"), 3), 1), 7)

    start_arg = _str(args.get("startDate"))
    if start_arg:
        start = _dt.date.fromisoformat(start_arg)
    elif today:
        start = _dt.date.fromisoformat(today)
    else:
        start = _dt.date.today()

    lines = [
        f"surface({_q(surface_id)})",
        f"head = Text({_q(destination['city'])}, variant={_q('h4' if flow == 'home' else 'h2')})",
    ]
    day_vars: list[str] = []

    # Each highlight is used once before any is reused. A three-day plan that
    # lists the same museum on days one and three reads as a bug, because it is.
    pool = list(destination["highlights"])
    filler = [
        {**item, "name": item["name"].format(city=destination["city"])} for item in _FILLER
    ]

    for day in range(days):
        date = start + _dt.timedelta(days=day)
        label = _utc_label(date)
        activity_vars: list[str] = []

        for slot in range(2):
            highlight = pool.pop(0) if pool else filler[(day * 2 + slot) % len(filler)]
            variable = f"a{day}_{slot}"
            activity_vars.append(variable)
            lines.append(
                f"{variable} = ActivityItem({_q(highlight['name'])}, "
                f"{_q('10:00' if slot == 0 else '16:00')}, "
                f"category={_q(highlight['category'])}, note={_q(highlight['note'])})"
            )

        day_var = f"day{day}"
        day_vars.append(day_var)
        summary = "Arrive and settle in" if day == 0 else "A full day out"
        lines.append(
            f"{day_var} = ItineraryDay({_q(f'Day {day + 1}')}, [{', '.join(activity_vars)}], "
            f"date={_q(label)}, summary={_q(summary)})"
        )

    lines.append(f"root = Column([head, {', '.join(day_vars)}])")

    return Surface(
        express="\n".join(lines),
        surface_id=surface_id,
        summary=f"A {days}-day plan for {destination['city']}: {destination['summary']}",
    )


async def _dashboard(
    args: dict[str, Any], provider: TravelProvider, today: str | None
) -> Surface:
    from .tools import _estimate

    query = _str(args.get("destination"))
    destination = await provider.resolve_destination(query)
    place = destination["city"] if destination else query
    nights = _int(args.get("nights"), 5)
    travelers = _int(args.get("travelers"), 2)
    budget = _int(args.get("budget"), 0)
    spent = _int(args.get("spent"), 0)

    start_date = _str(args.get("startDate"))
    days_out: int | None = None
    if start_date:
        now = _dt.date.fromisoformat(today) if today else _dt.date.today()
        days_out = max(0, (_dt.date.fromisoformat(start_date) - now).days)

    estimate = _estimate(query, travelers, nights, None, None)
    weather = await provider.get_weather(query, start_date or None, 5)
    if not weather.ok:
        raise NoData(weather)
    forecast = weather.items[0]
    effective_budget = budget or estimate["totalValue"]
    over = spent > effective_budget

    lines = [
        'surface("mcp-home")',
        f"head = Text({_q(f'{days_out} days to {place}' if days_out is not None else place)}, "
        'variant="h1")',
        f't1 = StatTile("Travellers", {_q(str(travelers))}, caption={_q(f"{nights} nights")}, '
        'tone="neutral")',
        f't2 = StatTile("Estimated", {_q(estimate["total"])}, caption="all in", tone="accent")',
        f't3 = StatTile("Spent", {_q(_money(spent))}, '
        f"caption={_q(f'of {_money(effective_budget)}')}, "
        f"tone={_q('critical' if over else 'positive')})",
        "tiles = Row([t1, t2, t3])",
        f'meter = ProgressMeter("Budget used", {spent}, {max(effective_budget, 1)}, '
        f"caption={_q(f'{_money(spent)} of {_money(effective_budget)}')}, "
        f"tone={_q('critical' if over else 'caution')})",
    ]

    days = ", ".join(
        f"{{day: {_q(day['day'])}, high: {_q(day['high'])}, low: {_q(day['low'])}, "
        f"condition: {_q(day['condition'])}}}"
        for day in forecast["days"]
    )
    lines.append(
        f"weather = WeatherStrip([{days}], place={_q(forecast['place'])}, "
        f"caption={_q(forecast['note'])})"
    )

    if destination:
        highlights = ", ".join(
            f"{{label: {_q(item['name'])}, kind: {_q(item['category'])}}}"
            for item in destination["highlights"][:4]
        )
        lines.append(
            f"map = MapPreview([{highlights}], caption={_q(destination['summary'])})"
        )
        lines.append("root = Column([head, tiles, meter, weather, map])")
    else:
        lines.append("root = Column([head, tiles, meter, weather])")

    return Surface(
        express="\n".join(lines),
        # The dashboard *is* the home flow, so it always writes the home surface.
        surface_id="mcp-home",
        summary=(
            f"{place}: {travelers} traveller(s), {nights} nights, "
            f"estimated {estimate['total']}."
        ),
    )


async def _price(args: dict[str, Any], provider: TravelProvider) -> Surface:
    from .tools import _estimate

    flow = _flow_of(args)
    surface_id = _surface_id_for(flow, "mcp-price")
    query = _str(args.get("destination"))
    estimate = _estimate(
        query,
        _int(args.get("travelers"), 2),
        _int(args.get("nights"), 5),
        _number(args.get("flightPrice")),
        _number(args.get("nightlyPrice")),
    )
    place = await _place(provider, query)

    rows = ", ".join(
        f"{{label: {_q(line['label'])}, amount: {_q(line['amount'])}"
        + (f", note: {_q(line['note'])}" if line.get("note") else "")
        + "}"
        for line in estimate["lines"]
    )

    return Surface(
        express="\n".join(
            [
                f"surface({_q(surface_id)})",
                f"head = Text({_q(f'What {place} costs')}, "
                f"variant={_q('h4' if flow == 'home' else 'h3')})",
                f"p = PriceSummary([{rows}], {_q(estimate['total'])}, "
                'totalLabel="Trip total", caption="Estimated, taxes included")',
                "root = Column([head, p])",
            ]
        ),
        surface_id=surface_id,
        summary=f"Estimated {estimate['total']} for {place}.",
    )
