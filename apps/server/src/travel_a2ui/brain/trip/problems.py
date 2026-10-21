"""What is wrong with a trip, and what not to let into it.

Two kinds. `problems` is what the agent should be told — a date in the past, a
route that ends before it starts, a hop with nowhere to go — phrased so it can
be read out to the traveller and acted on. `sieve` is the other kind: values a
commit is not allowed to write at all, because a press and a `save_trip` can
both arrive carrying a date the traveller never agreed to.

They are deliberately separate. A problem is a thing to say; a refusal is a
thing to not do, and conflating them is how an agent ends up narrating a
validation rule instead of fixing the trip.
"""

from __future__ import annotations

from .fields import Trip
from .route import stops
from .values import _days_between, _to_date

def nights(trip: Trip) -> int | None:
    """Nights implied by the range, if there is a coherent one."""
    if not trip.get("startDate") or not trip.get("endDate"):
        return None
    span = _days_between(trip["endDate"], trip["startDate"])
    return span if span is not None and span > 0 else None


def days_until(trip: Trip, today: str) -> int | None:
    """Days until departure, from a given day. Negative means it has gone."""
    if not trip.get("startDate"):
        return None
    return _days_between(trip["startDate"], today)


def problems(trip: Trip, today: str | None = None) -> list[dict[str, str]]:
    """What is wrong with a trip as saved, as opposed to merely unfinished.

    Only things that would make a downstream number a lie. Somewhere to stay
    being undecided is fine; a return before the departure is not, because
    everything from nights to the total is computed off that range.
    """
    found: list[dict[str, str]] = []

    if trip.get("startDate") and trip.get("endDate") and nights(trip) is None:
        found.append(
            {
                "field": "endDate",
                "message": f"{trip['endDate']} is not after {trip['startDate']}.",
            }
        )
    if today and trip.get("startDate"):
        until = days_until(trip, today)
        if until is not None and until < 0:
            found.append({"field": "startDate", "message": f"{trip['startDate']} is in the past."})
    if trip.get("travelers") is not None and trip["travelers"] < 1:
        found.append({"field": "travelers", "message": "A trip needs at least one traveler."})
    if (
        trip.get("budget") is not None
        and trip.get("spent") is not None
        and trip["spent"] > trip["budget"]
    ):
        # Not an error — a real state a dashboard should show — so it is
        # reported rather than rejected.
        found.append({"field": "spent", "message": "Committed spend is over the budget."})

    found.extend(_route_problems(trip))
    return found


def _route_problems(trip: Trip) -> list[dict[str, str]]:
    """What is wrong with the route, stop by stop.

    The trip-level checks only ever saw the first stop, because that is what the
    flat fields describe. Everything after it lived in `legs` and was never
    looked at — so a second stop could check out before it checked in, and the
    trip saved cleanly. A multi-stop trip is the case this app exists to handle
    well, and it was the one with no validation at all.
    """
    found: list[dict[str, str]] = []
    route = stops(trip)

    for index in range(1, len(route)):
        leg = route[index]
        where = leg.get("destination") or f"stop {index + 1}"

        if not leg.get("destination"):
            found.append({"field": "legs", "message": f"Stop {index + 1} has no destination."})

        # Compared as dates, not as the strings they arrived as. A leg whose
        # dates came off a `DateRangePicker` holds RFC 3339 instants and the one
        # before it may hold plain dates, and `"2027-04-18" > "2027-04-12T00:00:00Z"`
        # is a string comparison that answers a question nobody asked.
        #
        # **A hop that arrives and leaves the same day is legal**, and it is the
        # commonest hop there is: the way home. `journey` has always read it
        # that way — `_nights_of` allows a span of nought — and the brief tells
        # the model in as many words to record the hop home as `startDate` and
        # `endDate` on the same day. This refused exactly that, and because
        # `save_trip` refused the whole call rather than the field, the trip
        # lost its dates, its party and anything else in the same breath. One
        # conversation in the measurements opened by being told "In JFK,
        # 2027-04-19 is not after 2027-04-19" and spent the next turn asking
        # again for dates it had just been given. Only a hop that ends *before*
        # it begins is wrong.
        start, end = _to_date(leg.get("startDate")), _to_date(leg.get("endDate"))
        if start and end and end < start:
            found.append({"field": "legs", "message": f"In {where}, {end} is before {start}."})

        if leg.get("travelers") is not None and leg["travelers"] < 1:
            found.append({"field": "legs", "message": f"{where} needs at least one traveler."})

        # A stop cannot begin before the one it follows has ended. `endDate or
        # startDate` so an open-ended previous stop still pins the earliest this
        # one can start.
        previous = route[index - 1]
        after = _to_date(previous.get("endDate")) or _to_date(previous.get("startDate"))
        if start and after and start < after:
            found.append(
                {
                    "field": "legs",
                    "message": (
                        f"{where} starts {start}, before "
                        f"{previous.get('destination') or 'the previous stop'} ends {after}. "
                        "Stops are in travel order."
                    ),
                }
            )

    return found


#: Fields a trip will turn away rather than record.
#:
#: Everything downstream prices against these, so a range that ends before it
#: starts produces numbers that look authoritative and are not. Everything
#: *else* is recorded as given: an over-budget trip is a real state, not a
#: mistake.
#:
#: One table, read by every path a value can arrive on — a press committed by
#: the host and a `save_trip` the model made — because two copies of this list
#: is two rules, and the one that drifts is the one nobody is testing.
REFUSABLE: tuple[str, ...] = ("startDate", "endDate", "travelers", "legs")


def sieve(saved: Trip, proposed: Trip, today: str | None = None) -> tuple[Trip, list[str]]:
    """What of `proposed` can be recorded, and what had to be turned away.

    **Field by field, never the whole call.** `save_trip` used to refuse
    everything the moment any part of it was wrong, which sounds careful and is
    not: a model saving a chosen hotel, the party and the route in one call —
    which is what it does, because the call takes the whole trip — lost the
    hotel because a hop's dates were a day out. Measured in a real
    conversation: the traveller pressed a stay, the save was refused whole, the
    next turn read a trip with no stay in it and drew the fares again. "It does
    not save the hotel" was this.
    A refused field goes back to what was saved rather than being deleted —
    dropping it outright would lose a value they had already agreed to, which
    is a second wrong answer — and the messages go back to the model so the
    next surface re-asks for it, with everything else they said still in place.
    """
    def refusable(candidate: Trip) -> list[dict[str, str]]:
        return [
            problem
            for problem in problems(candidate, today)
            if problem["field"] in REFUSABLE
        ]

    found = refusable(proposed)
    if not found:
        return proposed, []

    def revert(candidate: Trip, fields: Iterable[str]) -> Trip:
        out = dict(candidate)
        for name in fields:
            if name in saved:
                out[name] = saved[name]
            else:
                out.pop(name, None)
        return out

    trip = revert(proposed, [problem["field"] for problem in found])

    # Reverting the field that *reported* the problem is not always enough, and
    # the date pair is the case that proves it. `problems` names `endDate` for a
    # range that runs backwards, so a commit of 20 Apr → 12 Apr over a saved
    # 1 Apr → 8 Apr reverts only the end and leaves 20 Apr → 8 Apr: still
    # backwards, still negative nights, and now a pair the traveller never
    # typed. A range is one decision, so when one end is refused and putting it
    # back does not settle it, the whole decision goes back.
    if refusable(trip):
        trip = revert(proposed, [name for name in REFUSABLE if proposed.get(name) != saved.get(name)])

    return trip, [problem["message"] for problem in found]
