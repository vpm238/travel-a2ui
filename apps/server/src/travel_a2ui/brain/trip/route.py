"""The journey as hops: who is on each, what it costs, what it still needs.

A trip is stored as a destination and a list of legs, which is the shape the
model writes and the shape the tools read. Nobody plans a trip in that shape.
A traveller plans *hops* — out on Monday with two of us, back on Thursday with
one — and every surface that asks about the journey is a projection of those
hops.

So this turns the record into the hops: `stops` for where the route goes,
`journey` for what each hop has and still wants, `party_varies` for the one
fact that decides whether a single counter can express the party at all.
"""

from __future__ import annotations

from typing import Any

from .fields import Leg, Trip
from .values import _days_between, _to_date

def _legs_of(trip: Trip) -> list[dict[str, Any]]:
    """The legs, as a list of dicts, whatever the trip actually holds."""
    legs = trip.get("legs")
    return [leg for leg in legs if isinstance(leg, dict)] if isinstance(legs, list) else []


def stops(trip: Trip) -> list[Leg]:
    """Stops in order, each resolved against the trip and the stop before it.

    Two defaults are filled in here so nothing downstream reimplements them: a
    leg with no origin departs from wherever the previous leg ended, and a leg
    with no party size carries the trip's. Both are what a person means when
    they leave it out.
    """
    first: Leg | None = None
    if trip.get("destination"):
        first = {"destination": trip["destination"]}
        if trip.get("origin"):
            first["origin"] = trip["origin"]
        if trip.get("startDate"):
            first["startDate"] = trip["startDate"]
        if trip.get("endDate"):
            first["endDate"] = trip["endDate"]
        if trip.get("travelers") is not None:
            first["travelers"] = trip["travelers"]

    all_legs = ([first] if first else []) + list(trip.get("legs") or [])

    resolved: list[Leg] = []
    for index, leg in enumerate(all_legs):
        out: Leg = dict(leg)
        # Assigned rather than conditionally inserted so an existing key keeps
        # its position, exactly as a JavaScript spread does — and skipped when
        # there is no value, because `JSON.stringify` drops `undefined` and the
        # golden compares serialised JSON.
        origin = leg.get("origin") or (
            all_legs[index - 1]["destination"] if index > 0 else trip.get("origin")
        )
        if origin is not None:
            out["origin"] = origin
        travelers = leg.get("travelers") if leg.get("travelers") is not None else trip.get("travelers")
        if travelers is not None:
            out["travelers"] = travelers
        # **A hop ends when they leave it, which is the day the next hop
        # departs.** Nobody says "I leave Chicago on the 12th and also arrive in
        # New York on the 12th" — they say it once, and the second date is the
        # same fact written twice. Derived here so nothing downstream has to ask
        # for it: a stop whose nights were unknown had no nights, so it was
        # never offered a stay or a plan, and `journey` reported it as wanting
        # dates it had already been given.
        #
        # The last hop keeps no end, because it has none. It is where the
        # journey stops.
        if out.get("endDate") is None and index + 1 < len(all_legs):
            following = _to_date(all_legs[index + 1].get("startDate"))
            if following:
                out["endDate"] = following
        # The trip's own choices belong to the first stop, which is what the
        # flat fields describe.
        #
        # `selectedHotel` was carried and the other three were not, so the first
        # hop of a multi-stop trip looked like the one leg nobody had priced:
        # every other leg reported its own fare and Chicago reported none, and
        # anything totalling the trip either guessed at it or dropped it. The
        # flat fields *are* the first leg; they are flat because most trips have
        # only one.
        for field in (
            "selectedHotel",
            "selectedFlight",
            "flightPrice",
            "nightlyPrice",
            # "I'm at my sister's" has to be answerable for the first stop too.
            # Every other stop carries `needsStay` on its leg; the first stop is
            # the flat fields, so it carries it here — and without this the
            # question had no answer and the agent asked it every turn.
            "needsStay",
        ):
            if index == 0 and leg.get(field) is None and trip.get(field) is not None:
                out[field] = trip[field]
        resolved.append(out)

    return resolved


def _own_leg(trip: Trip, hop: int) -> Leg | None:
    """The `legs` entry a hop is stored in, or None when it is the flat fields.

    The route is the flat fields followed by `legs`, so hop *n* is `legs[n - 1]`
    — except on a trip with no destination, where there are no flat fields to
    describe a first hop and the route starts at `legs[0]`. Getting that offset
    wrong reads one hop's answer off the hop beside it, which is the whole class
    of bug this app keeps finding.
    """
    legs = _legs_of(trip)
    index = hop - 1 if trip.get("destination") else hop
    return legs[index] if 0 <= index < len(legs) else None


def party_varies(trip: Trip) -> bool:
    """True when the legs do not all carry the same number of people."""
    counts = {leg["travelers"] for leg in stops(trip) if leg.get("travelers") is not None}
    return len(counts) > 1


#: What a hop records, and what to call it on the panel.
#:
#: Flat on the trip for the first hop and on the leg for every other one —
#: `stops` resolves that, so this is one table rather than two.
_HOP_DECISIONS: tuple[tuple[str, str], ...] = (
    ("travelers", "who is on this hop"),
    ("selectedFlight", "the flight for this hop"),
    ("selectedHotel", "where you are staying here"),
)


