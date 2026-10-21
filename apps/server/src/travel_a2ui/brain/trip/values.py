"""Reading a value the way the model wrote it, not the way it should have.

A model writes `"2"` where the schema says a number, `"next Tuesday"` where it
says a date, and a whole leg where it means one field of one. Every one of
those is coerced here, once, so the rest of the model can assume a trip's
fields hold what they claim to.

**Where a port like this goes wrong is JavaScript semantics, not logic**, and
the three that are load-bearing all live in this file, each with a comment
where it bites:

  * `Math.round` rounds halves toward positive infinity; Python's `round` rounds
    them to even, so `round(2.5)` is 2 and `Math.round(2.5)` is 3.
  * `parseFloat` takes the longest numeric prefix and ignores the rest, where
    `float()` raises.
  * `JSON.stringify` drops keys whose value is `undefined`, so a key set to
    nothing in JavaScript is a key that must never be set here.

The golden catches all three, which is why it was written before this file.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .fields import (
    BY_KEY,
    LIST_KINDS,
    STAGES,
    Leg,
    _blank,
    _CODE,
    _DATE_ONLY,
    _LEADING_NUMBER,
)

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


def _to_activity(value: Any) -> dict[str, Any] | None:
    """One scheduled thing, or nothing if it has no name.

    Deliberately narrow. An activity is a title and some optional decoration —
    the moment it grows a price or a booking reference it has become a decision,
    and decisions live in their own fields where releasing one can clear what
    depended on it.
    """
    if isinstance(value, str):
        title = value.strip()
        return {"title": title[:120]} if title else None
    if not isinstance(value, dict):
        return None

    title = value.get("title") or value.get("name")
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        return None

    out: dict[str, Any] = {"title": title[:120]}
    for key in ("time", "category", "location", "duration", "note"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            out[key] = text.strip()[:160]
    if value.get("done") is True:
        out["done"] = True
    return out


def _to_day(value: Any) -> dict[str, Any] | None:
    """One day of the plan, with its activities in the order they arrived.

    A day with no activities is kept, because an empty day is a real answer — a
    rest day, or a day somebody has just emptied — and dropping it would lose
    the date with it.
    """
    if not isinstance(value, dict):
        return None

    title = value.get("title")
    title = title.strip() if isinstance(title, str) else ""
    date = _to_date(value.get("date"))
    if not title and not date:
        return None

    raw = value.get("activities")
    entries = raw if isinstance(raw, list) else []
    activities = [item for item in (_to_activity(entry) for entry in entries) if item is not None]

    out: dict[str, Any] = {}
    if title:
        out["title"] = title[:120]
    if date:
        out["date"] = date
    summary = value.get("summary")
    if isinstance(summary, str) and summary.strip():
        out["summary"] = summary.strip()[:200]
    out["activities"] = activities
    return out


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
    # How they get there. Not every hop is flown: "we'll drive to Lisbon" and
    # "the train down to Kyoto" are hops of the journey that want no fare, no
    # search and no ticket — and without somewhere to say so, the agent either
    # kept offering flights for them or quietly dropped the hop from the route.
    mode = (raw.get("mode") or "").strip().lower() if isinstance(raw.get("mode"), str) else ""
    if mode in ("air", "car", "train", "bus", "ferry"):
        leg["mode"] = mode
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

    if kind == "days":
        entries = value if isinstance(value, list) else [value]
        days = [day for day in (_to_day(entry) for entry in entries) if day is not None]
        return days or None

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


def _days_between(later: str, earlier: str) -> int | None:
    """Days between two dates in whatever shape they arrived in.

    Through `_to_date` rather than `date.fromisoformat` directly, and that is
    the whole fix. A2UI's `DateRangePicker` binds an RFC 3339 instant, so a trip
    that came back off a surface holds `2027-04-18T00:00:00Z` — which
    `date.fromisoformat` rejects outright. This returned None, `nights` returned
    None, and `problems` reported "2027-04-18T00:00:00Z is not after
    2027-04-12T00:00:00Z" about a range six days long.

    Which the traveller then met as an agent that would not believe its own
    trip. Every turn opened by telling the model the dates had been refused and
    to ask for them again, so "book my flight home" drew an airport picker and
    a date range — eight times out of eight — instead of the fares home. The
    docstring on `_to_date` has named this exact failure since the day it was
    written: storing both shapes and comparing them later is how a range ends
    up looking invalid when it is not.
    """
    from datetime import date

    first, second = _to_date(later), _to_date(earlier)
    if not first or not second:
        return None
    try:
        return (date.fromisoformat(first) - date.fromisoformat(second)).days
    except ValueError:
        return None
