"""Presses the host answers itself, without waking the model.

Most of what a traveller presses is a question — pick this flight, search those
dates — and the answer needs judgement, so it goes to the model. A few presses
are not questions at all. Dropping an activity from a day plan is one: there is
nothing to decide, the outcome is completely determined by what was pressed, and
routing it through a model turn costs five to fifteen seconds and a chance of
the model rewriting the surface while it is at it.

So those are answered here, in single-digit milliseconds, and the reply is the
data-model update the renderer already knows how to apply.

**Why the server rather than the browser.** A2UI v0.9.1 has two kinds of action:
an event the host handles, and a client-side function call that computes a value
— it has no "mutate the data model" action. A row could be dropped in the
renderer, but then it would be dropped only in *this* renderer: the Flutter
client, an iOS client and the trip the agent reads next would all still have it.
The trip lives on the server, so the edit happens on the server, and every
client learns about it the same way it learns about everything else.

**Why it is a short list rather than a rule.** "Anything deterministic" is not
knowable from the outside — `search_flights` looks deterministic and is a
question about what to show next. Each entry here is a press somebody decided
needs no thought, and the rest keep going to the model.
"""

from __future__ import annotations

from typing import Any, Callable

#: What the model is told to name these, and what the host answers.
#:
#: Kept in one place so the prompt and the dispatch cannot disagree about the
#: spelling — a handler for `drop_activity` and a prompt that says
#: `remove_activity` is a button that silently costs a model turn.
DROP_ACTIVITY = "drop_activity"


def _index_of(context: dict[str, Any]) -> int | None:
    """Which row was dropped, from whatever the surface bound into the event."""
    for key in ("index", "activityIndex", "row"):
        value = context.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
    return None


def _drop_activity(trip: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    """Removes one activity from a day, and says nothing if it cannot.

    Addressed by day and index rather than by title, because two days can both
    contain "Lunch" and the traveller pressed one of them. A press that does not
    resolve is dropped rather than guessed at: removing the wrong activity is
    worse than removing none, and the surface is still on screen to press again.
    """
    days = trip.get("days")
    if not isinstance(days, list):
        return None

    day_index = _index_of({"index": context.get("day")}) if "day" in context else None
    activity_index = _index_of(context)
    if day_index is None or activity_index is None:
        return None
    if not (0 <= day_index < len(days)):
        return None

    day = days[day_index]
    if not isinstance(day, dict):
        return None
    activities = day.get("activities")
    if not isinstance(activities, list) or not (0 <= activity_index < len(activities)):
        return None

    remaining = [*activities[:activity_index], *activities[activity_index + 1 :]]
    # A day emptied of everything stays. An empty day is a real answer — a rest
    # day — and deleting the card would lose the date with it.
    updated = [*days]
    updated[day_index] = {**day, "activities": remaining}
    return {"days": updated}


#: Press name → what it does to the trip, or `None` when it cannot be done.
HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]] = {
    DROP_ACTIVITY: _drop_activity,
}


def handles(name: str) -> bool:
    """Whether this press is answered here rather than by the model."""
    return name in HANDLERS


def apply(name: str, trip: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    """The patch this press makes to the trip, or nothing."""
    handler = HANDLERS.get(name)
    return handler(trip, context) if handler else None