def _nights_of(leg: Leg) -> int | None:
    """Nights this hop stays for, or None when it has no coherent range."""
    start, end = leg.get("startDate"), leg.get("endDate")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    span = _days_between(end, start)
    return span if span is not None and span >= 0 else None


def _planned_days(trip: Trip, leg: Leg) -> int:
    """Days of the plan that fall inside this hop's stay."""
    start, end = leg.get("startDate"), leg.get("endDate")
    if not isinstance(start, str) or not isinstance(end, str):
        return 0
    return sum(
        1
        for day in (trip.get("days") or [])
        if isinstance(day, dict)
        and isinstance(day.get("date"), str)
        and start <= day["date"] <= end
    )


def journey(trip: Trip) -> list[dict[str, Any]]:
    """The route as recorded, hop by hop, with what each hop has and lacks.

    Facts, in the order the traveler is travelling them — no opinion about which
    gap matters most, and nothing invented. A hop the agent has not recorded
    does not appear here, including the way home: noticing that a route ends
    somewhere other than home is judgement, and it lives in
    `prompts/journey.md` where it can be read and argued with.

    `stops` has already resolved each hop against the one before it, so a leg
    that never said where it departs from or how many are on it arrives here
    filled in, and every hop can be priced for the right number of people.

    **Three things are per hop, and the nights decide two of them.** Who is
    travelling, because parties change — somebody joins in Chicago, somebody
    flies home early, and a fare priced for the trip's number is wrong for the
    hop by exactly as many tickets as the difference. Then, for a hop that stays
    the night: somewhere to sleep, and something to do with the days. A hop that
    lands and leaves the same day wants neither, and asking about a hotel for
    nought nights is the question that makes an agent look like a form.
    """
    route = stops(trip)
    out: list[dict[str, Any]] = []
    for index, leg in enumerate(route):
        nights_here = _nights_of(leg)
        planned = _planned_days(trip, leg)
        flown = leg.get("mode") in (None, "", "air")
        last = index == len(route) - 1

        wants: list[str] = []
        # **A hop is dated by when it leaves.** It used to want an end date too,
        # and the last hop of every route can never have one — so every trip
        # ever recorded ended with a hop reporting, on every turn for the rest
        # of the conversation, that it was still waiting for dates. Measured:
        # the model was told a hop wanted dates, reached for the one tool that
        # asks for dates, and drew the date picker again over the hotels
        # somebody had just chosen. "It gets the dates thing again" is this
        # line.
        if not leg.get("startDate"):
            wants.append("dates")
        if leg.get("travelers") is None:
            wants.append("who is on it")
        if flown and not leg.get("selectedFlight"):
            wants.append("a ticket")
        # Nights decide both, and they are two separate answers. "I'm at my
        # sister's" — `needsStay: false` — settles the bed and nothing else:
        # they are still in that city for four days with nothing planned, and
        # treating one answer as both is how a stay somebody already had took
        # the itinerary down with it.
        if nights_here:
            if leg.get("needsStay") is not False and not leg.get("selectedHotel"):
                wants.append("somewhere to stay")
            if not planned:
                wants.append("things to do")

        hop: dict[str, Any] = {
            "hop": index,
            "from": leg.get("origin"),
            "to": leg["destination"],
            "wants": wants,
        }
        # Where the journey stops, said rather than inferred. A hop with no
        # `endDate` is either the last one or an open-ended stay, and those are
        # different answers to "when do they leave": the first needs nothing,
        # the second needs asking.
        if last:
            hop["last"] = True
        # Whether this hop's party is its own answer or the trip's, carried over.
        #
        # `stops` fills a leg's missing party from the trip, which is what
        # anybody means when they leave it out — and it means a hop nobody has
        # been asked about is indistinguishable here from one they answered.
        # So the surface never asked: three hops, two counters, and the party
        # flying home was whatever the first hop said. It is one word to say
        # which, and the brief can then ask for the hops that have not been
        # answered.
        own = _own_leg(trip, index)
        if own is not None and own.get("travelers") is None and leg.get("travelers") is not None:
            hop["partyInherited"] = True
        if nights_here is not None:
            hop["nights"] = nights_here
        if planned:
            hop["plannedDays"] = planned
        for key in ("startDate", "endDate", "travelers", "mode", "purpose"):
            if leg.get(key) is not None:
                hop[key] = leg[key]
        for key in ("selectedFlight", "flightPrice", "selectedHotel", "nightlyPrice"):
            if leg.get(key) is not None:
                hop[key] = leg[key]

        # What has been decided *on this hop*, addressed so the panel's Change
        # button can release exactly one of them. The first hop's decisions are
        # the trip's flat fields; every other hop's live on its leg.
        hop["decisions"] = [
            {
                "key": field if index == 0 else f"legs/{index - 1}/{field}",
                "label": label,
                "value": leg[field],
            }
            for field, label in _HOP_DECISIONS
            if leg.get(field) is not None
        ]
        out.append(hop)
    return out
