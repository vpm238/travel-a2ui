"""What looks wrong with a trip, as notes for the agent.

A date in the past, a stay that ends before it starts, a hop with nowhere to
go — phrased so it can be read out to the traveller and acted on. They are
notes, never refusals: the trip records what the agent and the traveller wrote,
and the agent decides what to do about a note.
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
    if trip.get("budget") is not None and trip.get("spent") is not None and trip["spent"] > trip["budget"]:
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

        # A hop that goes nowhere.
        #
        # Nothing caught this, and it is what an ambiguous route turns into: "JFK
        # to Chicago then New York then back home", where home *is* New York,
        # was recorded as three hops ending JFK → JFK. Which is not a hop — it
        # cannot be priced, `search_flights` has nothing to look for, and the
        # panel draws a row for it that can never be filled. The agent then goes
        # on trying to ticket it every turn.
        #
        # A note, so the agent is told and asks instead of inventing a reading:
        # an ambiguous route is exactly the case where it should come back and
        # check.
        leaving = (leg.get("origin") or "").strip().casefold()
        arriving = (leg.get("destination") or "").strip().casefold()
        if leaving and arriving and leaving == arriving:
            found.append(
                {
                    "field": "legs",
                    "message": (
                        f"Stop {index + 1} flies from {where} to {where}. A hop has to go "
                        "somewhere — drop it, or ask which city they meant."
                    ),
                }
            )

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

    return found
