"""The data the host publishes for surfaces to bind.

The model composes every surface. The host's part is data: it owns a few
top-level keys of a surface's data model, keeps them current, and sends them as
ordinary `updateDataModel` messages to the surfaces that bind them. It never
rewrites a message the model wrote.

The roots, and what each holds:

    /trip        the record: every field the traveller has settled, as stored
    /plan        the decisions as rows a panel can list, labels resolved
    /panel       the trip hop by hop, as `Trip()` binds it
    /days        the day plan, as `Itinerary()` binds it
    /money       committed so far, the budget and what is left, as numbers
    /places      the airports this deployment flies, for `AirportPicker`
    /flights, /hotels, /highlights
                 the rows the last lookup returned, for this turn's surface

A surface binds a root when one of its components reads a path under it: an
absolute `@path`, a `List` template over it, or `${/root/...}` inside a
`formatString`. The first time a surface binds a root it receives the root's
current value; after that, it receives the root again whenever the value
changes. `brain/ui.py` does the sending.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from . import trip as model

#: Roots kept for the whole conversation: any surface may bind them.
SESSION_ROOTS = ("trip", "plan", "panel", "booked", "days", "money", "places")

#: Roots a lookup fills, for the surface the turn is drawing.
LOOKUPS: dict[str, tuple[str, str]] = {
    "search_flights": ("flights", "flights"),
    "search_hotels": ("hotels", "hotels"),
    "get_destination": ("highlights", "highlights"),
}

#: Where a lookup's rows are also filed by hop, so a turn that looks up fares
#: for several hops draws a list per hop rather than one list overwritten by
#: each search in turn: `/fares/3` is hop three's.
BY_HOP: dict[str, str] = {"flights": "fares", "hotels": "rooms"}

#: Roots that belong to the surface a turn draws, not the conversation.
LOOKUP_ROOTS = frozenset((*(root for root, _ in LOOKUPS.values()), *BY_HOP.values()))

ROOTS = frozenset((*SESSION_ROOTS, *LOOKUP_ROOTS))

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_INTERPOLATED = re.compile(r"\$\{\s*/([A-Za-z_][\w-]*)")


# --------------------------------------------------------------------------
# What each root holds
# --------------------------------------------------------------------------


def currency_of(trip: dict[str, Any]) -> str:
    named = trip.get("currency")
    return named if isinstance(named, str) and named else "USD"


def _money_text(amount: Any, currency: str) -> str:
    if not isinstance(amount, (int, float)):
        return ""
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(currency)
    figure = f"{amount:,.0f}"
    return f"{symbol}{figure}" if symbol else f"{figure} {currency}"


def _day_text(value: Any) -> str:
    try:
        day = dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return ""
    return f"{day.day} {_MONTHS[day.month - 1]}"


def trip_values(trip: dict[str, Any]) -> dict[str, Any]:
    """The record, field by field: what a control bound to `/trip/...` shows.

    A hop that has no party of its own travels with the one before it, and the
    record says so by leaving `travelers` off the leg. A counter bound to
    `/trip/legs/3/travelers` has to show that party, not an empty count, so
    each leg is sent with the party it actually has.
    """
    out = {key: trip[key] for key in model.TRIP_KEYS if trip.get(key) is not None and trip.get(key) != ""}
    legs = out.get("legs")
    if isinstance(legs, list):
        party = {hop.get("hop"): hop.get("travelers") for hop in model.journey(model.normalize(trip))}
        out["legs"] = [
            {**leg, "travelers": party[index + 1]}
            if isinstance(leg, dict) and leg.get("travelers") is None and party.get(index + 1) is not None
            else leg
            for index, leg in enumerate(legs)
        ]
    return out


def money_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """Committed so far, the budget and what is left, as numbers.

    Only what has been chosen counts: a fare times the party on its hop, a stay
    times the nights at its stop. Nothing is projected.
    """
    total, counted = 0.0, False
    for hop in model.journey(model.normalize(trip)):
        party = hop.get("travelers")
        party = int(party) if isinstance(party, (int, float)) and party > 0 else 1
        fare = hop.get("flightPrice")
        if isinstance(fare, (int, float)):
            total += float(fare) * party
            counted = True
        nightly, nights = hop.get("nightlyPrice"), hop.get("nights")
        if isinstance(nightly, (int, float)) and isinstance(nights, (int, float)) and nights > 0:
            total += float(nightly) * int(nights)
            counted = True

    out: dict[str, Any] = {}
    if counted:
        out["total"] = round(total, 2)
    budget = trip.get("budget")
    if isinstance(budget, (int, float)):
        out["budget"] = round(float(budget), 2)
        if counted:
            out["remaining"] = round(float(budget) - total, 2)
            out["over"] = out["remaining"] < 0
    if out:
        out["currency"] = currency_of(trip)
    return out


def plan_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """Every decision made so far, as rows with their labels resolved."""
    hops = model.journey(trip)
    on_a_hop = {"travelers", "selectedFlight", "selectedHotel"}
    decisions = []
    for item in model.FIELDS:
        key = item["key"]
        value = trip.get(key)
        if value in (None, "") or item.get("kind") in model.LIST_KINDS:
            continue
        if key in on_a_hop and hops:
            continue
        decisions.append({"key": key, "label": item["label"], "value": _value_text(value)})
    route = [
        {
            "place": hop["to"],
            "from": hop.get("from") or "",
            "nights": hop.get("nights") or 0,
            "wants": hop["wants"],
            "decisions": [
                {"key": row["key"], "label": row["label"], "value": _value_text(row["value"])}
                for row in hop["decisions"]
            ],
        }
        for hop in hops
    ]
    open_hops = sum(1 for hop in hops if hop["wants"])
    return {
        "decisions": decisions,
        "route": route,
        "complete": bool(route) and open_hops == 0,
    }


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item) or "—"
    return str(value)


def panel_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """The trip hop by hop, as `Trip()` draws it.

    Each hop carries `flights` and `stays` as lists of none or one, so a
    template over them draws a card only once that decision is settled. Every
    field a card shows is filled, with an empty string for what nobody has
    recorded, so nothing on the panel waits for data that is not coming.
    """
    currency = currency_of(trip)
    legs = trip.get("legs") if isinstance(trip.get("legs"), list) else []
    hops = []
    for hop in model.journey(trip):
        index = hop.get("hop") or 0
        own = trip if index == 0 else (legs[index - 1] if len(legs) >= index else {})
        own = own if isinstance(own, dict) else {}

        when = []
        if hop.get("startDate"):
            when.append(_day_text(hop["startDate"]))
            if hop.get("endDate"):
                when[-1] += f" – {_day_text(hop['endDate'])}"
        if hop.get("travelers") is not None:
            when.append(f"{hop['travelers']} travelling")

        # Counted from one, as every press reads `hop`: hop two is `legs/0`.
        number = index + 1
        flights = []
        if hop.get("selectedFlight"):
            flights.append(
                {
                    "hop": number,
                    "route": f"{hop.get('from') or ''} → {hop.get('to') or ''}".strip(" →"),
                    "airline": str(own.get("airline") or ""),
                    "flightNumber": str(own.get("flightNumber") or hop["selectedFlight"]),
                    "departTime": str(own.get("departTime") or ""),
                    "arriveTime": str(own.get("arriveTime") or ""),
                    "origin": str(hop.get("from") or ""),
                    "destination": str(hop.get("to") or ""),
                    "price": _money_text(hop.get("flightPrice"), currency),
                }
            )
        stays = []
        if hop.get("selectedHotel"):
            nightly = _money_text(hop.get("nightlyPrice"), currency)
            stays.append(
                {
                    "hop": number,
                    "name": str(own.get("hotelName") or hop["selectedHotel"]),
                    "price": f"{nightly} / night" if nightly else "",
                }
            )
        hops.append(
            {
                "hop": number,
                "title": f"{hop.get('from') or ''} → {hop.get('to') or ''}".strip(" →"),
                "when": " · ".join(part for part in when if part),
                "flights": flights,
                "stays": stays,
            }
        )

    money = money_rows(trip)
    figures = []
    if money.get("total") is not None:
        figures.append({"label": "Committed so far", "value": _money_text(money["total"], currency)})
    if money.get("budget") is not None:
        figures.append({"label": "Budget", "value": _money_text(money["budget"], currency)})
    if money.get("remaining") is not None:
        figures.append(
            {
                "label": "Over budget by" if money.get("over") else "Left to spend",
                "value": _money_text(abs(money["remaining"]), currency),
            }
        )
    return {
        "hops": hops,
        "figures": figures,
        # A line for a panel with nothing on it yet, as a list of none or one so
        # a template shows it only while it is true.
        "notice": [] if hops else [{"text": "Nothing settled yet."}],
    }


def day_rows(trip: dict[str, Any]) -> list[dict[str, Any]]:
    """The day plan, as `Itinerary()` draws it.

    Each day and activity carries its own position (`day`, `index`), so a
    template can put them in the context of a press without counting.
    """
    days = trip.get("days") if isinstance(trip.get("days"), list) else []
    out = []
    for position, day in enumerate(days):
        if not isinstance(day, dict):
            continue
        activities = [
            {
                "day": position,
                "index": index,
                "title": str(item.get("title") or ""),
                "time": str(item.get("time") or ""),
                "category": str(item.get("category") or "sight"),
                "location": str(item.get("location") or ""),
                "duration": str(item.get("duration") or ""),
                "note": str(item.get("note") or ""),
                "done": bool(item.get("done")),
            }
            for index, item in enumerate(day.get("activities") or [])
            if isinstance(item, dict)
        ]
        out.append(
            {
                "day": position,
                "title": str(day.get("title") or f"Day {position + 1}"),
                "date": str(day.get("date") or ""),
                "summary": str(day.get("summary") or ""),
                "activities": activities,
            }
        )
    return out


def places_rows(origins: Iterable[dict[str, Any]], destinations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The places this deployment flies, as `AirportPicker` options.

    What an option stores follows the trip field it fills: `origin` is an
    airport code, so an origin stores CPH; `destination` is a city or an
    airport, and the city reads better everywhere a person sees it.
    """

    def detail(value: Any) -> str:
        said = str(value or "").strip()
        if said.islower():  # a slug such as "north-america"
            said = " ".join(word.capitalize() for word in said.split("-") if word)
        return said

    origins_out, destinations_out = [], []
    for entry in origins:
        if isinstance(entry, dict) and entry.get("code"):
            code = str(entry["code"]).strip()
            origins_out.append(
                {
                    "value": code,
                    "label": str(entry.get("city") or code),
                    "code": code,
                    "detail": detail(entry.get("region")),
                }
            )
    for entry in destinations:
        if isinstance(entry, dict) and (entry.get("city") or entry.get("airport")):
            city = str(entry.get("city") or "").strip()
            code = str(entry.get("airport") or "").strip()
            destinations_out.append(
                {"value": city or code, "label": city or code, "code": code, "detail": detail(entry.get("country"))}
            )
    return {"origins": origins_out, "destinations": destinations_out}


