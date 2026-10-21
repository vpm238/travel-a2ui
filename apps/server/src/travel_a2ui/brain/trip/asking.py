"""What is still worth asking about, and how to say it.

`missing_for` is the strict half: which fields a goal cannot be reached
without. `summarize` is the half the prompt actually reads — what is known,
what is assumed, what is blocked and by what — and `basis_of` is the sentence
that says where the facts came from, so an agent does not re-ask for something
the traveller already said.

Strictness belongs in `missing_for` and nowhere else. Everything here that
softens it does so by naming what it is ruling out and why, which is how
`oneWay` stopped a trip being nagged about a way home it had already said it
did not want.
"""

from __future__ import annotations

from typing import Any, Sequence

from .fields import BY_KEY, FIELDS, REQUIREMENTS, Trip, _blank, _MONTHS
from .problems import nights, problems
from .route import _legs_of

def missing_for(trip: Trip, goal: str) -> list[str]:
    """The fields a goal needs and does not have.

    Strict, including on a one-way trip: pricing a stay or totalling a journey
    needs a length, and a tool that cannot find one must say so rather than
    invent five nights. What a one-way trip should not be *told*, every turn, is
    that it is missing a return date — and that is `summarize` below, which is
    what reaches the prompt.
    """
    return [key for key in REQUIREMENTS[goal] if _blank(trip.get(key))]


def can_do(trip: Trip, goal: str) -> bool:
    return not missing_for(trip, goal)


def ask_for(keys: Sequence[str]) -> str:
    """The missing fields as a sentence to put in front of a person."""
    labels = [BY_KEY[key]["label"] if key in BY_KEY else key for key in keys]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def summarize(trip: Trip, today: str | None = None) -> dict[str, Any]:
    """The trip as the app and the prompt both want to show it."""
    decided = [
        {"key": field["key"], "value": trip.get(field["key"]), "label": field["label"]}
        for field in FIELDS
        if not _blank(trip.get(field["key"]))
    ]

    # What the trip is still waiting on, as the prompt and `save_trip` report
    # it — minus anything the trip has ruled out.
    #
    # `endDate` on a one-way journey is the case. There is no day they come
    # back, so every goal that wants one reported it missing on every turn for
    # the rest of the conversation: the route said nothing was wanted and the
    # line beside it said "endDate", and the agent went looking for a return
    # date on a trip that had told it twice there was not one. The goals
    # themselves stay strict — `missing_for` is what stops a total inventing a
    # length — so a tool that needs nights still asks for the nights it is
    # pricing, which is a question with an answer.
    ruled_out = {"endDate"} if trip.get("oneWay") is True else set()
    missing: dict[str, None] = {}
    for goal in REQUIREMENTS:
        for key in missing_for(trip, goal):
            if key not in ruled_out:
                missing[key] = None

    night_count = nights(trip)
    out: dict[str, Any] = {"decided": decided, "missing": list(missing)}
    # Key order matches the TypeScript literal: `nights` is spread in before
    # `problems`, and omitted entirely when there is no coherent range.
    if night_count is not None:
        out["nights"] = night_count
    out["problems"] = problems(trip, today)
    return out


def _short_date(date_string: str) -> str:
    """`12 Apr`, the way `toLocaleDateString('en-GB', …)` writes it."""
    from datetime import date

    day = date.fromisoformat(date_string)
    return f"{day.day} {_MONTHS[day.month - 1]}"


def basis_of(trip: Trip) -> str:
    """How a surface should describe what it is showing.

    `LHR → Madrid · 12–19 Apr · 3 travellers`. A fare with no route, dates or
    party size beside it is the thing that makes an answer untrustworthy, and
    every priced surface is asked to carry this.
    """
    parts: list[str] = []

    if trip.get("origin") and trip.get("destination"):
        parts.append(f"{trip['origin']} → {trip['destination']}")
    elif trip.get("destination"):
        parts.append(trip["destination"])

    start, end = trip.get("startDate"), trip.get("endDate")
    if start and end:
        from_text, to_text = _short_date(start), _short_date(end)
        # Same month reads better as "12–19 Apr" than "12 Apr – 19 Apr".
        same_month = start[:7] == end[:7]
        parts.append(f"{from_text.split(' ')[0]}–{to_text}" if same_month else f"{from_text} – {to_text}")
    elif start:
        # A one-way or half-decided trip still says when it leaves, in the same
        # voice as the rest — a raw ISO date in a heading reads like a database.
        parts.append(f"from {_short_date(start)}")

    if trip.get("travelers") is not None:
        count = trip["travelers"]
        # A party that changes along the way cannot be stated as one number, and
        # stating it as one is worse than leaving it out: "1 traveller" over a
        # trip that flies home with two prices the whole thing for the wrong
        # party, which is exactly the untrustworthy answer this line exists to
        # prevent.
        counts = {count, *(leg["travelers"] for leg in _legs_of(trip) if leg.get("travelers"))}
        if len(counts) > 1:
            parts.append(f"{min(counts)}–{max(counts)} travellers")
        else:
            parts.append(f"{count} traveller{'' if count == 1 else 's'}")

    return " · ".join(parts)
