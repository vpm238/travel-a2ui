"""The switch: one function per tool name, and the dispatch over them.

`data/tools.json` says what each tool takes; this says what each one does. The
two are deliberately apart — the contract is prompt engineering, read by the
model before it decides anything, and this is the lookup it causes.

Everything a tool answers with goes through `answers.py`, so the wording of a
"cannot do that yet" or a fare priced for a party is the same whichever tool
hit it.
"""

from __future__ import annotations

import json
from typing import Any

from .. import trip as model
from .answers import (
    _cannot,
    _effective_trip,
    _estimate,
    _needs_input,
    _num,
    _priced_for,
    _route_note,
    _str,
    _trip_currency,
)
from .contracts import ToolContext
from .share import FIXTURE_NOTE, _share_page

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
                # The whole trip in one currency — see `fare_currency`.
                "currency": await _trip_currency(provider, context, trip),
            }
        )
        if not outcome.ok:
            return _cannot(outcome), False

        party = trip.get("travelers")
        return (
            {
                "flights": _priced_for(
                    outcome.items,
                    each="priceValue",
                    count=party if isinstance(party, int) else None,
                    unit="each",
                    whole=f"for {party}" if party else "",
                    currency=outcome.currency or "USD",
                ),
                "pricesAre": (
                    f"`price` is one ticket. `total` is all {party} on this hop, and "
                    f"`priceLabel` says both — put that on the card, not the bare fare: "
                    f"a per-person figure beside a party of {party} reads as the total "
                    f"and is wrong by {party}×."
                    if isinstance(party, int) and party > 1
                    else "One traveller, so `price` is the whole of it."
                ),
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
                **_route_note(context.trip, trip),
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
                "hotels": _priced_for(
                    outcome.items,
                    each="priceValue",
                    count=stay_nights if isinstance(stay_nights, int) else None,
                    unit="a night",
                    whole=f"for {stay_nights} nights" if stay_nights else "",
                    currency=outcome.currency or "USD",
                ),
                "pricesAre": (
                    f"`price` is one night. `total` is all {stay_nights} of them, and "
                    f"`priceLabel` says both — put that on the card."
                    if isinstance(stay_nights, int) and stay_nights > 1
                    else "One night, so `price` is the whole of it."
                ),
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
            # "What is it like there?" with no date means from today, and today
            # is the turn's day rather than the clock's — see `ToolContext.day`.
            _str(args.get("startDate")) or context.day(),
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
            model.stops(trip),
            await _trip_currency(provider, context, trip),
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
        current = model.normalize(context.trip)
        proposed = model.merge(current, args)
        today = context.day()

        # **What is sound is recorded; only the offending field is turned away.**
        #
        # This used to refuse the whole call, and `save_trip` takes the whole
        # trip — so one hop's dates being a day out threw away the chosen stay,
        # the party and the route that came with them. The model then read a
        # trip with no stay in it and drew the fares again at somebody who had
        # just picked a hotel.
        #
        # The sieve is the model's, the same one a button press goes through,
        # so a value is refused for the same reason wherever it came from.
        kept, refused = model.sieve(current, proposed, today)
        if refused:
            # A refused field goes back to what it was, and putting a value
            # *back* is not something a patch can express — a field that had no
            # value has to end with none. So the trip is rewritten in place, the
            # way `release_decision` rewrites it, and the save is announced with
            # nothing in it.
            context.trip.clear()
            context.trip.update(kept)
            context.save({})
        else:
            context.save(model.normalize(args))

        saved = model.merge(model.normalize(context.trip), {})
        result: dict[str, Any] = {
            "saved": True,
            "trip": saved,
            "stillNeeded": model.summarize(saved, today)["missing"],
        }
        if refused:
            # Named, so the next surface asks for it again rather than the model
            # believing it holds a value the trip turned down.
            result["refused"] = refused
            result["message"] = (
                "Saved, except: "
                + " ".join(refused)
                + " That field is still what it was — ask the traveler for it again, "
                "and keep everything else they said."
            )
        warnings = [problem for problem in model.problems(saved, today) if problem["field"] == "spent"]
        if warnings:
            result["warnings"] = warnings
        return result, False

    if name == "release_decision":
        # A trip field — `startDate` — or one hop's own, `legs/1/travelers`.
        # Both are decisions somebody made and can change, and releasing the
        # trip's party size because they changed their mind about one leg is
        # how a correction undoes an answer nobody was correcting.
        asked = [
            str(key)
            for key in (args.get("fields") or [])
            if model.is_trip_key(str(key)) or model.is_hop_key(str(key))
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

    if name == "share_plan":
        trip = _effective_trip(args, context)
        return (
            {
                "page": _share_page(trip, _str(args.get("note")), context.day()),
                "summary": model.basis_of(trip),
                "provenance": FIXTURE_NOTE,
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
