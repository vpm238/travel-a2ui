"""What a trip is made of: the table, and the keys that address it.

The table itself is not written here. It lives in `data/trip-model.json` and
both this and the TypeScript model read it, because a second copy of a table is
a table that drifts — and this particular drift shows up as an agent asking for
something it already has.

What is here besides the table is how a key is read: whether it names a field
of the trip or of one hop (`legs/1/travelers`), what the data model calls it,
and whether a value counts as set at all. `_blank` is the one everything else
leans on: zero travellers is blank, an empty list is blank, `False` is not.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from ... import ROOT

Stage = Literal["route", "dates", "party", "flight", "stay", "budget", "plan"]
Trip = dict[str, Any]
Leg = dict[str, Any]

# src/travel_a2ui/brain/trip/ → travel_a2ui → src → server → apps → the project.
_ROOT = ROOT
_DATA = _ROOT / "data" / "trip-model.json"
_MODEL = json.loads(_DATA.read_text("utf-8"))

FIELDS: list[dict[str, Any]] = _MODEL["fields"]
STAGES: list[str] = _MODEL["stages"]
REQUIREMENTS: dict[str, list[str]] = _MODEL["requirements"]

BY_KEY: dict[str, dict[str, Any]] = {field["key"]: field for field in FIELDS}
TRIP_KEYS: list[str] = [field["key"] for field in FIELDS]

#: Field kinds whose value really is a list, and so are not unwrapped.
LIST_KINDS = frozenset({"stages", "legs", "fields", "days"})

#: The fields that are decisions rather than refinements.
#:
#: A decision is something the traveler settled and can press Change on, and
#: gaining or losing one is what makes the standing panel need *different*
#: controls. Everything else on the trip — a cabin preference, a neighbourhood,
#: a ceiling on the nightly rate, a note — refines a decision already made: it
#: reaches a standing surface live as `updateDataModel` and costs no model turn.
#:
#: Order is the order they are usually settled in, which is all that is left of
#: what used to be a stage ladder: a list for reading, not a sequence anything
#: is held to. Which one to settle next is the agent's judgement — see
#: `prompts/flow.md`.
DECISIONS: tuple[str, ...] = (
    "destination",
    "origin",
    "startDate",
    "endDate",
    "travelers",
    "selectedFlight",
    "selectedHotel",
    "budget",
    "planned",
    "skip",
    "legs",
    # A journey that does not come back needs a different panel: no return
    # date, no way-home fares, nothing waiting on a hop that is not coming.
    "oneWay",
)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE = re.compile(r"^[A-Z]{3}$")
_LEADING_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)")

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

#: A decision that belongs to a hop rather than to the trip: `legs/1/travelers`.
_LEG_KEY = re.compile(r"^legs/(\d+)/([A-Za-z]+)$")


def is_trip_key(key: str) -> bool:
    return key in BY_KEY


def is_hop_key(key: str) -> bool:
    """True for a decision that belongs to one hop: `legs/1/travelers`."""
    return bool(_LEG_KEY.match(key))


def field_for(key: str) -> dict[str, Any] | None:
    return BY_KEY.get(key)


def binding_for(key: str) -> str:
    """The data-model path a control binds to. One spelling, everywhere."""
    return f"/trip/{key}"


def _blank(value: Any) -> bool:
    return value is None or value == ""
