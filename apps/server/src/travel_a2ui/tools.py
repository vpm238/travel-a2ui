"""The agent's tools.

A deliberate split runs through this file, and it is the whole architectural
idea of the project:

    **Tools return data. The skill turns data into UI.**

No tool here returns A2UI. `search_flights` returns flights. The model reads
them and writes Express, because deciding *how* to present five flights — which
to lead with, what to say about the stopover, whether this is a moment for a
price summary — is a judgement call, and judgement is what the model is for. A
tool returning pre-rendered cards moves that decision into this file, where it
would be frozen and wrong half the time.

The one exception is `save_trip`, which writes rather than reads, because the
traveller's choices have to outlive the turn that made them.

The contracts themselves are in `data/tools.json`, shared with the TypeScript
implementation while that still exists. They are prompt engineering as much as
schema, and a retyped description is a different agent.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Callable

from . import trip as model
from .providers.types import Found, NotFound, TravelProvider

_ROOT = pathlib.Path(__file__).resolve().parents[4]
TOOLS: list[dict[str, Any]] = json.loads(
    (_ROOT / "data" / "tools.json").read_text("utf-8")
)["tools"]

#: Fields a surface may not quietly change, even by pressing a button.
#:
#: `save_trip` validates; a button press used to not, so a picker sending
#: 20 Apr → 12 Apr priced four flights against negative nights.
REFUSABLE = ("startDate", "endDate", "travelers", "legs")


@dataclass
class ToolContext:
    """What a tool may read and write for the turn it is part of."""

    #: The trip so far, readable and writable across turns.
    trip: dict[str, Any]
    #: Where travel data comes from. On the context rather than imported,
    #: because it is a property of the deployment — fixtures by default, live
    #: inventory where a credential is set.
    provider: TravelProvider
    #: Called with a patch when a tool changes the trip.
    save: Callable[[dict[str, Any]], None] = lambda patch: None
    #: The day this turn happens on, as `YYYY-MM-DD`. Defaulted from the clock,
    #: because every caller in the app means now. It is here at all because
    #: `save_trip` refuses a start date in the past, so a tool reading the clock
    #: directly has behaviour that depends on the day it runs — and a golden of
    #: that would rot overnight.
    today: str | None = None

    def day(self) -> str:
        return self.today or _dt.date.today().isoformat()


def gemini_tools() -> list[dict[str, Any]]:
    """The tools in the shape the Interactions API wants them.

    Function declarations only. `voice_tools` reads `name`, `description` and
    `parameters` off every entry here, so a built-in tool — which has none of
    them — belongs in `grounding_tools` instead, not in this list.

    `get_trip` is not offered. This model is handed the whole trip in its system
    prompt, under "The trip so far", so calling it buys nothing — and it costs a
    round: the loop stops, sends the results back, and waits for the model to
    start again. A traced turn spent one of its three rounds, about eight
    seconds, reading back something it was already looking at.

    It still exists for MCP, where it is the only way a host can see the trip.
    """
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in TOOLS
        if tool["name"] != "get_trip"
    ]


#: Whether the model may look things up on the open web.
#:
#: On by default, off with `GROUNDING=off` — worth a switch because it is the
#: one thing here that reaches outside the process. A deployment that must be
#: reproducible, or one behind a network policy that forbids it, should be able
#: to say so without editing code.
GROUNDING = os.environ.get("GROUNDING", "on").strip().lower() not in {"off", "0", "false"}


#: Tools a host model may call for data rather than for a surface.
#:
#: Named as a set rather than "everything not `show_`" because the two lists are
#: read by different doors and a tool that quietly became callable over MCP
#: because of how its name was spelled would be a change nobody decided to make.
DATA_TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)


def is_data_tool(name: str) -> bool:
    return name in DATA_TOOL_NAMES


def mcp_data_tools() -> list[dict[str, Any]]:
    """The data tools in MCP's shape.

    Same contracts as the Gemini declarations — `data/tools.json` is the one
    source — re-keyed from `parameters` to `inputSchema`, which is the only
    thing the two protocols disagree about.
    """
    return [
        {
            "name": tool["name"],
            "title": tool["name"].replace("_", " ").capitalize(),
            "description": tool["description"],
            "inputSchema": tool["input_schema"],
        }
        for tool in TOOLS
    ]


def grounding_tools() -> list[dict[str, Any]]:
    """Google's own tools, for the parts of a trip that are facts about the world.

    The eight functions above answer with fixtures: a fare, a nightly rate, a
    list of neighbourhoods, all generated and all labelled as generated. That is
    honest for prices — nobody should trust a fare from a demo — but it is a
    poor answer for the half of planning that is not a price. Whether a place is
    worth three days or one, what is closed in April, whether the festival is
    the week they arrive: those are facts, they change, and no fixture will ever
    have them.

    So the model gets Search and URL context alongside its own tools, and the
    two do different jobs. Gemini 3 supports the combination; on a model that
    does not, this is the list to leave empty.

    These are *not* given to the voice session. The Live API takes a different
    tool shape, and the failure mode for getting it wrong is a setup frame
    rejected whole, with nothing naming the tool that caused it.
    """
    if not GROUNDING:
        return []
    return [{"type": "google_search"}, {"type": "url_context"}]


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _num(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _needs_input(what: str, missing: list[str]) -> dict[str, Any]:
    """A refusal that tells the model exactly how to stop being stuck.

    The failure this prevents is the confident one: with no dates the agent
    would price a week nobody chose, label it "estimated", and the traveller is
    then looking at fares for a trip that does not exist.
    """
    bound = ", ".join(f"${model.binding_for(key)}" for key in missing)
    return {
        "needs": missing,
        "message": (
            f"Cannot {what} without {model.ask_for(missing)}, and inventing a plausible answer "
            f"is worse than asking. Draw the controls for all of it in one surface — bound to "
            f"{bound} so the host pre-fills them — with a single commit button, and wait. If the "
            "traveler explicitly asked for a rough or seasonal figure, call again with "
            "flexible: true and label what you draw as indicative."
        ),
    }


def _cannot(outcome: NotFound) -> dict[str, Any]:
    """A provider with nothing, turned into something the model can act on.

    The counterpart to `_needs_input`. That one says "you have not asked the
    traveller enough"; this says "I asked and there is no answer" — and both end
    in a concrete next step rather than an empty surface.
    """
    return {
        "found": False,
        "reason": outcome.reason,
        "message": outcome.message,
        "options": outcome.recover,
        "provenance": outcome.provenance.as_dict(),
        "instruction": (
            "Say this in one short line and draw the options as choices the traveler can press. "
            "Do not substitute a different city, invent an airport code, or show an empty list."
        ),
    }


def _effective_trip(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """The trip a tool should reason about: what is saved, plus what this call says.

    The subtlety is **which stop**. A trip's flat fields describe the first one,
    so pricing any later stop against them quietly used the wrong party size,
    the wrong dates and the wrong departure airport — "New York back to SFO, two
    of us this time" priced one ticket, out of the original origin, on the
    outbound dates, and looked entirely plausible doing it.
    """
    saved = model.normalize(context.trip)
    asked = _str(args.get("destination"))

    stop = None
    if asked:
        # `stops()` resolves each leg against the one before it, so a leg that
        # never said where it departs from arrives here with that filled in.
        for leg in model.stops(saved):
            if leg.get("destination", "").lower() == asked.lower():
                stop = leg
                break

    base = dict(saved)
    if stop:
        base["destination"] = stop["destination"]
        for key in ("origin", "startDate", "endDate", "selectedHotel"):
            if stop.get(key):
                base[key] = stop[key]
        if stop.get("travelers") is not None:
            base["travelers"] = stop["travelers"]

    return model.merge(
        base,
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
        },
    )


def _estimate(
    destination: str,
    travelers: int | None,
    nights: int | None,
    flight_price: float | None,
    nightly_price: float | None,
) -> dict[str, Any]:
    """What a trip comes to, line by line.

    Arithmetic over numbers the caller already has, so it queries nothing and
    stays here rather than behind the provider interface.
    """
    from .providers.fixture import _js_round, _money, _rng, _seed, code_for_seed

    currency = "USD"
    people = max(1, travelers or 2)
    stay_nights = max(1, nights or 5)
    # Seeded on the resolved airport code, not the text. "Madrid", "madrid" and
    # "MAD" are one destination, and seeding on the spelling gives each of them
    # its own set of plausible prices for the same trip.
    code = code_for_seed(destination)
    random = _rng(_seed(f"estimate-{code}-{people}-{stay_nights}"))

    flight = (flight_price if flight_price is not None else 380 + random() * 180) * people
    stay = (nightly_price if nightly_price is not None else 140 + random() * 90) * stay_nights
    food = 55 * people * (stay_nights + 1)
    local = 24 * (stay_nights + 1)

    lines = [
        {
            "label": f"Flights ({people} traveler{'' if people == 1 else 's'})",
            "amount": _money(flight, currency),
        },
        {
            "label": f"Stay ({stay_nights} night{'' if stay_nights == 1 else 's'})",
            "amount": _money(stay, currency),
        },
        {"label": "Food and drink", "amount": _money(food, currency), "note": "estimated"},
        {"label": "Local transport", "amount": _money(local, currency), "note": "metro and taxis"},
    ]
    total = flight + stay + food + local
    return {
        "lines": lines,
        "total": _money(total, currency),
        "totalValue": _js_round(total),
        "currency": currency,
    }


async def run_tool(
    name: str, args: dict[str, Any], context: ToolContext
) -> tuple[Any, bool]:
    """Runs one tool call. Never raises: a thrown tool is a dead turn."""
    try:
        return await _run(name, args, context)
    except Exception as error:  # noqa: BLE001 - the message is what the model gets
        return {"error": str(error)}, True


async def _run(name: str, args: dict[str, Any], context: ToolContext) -> tuple[Any, bool]:
    provider = context.provider

    if name == "search_flights":
        trip = _effective_trip(args, context)
        missing = model.missing_for(trip, "priceFlights")
        if missing and args.get("flexible") is not True:
            return _needs_input("price flights", missing), False

        outcome = await provider.search_flights(
            {
                "destination": trip.get("destination") or _str(args.get("destination")),
                "origin": trip.get("origin"),
                "date": trip.get("startDate"),
                "travelers": trip.get("travelers"),
                "cabin": trip.get("cabin"),
                "maxPrice": trip.get("maxFare"),
                "nonstopOnly": args.get("nonstopOnly") is True or trip.get("nonstopOnly") is True,
                # `flexible` is the traveller asking what a trip like this
                # generally costs. The provider may answer without a departure
                # city, but has to say which one it sampled.
                "indicative": args.get("flexible") is True or bool(missing),
            }
        )
        if not outcome.ok:
            return _cannot(outcome), False

        return (
            {
                "flights": outcome.items,
                "currency": outcome.currency or "USD",
                "note": outcome.note,
                "provenance": outcome.provenance.as_dict(),
                "relaxed": outcome.relaxed,
                # Echoed back so the surface can say what it is showing. A price
                # with nothing beside it is the thing that made this untrustworthy.
                "searchedFor": {
                    "basis": model.basis_of(trip),
                    "date": trip.get("startDate"),
                    "origin": trip.get("origin"),
                    "travelers": trip.get("travelers"),
                    "cabin": trip.get("cabin") or "economy",
                    "indicative": bool(missing),
                },
            },
            False,
        )

    if name == "search_hotels":
        trip = _effective_trip(args, context)
        missing = model.missing_for(trip, "priceStay")
        stay_nights = args.get("nights") or model.nights(trip)
        if missing and stay_nights is None and args.get("flexible") is not True:
            return _needs_input("price a stay", missing), False

        outcome = await provider.search_hotels(
            {
                "destination": trip.get("destination") or _str(args.get("destination")),
                "nights": stay_nights,
                "travelers": trip.get("travelers"),
                "maxNightly": trip.get("maxNightly"),
                "neighborhood": trip.get("neighborhood"),
            }
        )
        if not outcome.ok:
            return _cannot(outcome), False

        return (
            {
                "hotels": outcome.items,
                "currency": outcome.currency or "USD",
                "note": outcome.note,
                "provenance": outcome.provenance.as_dict(),
                "relaxed": outcome.relaxed,
                "searchedFor": {
                    "basis": model.basis_of(trip),
                    "nights": stay_nights,
                    "travelers": trip.get("travelers"),
                    "checkIn": trip.get("startDate"),
                    "indicative": stay_nights is None,
                },
            },
            False,
        )

    if name == "get_destination":
        query = _str(args.get("destination"))
        if not query:
            return {"destinations": await provider.destinations()}, False
        destination = await provider.resolve_destination(query)
        if not destination:
            # A miss is not an error — it is information the model can act on,
            # and naming the alternatives turns it into a next step.
            return (
                {
                    "found": False,
                    "message": f"No detailed guide for '{query}'.",
                    "available": [entry["city"] for entry in await provider.destinations()],
                },
                False,
            )
        return {"found": True, **destination}, False

    if name == "get_weather":
        outcome = await provider.get_weather(
            _str(args.get("destination")),
            _str(args.get("startDate")) or None,
            int(args.get("days") or 5),
        )
        if not outcome.ok:
            return _cannot(outcome), False
        return {**outcome.items[0], "provenance": outcome.provenance.as_dict()}, False

    if name == "estimate_cost":
        trip = _effective_trip(args, context)
        missing = model.missing_for(trip, "totalTrip")
        stay_nights = args.get("nights") or model.nights(trip)
        if missing and args.get("flexible") is not True:
            return _needs_input("total up a trip", missing), False

        estimate = _estimate(
            trip.get("destination") or _str(args.get("destination")),
            trip.get("travelers"),
            stay_nights,
            _num(args.get("flightPrice")) or trip.get("flightPrice"),
            _num(args.get("nightlyPrice")) or trip.get("nightlyPrice"),
        )
        return (
            {
                **estimate,
                # A total is meaningless without the party size and length it
                # totals, so the caption travels with it.
                "basis": {
                    "summary": model.basis_of(trip),
                    "nights": stay_nights,
                    "travelers": trip.get("travelers"),
                    "startDate": trip.get("startDate"),
                    "endDate": trip.get("endDate"),
                    "indicative": bool(missing),
                },
            },
            False,
        )

    if name == "save_trip":
        # Normalised on the way in, so what is stored is in the trip's own
        # shapes rather than whatever the model happened to type.
        proposed = model.merge(model.normalize(context.trip), args)
        today = context.day()
        wrong = model.problems(proposed, today)

        # Refused rather than recorded: everything downstream prices against
        # these, and a range that ends before it starts produces numbers that
        # look authoritative and are not. An over-budget trip is a real state,
        # not a mistake, so it is reported and saved.
        blocking = [problem for problem in wrong if problem["field"] != "spent"]
        if blocking:
            return (
                {
                    "saved": False,
                    "problems": blocking,
                    "message": (
                        "Not saved: "
                        + " ".join(problem["message"] for problem in blocking)
                        + " Ask the traveler to confirm."
                    ),
                },
                # An error, unlike a search that found nothing: the model asked
                # for something to be stored and it was not.
                True,
            )

        context.save(model.normalize(args))
        saved = model.merge(model.normalize(context.trip), {})
        result: dict[str, Any] = {
            "saved": True,
            "trip": saved,
            "stillNeeded": model.summarize(saved, today)["missing"],
        }
        if wrong:
            result["warnings"] = wrong
        return result, False

    if name == "release_decision":
        asked = [
            str(key)
            for key in (args.get("fields") or [])
            if model.is_trip_key(str(key))
        ]
        stages = [str(stage) for stage in (args.get("stages") or [])]

        current = model.normalize(context.trip)
        current, cleared = model.release(current, asked)
        for stage in stages:
            current = model.unskip(current, stage)

        # The context's trip is the live object the turn reads, so it is
        # rewritten in place rather than replaced.
        context.trip.clear()
        context.trip.update(current)
        context.save({})

        today = context.day()
        if not cleared and not stages:
            message = "Nothing to release — it was not set."
        else:
            put_back = f"; put {', '.join(stages)} back in the plan" if stages else ""
            message = (
                f"Released {', '.join(cleared) or 'nothing'}{put_back}. "
                "Re-ask inline, pre-filled with what was there, and say what else this undid."
            )
        return (
            {
                "released": cleared,
                "unskipped": stages,
                "trip": current,
                "stillNeeded": model.summarize(current, today)["missing"],
                "message": message,
            },
            False,
        )

    if name == "get_trip":
        # The stored trip as it is, not a normalised view of it. The plan, the
        # summary and the next step are already in the turn's system prompt,
        # and repeating them in every tool result buys the model nothing while
        # costing a paragraph of context on each call.
        return {"trip": context.trip}, False

    return {"error": f"Unknown tool '{name}'."}, True
