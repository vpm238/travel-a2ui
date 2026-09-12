"""What a trip is, and what the agent should do about it next.

This is the one piece of the project that is neither generated from the catalog
nor provided by the SDK — judgement about which fields block which goals, what
to ask for next, and when to stop asking. It is a port of the TypeScript model,
held to it by `tools/parity/__golden__/trip.json`: nine trips chosen for the
decisions they force, run through every function here, compared byte for byte.

The field table itself is not ported. It lives in `data/trip-model.json` and
both implementations read it, because a second copy of a table is a table that
drifts — and this particular drift shows up as an agent asking for something it
already has.

**Where a port like this goes wrong is JavaScript semantics, not logic.** Three
of them are load-bearing here and each has a comment where it bites:

  * `Math.round` rounds halves toward positive infinity; Python's `round` rounds
    them to even, so `round(2.5)` is 2 and `Math.round(2.5)` is 3.
  * `parseFloat` takes the longest numeric prefix and ignores the rest, where
    `float()` raises.
  * `JSON.stringify` drops keys whose value is `undefined`, so a key set to
    nothing in JavaScript is a key that must never be set here.

The golden catches all three, which is why it was written before this file.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from typing import Any, Iterable, Literal, Sequence

Stage = Literal["route", "dates", "party", "flight", "stay", "budget", "plan"]
Trip = dict[str, Any]
Leg = dict[str, Any]

# src/travel_a2ui/trip.py → travel_a2ui → src → server → apps → the project.
_ROOT = pathlib.Path(__file__).resolve().parents[4]
_DATA = _ROOT / "data" / "trip-model.json"
_MODEL = json.loads(_DATA.read_text("utf-8"))

FIELDS: list[dict[str, Any]] = _MODEL["fields"]
STAGES: list[str] = _MODEL["stages"]
REQUIREMENTS: dict[str, list[str]] = _MODEL["requirements"]

BY_KEY: dict[str, dict[str, Any]] = {field["key"]: field for field in FIELDS}
TRIP_KEYS: list[str] = [field["key"] for field in FIELDS]

#: Field kinds whose value really is a list, and so are not unwrapped.
LIST_KINDS = frozenset({"stages", "legs", "fields"})

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE = re.compile(r"^[A-Z]{3}$")
_LEADING_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)")

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def is_trip_key(key: str) -> bool:
    return key in BY_KEY


def field_for(key: str) -> dict[str, Any] | None:
    return BY_KEY.get(key)


def binding_for(key: str) -> str:
    """The data-model path a control binds to. One spelling, everywhere."""
    return f"/trip/{key}"


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _js_round(value: float) -> int:
    """`Math.round`: halves go toward positive infinity.

    Python's `round` is banker's rounding — `round(2.5)` is 2 — so a party of
    2.5 would come out as two people here and three in the browser.
    """
    return math.floor(value + 0.5)


def _to_number(value: Any) -> float | None:
    """`parseFloat` over a string with the non-numeric characters stripped.

    Money arrives from an interface as "$1,240" as often as 1240. The prefix
    behaviour matters: `parseFloat("1.2.3")` is 1.2 where `float("1.2.3")`
    raises, and a version string reaching here should degrade the same way in
    both implementations rather than throwing in one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^0-9.-]", "", value)
    match = _LEADING_NUMBER.match(cleaned)
    if not match:
        return None
    try:
        parsed = float(match.group(0))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _to_date(value: Any) -> str | None:
    """A date as `YYYY-MM-DD`, from any shape an interface produces.

    `<input type="date">` gives a plain date, A2UI's DateRangePicker binds an
    RFC 3339 instant, and a model writing JSON produces either. Storing both and
    comparing them later is how a range ends up looking invalid when it is not.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    if not isinstance(value, str) or not value.strip():
        return None
    trimmed = value.strip()
    if _DATE_ONLY.match(trimmed):
        return trimmed
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.date().isoformat()


def _to_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in ("true", "yes", 1):
        return True
    if value in ("false", "no", 0):
        return False
    return None


def _to_leg(value: Any) -> Leg | None:
    """A leg from whatever shape it arrived in, or nothing if it names no place."""
    if not isinstance(value, dict):
        return None
    raw = value
    destination = raw.get("destination")
    destination = destination.strip() if isinstance(destination, str) else ""
    if not destination:
        return None

    def text(key: str) -> str | None:
        candidate = raw.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:200]
        return None

    origin_raw = raw.get("origin")
    origin = (
        origin_raw.strip().upper()
        if isinstance(origin_raw, str) and re.fullmatch(r"[A-Za-z]{3}", origin_raw.strip())
        else None
    )

    party = _to_number(raw.get("travelers"))
    travelers = None if party is None else max(1, _js_round(party))
    needs_stay = _to_flag(raw.get("needsStay"))
    # A leg carries its own flight, because a return is a separate ticket that
    # somebody has to choose. Without this the trip had one `selectedFlight`
    # for the whole journey, so the flight stage counted itself finished the
    # moment the outbound was picked and the traveller was never offered a way
    # home.
    fare = _to_number(raw.get("flightPrice"))
    nightly = _to_number(raw.get("nightlyPrice"))

    # Key order mirrors the TypeScript object literal, because the golden
    # compares serialised JSON.
    leg: Leg = {"destination": destination[:120]}
    start = _to_date(raw.get("startDate"))
    end = _to_date(raw.get("endDate"))
    if start:
        leg["startDate"] = start
    if end:
        leg["endDate"] = end
    if origin:
        leg["origin"] = origin
    if travelers is not None:
        leg["travelers"] = travelers
    if needs_stay is not None:
        leg["needsStay"] = needs_stay
    if text("selectedFlight"):
        leg["selectedFlight"] = text("selectedFlight")
    if fare is not None:
        leg["flightPrice"] = _js_round(fare)
    if text("selectedHotel"):
        leg["selectedHotel"] = text("selectedHotel")
    if nightly is not None:
        leg["nightlyPrice"] = _js_round(nightly)
    if text("purpose"):
        leg["purpose"] = text("purpose")
    if text("notes"):
        leg["notes"] = text("notes")
    return leg


def coerce(key: str, value: Any) -> Any:
    """One loose value in the field's shape, or nothing.

    The case worth naming is a multi-select bound to a single-valued field: a
    ChoicePicker hands back `["economy"]`, and a tool expecting a string then
    searches for a cabin called `economy,` — no error, wrong answer.
    """
    field = BY_KEY.get(key)
    if field is None or _blank(value):
        return None

    kind = field["kind"]

    if isinstance(value, list) and kind not in LIST_KINDS:
        return coerce(key, value[0]) if len(value) == 1 else None

    if kind == "stages":
        entries = value if isinstance(value, list) else [value]
        wanted = [str(entry).strip().lower() for entry in entries]
        kept = list(dict.fromkeys(entry for entry in wanted if entry in STAGES))
        return kept or None

    if kind == "fields":
        entries = value if isinstance(value, list) else [value]
        named = [str(entry).strip() for entry in entries]
        kept = list(
            dict.fromkeys(entry for entry in named if entry in BY_KEY and entry != "assumed")
        )
        return kept or None

    if kind == "legs":
        entries = value if isinstance(value, list) else [value]
        legs = [leg for leg in (_to_leg(entry) for entry in entries) if leg is not None]
        return legs or None

    if kind == "date":
        return _to_date(value)

    if kind == "count":
        count = _to_number(value)
        return None if count is None else max(0, _js_round(count))

    if kind == "money":
        amount = _to_number(value)
        return None if amount is None or amount < 0 else _js_round(amount)

    if kind == "flag":
        return _to_flag(value)

    if kind == "code":
        code = str(value).strip().upper()
        return code if _CODE.match(code) else None

    if kind == "choice":
        choice = str(value).strip().lower()
        return choice if choice in (field.get("options") or []) else None

    text = str(value).strip()
    return text[:400] if text else None


def normalize(value: Any) -> Trip:
    """Everything in `value` that belongs to a trip, in the shape a trip wants."""
    if not isinstance(value, dict):
        return {}
    out: Trip = {}
    for key, raw in value.items():
        coerced = coerce(key, raw)
        if coerced is not None:
            out[key] = coerced
    return out


def merge(trip: Trip, patch: Any) -> Trip:
    """A patch applied to a trip, with the patch normalised first.

    `assumed` is the one field that does not simply overwrite. A patch saying
    "these two were guesses" is talking about the fields in *that* patch, and a
    later patch stating one of them for real has to clear its mark. So anything
    the patch sets is confirmed unless the patch itself names it as assumed, and
    marks on fields the patch does not mention are kept.
    """
    nxt = normalize(patch)
    declared = list(nxt.get("assumed") or [])
    touched = {key for key in nxt if key != "assumed"}

    assumed = [key for key in (trip.get("assumed") or []) if key not in touched] + declared

    merged: Trip = {**trip, **nxt}
    if assumed:
        merged["assumed"] = list(dict.fromkeys(assumed))
    else:
        merged.pop("assumed", None)
    return merged


def confirm(trip: Trip, fields: Iterable[str]) -> Trip:
    """Marks fields as confirmed — what a traveller pressing a button means."""
    said = set(fields)
    left = [key for key in (trip.get("assumed") or []) if key not in said]
    nxt = dict(trip)
    if left:
        nxt["assumed"] = left
    else:
        nxt.pop("assumed", None)
    return nxt


#: What else has to be let go when one decision is released.
#:
#: Changing the dates does not just change the dates: the flight was priced
#: against them and the stay was booked for those nights. Deliberately shallow —
#: one level, and only where the dependency is real. Cascading further would
#: clear a trip someone spent an hour on because they moved a date by a day.
DEPENDENTS: dict[str, list[str]] = {
    "destination": [
        "selectedFlight",
        "flightPrice",
        "selectedHotel",
        "nightlyPrice",
        "neighborhood",
        "planned",
    ],
    "origin": ["selectedFlight", "flightPrice"],
    "startDate": ["selectedFlight", "flightPrice", "selectedHotel", "nightlyPrice", "planned"],
    "endDate": ["selectedHotel", "nightlyPrice", "planned"],
    "travelers": ["selectedFlight", "flightPrice", "selectedHotel", "nightlyPrice"],
    "selectedFlight": ["flightPrice"],
    "selectedHotel": ["nightlyPrice"],
}


def released(keys: Sequence[str]) -> list[str]:
    """The fields a release clears: the one named, plus what depended on it."""
    out: dict[str, None] = {}
    for key in keys:
        out[key] = None
        for dependent in DEPENDENTS.get(key, []):
            out[dependent] = None
    return list(out)


def release(trip: Trip, keys: Sequence[str]) -> tuple[Trip, list[str]]:
    """Lets go of a decision so it can be made again."""
    cleared = [key for key in released(keys) if trip.get(key) is not None]
    nxt = dict(trip)
    for key in cleared:
        nxt.pop(key, None)
    return nxt, cleared


def unskip(trip: Trip, stage: str) -> Trip:
    """Puts a ruled-out stage back into the plan."""
    remaining = [entry for entry in (trip.get("skip") or []) if entry != stage]
    nxt = dict(trip)
    if remaining:
        nxt["skip"] = remaining
    else:
        nxt.pop("skip", None)
    return nxt


def _days_between(later: str, earlier: str) -> int | None:
    from datetime import date

    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except ValueError:
        return None


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

        start, end = leg.get("startDate"), leg.get("endDate")
        if start and end and not end > start:
            found.append({"field": "legs", "message": f"In {where}, {end} is not after {start}."})

        if leg.get("travelers") is not None and leg["travelers"] < 1:
            found.append({"field": "legs", "message": f"{where} needs at least one traveler."})

        # A stop cannot begin before the one it follows has ended. `endDate or
        # startDate` so an open-ended previous stop still pins the earliest this
        # one can start.
        previous = route[index - 1]
        after = previous.get("endDate") or previous.get("startDate")
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


def missing_for(trip: Trip, goal: str) -> list[str]:
    """The fields a goal needs and does not have."""
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

    missing: dict[str, None] = {}
    for goal in REQUIREMENTS:
        for key in missing_for(trip, goal):
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


def _legs_of(trip: Trip) -> list[dict[str, Any]]:
    """The legs, as a list of dicts, whatever the trip actually holds."""
    legs = trip.get("legs")
    return [leg for leg in legs if isinstance(leg, dict)] if isinstance(legs, list) else []


STEPS: list[dict[str, Any]] = [
    {
        "stage": "route",
        "label": "settle where they are going and flying from",
        "needs": ["destination", "origin"],
    },
    {"stage": "dates", "label": "settle the dates", "needs": ["startDate", "endDate"]},
    {"stage": "party", "label": "settle how many are travelling", "needs": ["travelers"]},
    # No trip-level field, for the same reason `stay` has none: a journey with
    # more than one hop needs a ticket for each, and `selectedFlight` alone
    # declared the stage finished as soon as the outbound was chosen.
    # `_pending_for` is what makes this step complete.
    {"stage": "flight", "label": "choose a flight for each hop", "needs": []},
    # No trip-level field: whether a stay is needed, and which one, is decided
    # per stop. `_pending_for` is what makes this step complete.
    {"stage": "stay", "label": "sort out where you are sleeping, stop by stop", "needs": []},
    {"stage": "budget", "label": "agree what the trip should cost", "needs": ["budget"]},
    {"stage": "plan", "label": "plan the days", "needs": ["planned"]},
]


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
        # The trip's own choices belong to the first stop, which is what the
        # flat fields describe.
        #
        # `selectedHotel` was carried and the other three were not, so the first
        # hop of a multi-stop trip looked like the one leg nobody had priced:
        # every other leg reported its own fare and Chicago reported none, and
        # anything totalling the trip either guessed at it or dropped it. The
        # flat fields *are* the first leg; they are flat because most trips have
        # only one.
        for field in ("selectedHotel", "selectedFlight", "flightPrice", "nightlyPrice"):
            if index == 0 and leg.get(field) is None and trip.get(field) is not None:
                out[field] = trip[field]
        resolved.append(out)

    return resolved


def stay_status(trip: Trip) -> dict[str, list[str]]:
    """Stops grouped by where the question of somewhere to stay has got to."""
    unasked: list[str] = []
    needed: list[str] = []
    booked: list[str] = []
    not_needed: list[str] = []

    legs = stops(trip)
    for index, leg in enumerate(legs):
        # Nobody books a hotel in the city they live in. The last hop of a round
        # trip lands back where the trip started, and asking "where are you
        # staying in San Francisco?" of someone who has just flown home is the
        # kind of question that makes an agent look like a form.
        if (
            index == len(legs) - 1
            and index > 0
            and trip.get("origin")
            and leg["destination"] == trip["origin"]
            and not leg.get("selectedHotel")
        ):
            not_needed.append(leg["destination"])
            continue
        # A stay already chosen answers the question, whether or not anyone asked.
        if leg.get("selectedHotel"):
            booked.append(leg["destination"])
        elif leg.get("needsStay") is False:
            not_needed.append(leg["destination"])
        elif leg.get("needsStay") is True:
            needed.append(leg["destination"])
        else:
            unasked.append(leg["destination"])

    return {"unasked": unasked, "needed": needed, "booked": booked, "notNeeded": not_needed}


def party_varies(trip: Trip) -> bool:
    """True when the legs do not all carry the same number of people."""
    counts = {leg["travelers"] for leg in stops(trip) if leg.get("travelers") is not None}
    return len(counts) > 1


def _pending_for(trip: Trip, stage: str, legs: list[Leg]) -> dict[str, Any] | None:
    """What a per-stop stage is still waiting on, if anything.

    Three stages are per-stop. Dates, because every place needs a span.
    Somewhere to stay, because that is a question you ask city by city — and the
    answer "not there, I'm at my sister's" has to be recordable, or the agent
    asks about it forever. And the flight, because a return is a separate ticket:
    a trip with one `selectedFlight` counted the whole journey settled the moment
    the outbound was chosen, and the traveller was never offered a way home.
    """
    if stage == "flight":
        if not legs:
            return {"stops": [], "want": "a destination first"}
        # The first leg is the flat `selectedFlight`; the rest carry their own.
        # `stops()` has already resolved each leg's origin against the one
        # before it, so "unflown" is genuinely the list of hops with no ticket.
        unflown = [
            leg["destination"]
            for index, leg in enumerate(legs)
            if not (trip.get("selectedFlight") if index == 0 else leg.get("selectedFlight"))
        ]

        # The way home is a hop like any other, and it is the one that kept
        # going missing. "SFO to New York" is one leg, so the moment the
        # outbound was chosen the flight stage counted itself finished and the
        # plan moved on to hotels — with the traveller still in New York.
        #
        # There is no `returnFlight` field, deliberately. A return *is* a leg,
        # and saying so once here means a three-city trip and a round trip are
        # the same shape rather than two cases. Record the journey home as a leg
        # and this falls silent on its own; say it is one-way — `skip:
        # ["return"]` — and it stays silent too.
        home = trip.get("origin")
        if home and "return" not in set(trip.get("skip") or []) and legs[-1]["destination"] != home:
            # Named rather than listed as a bare code, because this reads out on
            # the panel beside real city names — "Flight — Madrid, JFK" looks
            # like a second destination, and "Madrid, home (JFK)" is the hop it
            # actually is. The code stays so the agent knows what to search.
            unflown.append(f"home ({home})")

        return {"stops": unflown, "want": "a flight"} if unflown else None

    if stage == "dates":
        undated = [
            leg["destination"] for leg in legs if not leg.get("startDate") or not leg.get("endDate")
        ]
        return {"stops": undated, "want": "dates"} if undated else None

    if stage == "stay":
        # A per-stop stage cannot be settled before there are stops. Without
        # this an empty trip counts "somewhere to stay" as done, and the plan
        # opens at step two of a trip nobody has started.
        if not legs:
            return {"stops": [], "want": "a destination first"}

        status = stay_status(trip)
        if status["unasked"]:
            return {"stops": status["unasked"], "want": "to know whether a stay is needed"}
        if status["needed"]:
            return {"stops": status["needed"], "want": "somewhere to stay"}

    return None


def plan(trip: Trip) -> dict[str, Any]:
    """The trip as steps, bending around what this particular trip does not need."""
    skipped = set(trip.get("skip") or [])
    assumed = set(trip.get("assumed") or [])
    legs = stops(trip)

    steps: list[dict[str, Any]] = []
    for step in STEPS:
        if step["stage"] in skipped:
            steps.append({**step, "missing": [], "done": True, "skipped": True})
            continue

        missing: list[str] = []
        for key in step["needs"]:
            value = trip.get(key)
            # A flag is only satisfied when it is actually true: `planned: false`
            # means the days are still unplanned, not that the question was
            # answered.
            if _blank(value) or (BY_KEY.get(key, {}).get("kind") == "flag" and value is not True):
                missing.append(key)
            elif key in assumed:
                # Present, but nobody said it. It pre-fills the control and
                # still counts as missing, which is the whole point: a guess
                # should not close a question.
                missing.append(key)

        pending = _pending_for(trip, step["stage"], legs)

        entry: dict[str, Any] = {**step, "missing": missing}
        if pending:
            entry["pending"] = pending
        entry["done"] = not missing and not pending
        entry["skipped"] = False
        steps.append(entry)

    nxt = next((step for step in steps if not step["done"]), None)
    done = sum(1 for step in steps if step["done"])

    out: dict[str, Any] = {"steps": steps}
    if nxt is not None:
        out["next"] = nxt
    out["done"] = done
    out["total"] = len(steps)
    out["complete"] = nxt is None
    return out


def next_step_for(trip: Trip) -> str:
    """What the agent should be doing on this turn, in one line.

    Deliberately imperative, because it is dropped straight into the prompt and
    the job it has to do there is stop the agent from stalling politely.
    """
    state = plan(trip)
    legs = stops(trip)

    if state["complete"]:
        across = f", across all {len(legs)} stops" if len(legs) > 1 else ""
        return (
            f"The trip is planned — every stage is settled or ruled out{across}. Do not invent "
            "another question about it. Show them the whole trip on one surface, offer the two "
            "things that are actually left — adding more to the days, or sharing the plan with "
            "whoever else is coming — and wish them a good trip."
        )

    step = state["next"]
    parts = [f"Step {state['done'] + 1} of {state['total']}: {step['label']}."]

    pending = step.get("pending")
    if pending and pending["stops"]:
        tail = (
            "Ask per stop, in one surface: which of these need somewhere to stay and which do "
            "not. Record a stop that does not with needsStay: false on its leg, and stop asking "
            "about it."
            if step["stage"] == "stay"
            else "A trip with several stops needs one for each, not one covering all of them."
        )
        parts.append(f"Waiting on {', '.join(pending['stops'])} — {pending['want']}. {tail}")

    if step["missing"]:
        bound = ", ".join(f"${binding_for(key)}" for key in step["missing"])
        parts.append(
            f"You still need {ask_for(step['missing'])} — ask for all of it in one surface, "
            f"bound to {bound}, with one button."
        )
    if not step["missing"] and not pending:
        parts.append("Draw what it needs and move it forward.")

    parts.append(
        "End every turn having moved the trip on, or having asked exactly what it takes to. If "
        "this stage does not apply to their trip — driving rather than flying, staying with "
        f'family, no fixed budget — record that with save_trip (skip: ["{step["stage"]}"]) and go '
        "to the next one instead of asking a question they have already answered."
    )

    return " ".join(parts)


def decision_shape(trip: Trip) -> str:
    """The decisions that make the panel a *different panel*.

    Not every field. Values reach a standing surface live, as `updateDataModel`
    with no model in the path — change the departure airport on an inline card
    and the panel's origin updates immediately. What warrants a *rebuild* is the
    panel needing different controls. Rebuilding on a slider value would mean a
    model turn every time someone dragged something.
    """
    settled = ",".join(step["stage"] for step in plan(trip)["steps"] if step["done"])
    return "|".join(
        [
            settled,
            trip.get("destination") or "",
            trip.get("selectedFlight") or "",
            trip.get("selectedHotel") or "",
            ">".join(leg.get("destination", "") for leg in (trip.get("legs") or [])),
        ]
    )