def currency_for(destinations: Iterable[dict[str, Any]], trip: dict[str, Any]) -> str:
    """The currency the trip's destination quotes in; dollars until there is one."""
    where = str((trip or {}).get("destination") or "").strip().casefold()
    if not where:
        return "USD"
    for entry in destinations:
        if not isinstance(entry, dict):
            continue
        names = {str(entry.get("city") or "").casefold(), str(entry.get("airport") or "").casefold()}
        if where in names and entry.get("currency"):
            return str(entry["currency"])
    return "USD"


def booked_rows(panel: dict[str, Any]) -> list[dict[str, Any]]:
    """Every chosen fare on the route, in hop order, as `Booked()` draws them."""
    return [fare for hop in panel.get("hops", []) for fare in hop.get("flights", [])]


def hop_of_search(args: Any) -> int | None:
    """The hop a search said it was for (`hop`, counted from one), if it said."""
    named = args.get("hop") if isinstance(args, dict) else None
    if isinstance(named, int) and not isinstance(named, bool) and named >= 1:
        return named
    return None


def session_values(trip: dict[str, Any], places: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every conversation-wide root, as it stands for this trip."""
    panel = panel_rows(trip)
    values = {
        "trip": trip_values(trip),
        "plan": plan_rows(trip),
        "panel": panel,
        "booked": booked_rows(panel),
        "days": day_rows(trip),
        "money": money_rows(trip),
    }
    if places is not None:
        values["places"] = places
    return values


def lookup_rows(tool: str, result: Any) -> tuple[str, list[Any]] | None:
    """The root a lookup files its rows under, and the rows."""
    landing = LOOKUPS.get(tool)
    if landing is None or not isinstance(result, dict):
        return None
    root, key = landing
    rows = result.get(key)
    return (root, rows) if isinstance(rows, list) else None


def file_rows(
    lookups: dict[str, Any], tool: str, args: Any, result: Any, trip: dict[str, Any]
) -> tuple[str, int | None] | None:
    """Files a lookup's rows in this turn's `lookups`: at its root, and by hop.

    Returns the root and the hop (counted from one) they were filed under, or
    None when the lookup files nothing.
    """
    landed = lookup_rows(tool, result)
    if landed is None:
        return None
    root, rows = landed
    lookups[root] = rows
    hop = hop_of_search(args) if root in BY_HOP else None
    if hop is not None:
        lookups[BY_HOP[root]] = {**(lookups.get(BY_HOP[root]) or {}), str(hop): rows}
    return root, hop


def turn_values(lookups: dict[str, Any], trip: dict[str, Any]) -> dict[str, Any]:
    """This turn's lookup roots, as the surface it draws binds them.

    Every hop of the route gets an entry under `/fares` and `/rooms`: its own
    rows when a search was for it, else the latest rows, so a list drawn for a
    hop is never left empty because its search did not say which hop it was.
    """
    out = dict(lookups)
    hops = len(model.journey(model.normalize(trip)))
    for flat, by_hop in BY_HOP.items():
        if flat not in lookups:
            continue
        own = lookups.get(by_hop) or {}
        # Every hop a list could be drawn for: the route's, any a search named,
        # and a return the route has not recorded as a hop yet.
        last = max([hops + 1, *(int(n) for n in own if str(n).isdigit())])
        out[by_hop] = {str(n): own.get(str(n), lookups[flat]) for n in range(1, last + 1)}
    return out


#: The macro that draws each lookup's rows.
DRAWN_BY = {"flights": "Flights()", "hotels": "Stays()", "highlights": "Highlights()"}


def without_the_rows(tool: str, result: Any, surface_id: str, hop: int | None = None, shown: bool = False) -> Any:
    """A lookup's result for the model, with the filed rows summarised.

    The rows are on the surface already, bound by path, so the model is told
    where they are and how many, rather than handed a list to re-type.
    """
    landed = lookup_rows(tool, result)
    if landed is None:
        return result
    root, rows = landed
    summary = dict(result)
    where = f"/{root}"
    if hop is not None and root in BY_HOP:
        where += f", and as hop {hop}'s own at /{BY_HOP[root]}/{hop}"
    if shown:
        said = "The list you drew for them on this turn has filled in: do not draw it again."
    else:
        said = f"Nothing on screen shows them yet: draw them with {DRAWN_BY.get(root, 'the macro')}."
    summary[LOOKUPS[tool][1]] = (
        f"{len(rows)} rows, in the data model of surface {surface_id} at {where}. {said} Never write them out."
    )
    summary["sample"] = rows[:1]
    return summary


# --------------------------------------------------------------------------
# Which roots a surface binds
# --------------------------------------------------------------------------


def roots_bound(components: Iterable[dict[str, Any]]) -> set[str]:
    """The host-owned roots these components read."""
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("@path", "path") and isinstance(inner, str) and inner.startswith("/"):
                    root = inner[1:].split("/", 1)[0]
                    if root in ROOTS:
                        found.add(root)
                else:
                    visit(inner)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and "${" in value:
            found.update(root for root in _INTERPOLATED.findall(value) if root in ROOTS)

    for component in components:
        visit(component)
    return found


_TRIP_FIELD = re.compile(r"\$\{\s*/trip(?:/([A-Za-z_][\w-]*))?")


def trip_fields_bound(components: Iterable[dict[str, Any]]) -> set[str]:
    """The record fields these components read, by name; `"*"` for the whole record."""
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("@path", "path") and isinstance(inner, str) and inner.startswith("/trip"):
                    parts = inner.strip("/").split("/")
                    found.add(parts[1] if len(parts) > 1 else "*")
                else:
                    visit(inner)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and "${" in value:
            found.update(field or "*" for field in _TRIP_FIELD.findall(value))

    for component in components:
        visit(component)
    return found


def components_of(message: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    for kind in ("createSurface", "updateComponents"):
        body = message.get(kind)
        if isinstance(body, dict):
            return body.get("surfaceId"), list(body.get("components") or [])
    return None, []
