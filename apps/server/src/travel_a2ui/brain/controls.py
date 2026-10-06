"""The right control for the thing being asked.

A date typed into a text box is a date the traveller can get wrong, and the
model reaches for `TextField` whenever it is not thinking about it — which is
most of the time, because a text box is the thing that always works. The result
is an interface that *accepts* "next tuesday", "12/4", "April 12ish" and then
either refuses them three turns later or prices the wrong week.

An interface that cannot express a wrong answer is better than one that
validates a wrong answer, so this is a check rather than a rule the model is
merely asked to follow: a component bound to a trip field has to be a control
that fits the field. A departure airport is a set of pills, because the answer
is one of twenty-one airports and pills are how you say that. Dates are a date
picker. A party size is a counter.

The complaint goes back to the model in the same breath as everything else it
got wrong — see `unreported` in `agent.py` — so a surface that would have asked
badly is rewritten before anybody sees it, rather than being caught by the
traveller.

What this is *not*: a layout opinion. It says nothing about which components to
use for anything that is not a decision the trip records, which is where the
model's judgement belongs and where it is good.
"""

from __future__ import annotations

from .. import ROOT

import json
import pathlib
from typing import Any, Iterable

#: The table itself lives in `data/controls.json`, beside the other things a
#: person edits on purpose.
#:
#: Read here *and* rendered into the system prompt by `skills.py`, so the rule
#: the model is taught and the rule it is held to are the same rows. A prompt
#: that says one thing and a hand-kept list in Python that says another is two
#: rules, and they drift the first time somebody edits one.
_ROWS: list[dict[str, Any]] = json.loads(
    (ROOT / "data" / "controls.json").read_text("utf-8")
)["controls"]

#: Which controls may be bound to which trip fields. Keyed by the tail of the
#: JSON Pointer, so a leg's own dates (`/trip/legs/0/startDate`) are held to the
#: same rule as the trip's.
BY_FIELD: dict[str, tuple[str, ...]] = {
    row["field"]: tuple(row["allow"]) for row in _ROWS
}

#: What to say instead, in the model's own vocabulary.
INSTEAD: dict[str, str] = {row["field"]: row["instead"] for row in _ROWS}

#: Why, so the complaint teaches rather than merely refuses.
WHY: dict[str, str] = {row["field"]: row["why"] for row in _ROWS}


def as_rules() -> str:
    """The table as the lines that go in the prompt."""
    return "\n".join(
        f"- **{row['field']}** → {row['instead']} — {row['why']}." for row in _ROWS
    )


#: Components that take an answer, read off the catalog rather than listed here.
#:
#: The spec marks them, indirectly but reliably: `Checkable` gives a component
#: `checks`, client-side validation rules — and only something the traveller can
#: fill in has anything to validate. So the components carrying it are exactly
#: the inputs: `TextField`, `ChoicePicker`, `Slider`, `DateTimeInput`,
#: `DateRangePicker`, `TravelerCounter`, `CheckBox`, `Button`. `FlightOption`,
#: `PriceSummary` and `Text` do not carry it, because they show a value rather
#: than collect one.
#:
#: Without this the check fired on displays. A fare card is
#: `FlightOption(origin=$/trip/origin, …)` — it is *showing* which airports the
#: fare is between — and the rule read the binding, saw `origin`, and said an
#: airport cannot be answered in a `FlightOption`. True, and beside the point.
#: In the skill eval it rejected the flights turn on every variant, seven times
#: out of nine: a check calling correct surfaces wrong, on the one scenario it
#: was written to help with.
_CATALOG = json.loads(
    (ROOT / "catalogs" / "a2ui-travel" / "catalog.json")
    .read_text("utf-8")
)

ASKING: frozenset[str] = frozenset(
    name
    for name, entry in _CATALOG["components"].items()
    if "$defs/Checkable" in json.dumps(entry)
)

#: The properties an answer actually arrives in.
#:
#: An input's other properties are its furniture: `label`, `caption`, `min`,
#: `max`, `options`, and — on a `Button` — `action`, which carries what the
#: controls above it collected (`Event("search_flights", {origin:
#: $/trip/origin, …})`) rather than asking for any of it. Reading those as
#: questions is how this check used to say "a Button cannot ask for an airport",
#: which is true and not what the button was doing.
#:
#: `start` and `end` are here because `DateRangePicker` is the one input whose
#: answer is two values rather than one.
ANSWER_KEYS = frozenset({"value", "start", "end"})


def _bound_paths(node: dict[str, Any]) -> Iterable[str]:
    """Every data-model path this component *asks* the traveller to fill."""
    for key, value in node.items():
        if key not in ANSWER_KEYS or not isinstance(value, dict):
            continue
        path = value.get("path")
        if isinstance(path, str):
            yield path


def wrong_controls(messages: Iterable[dict[str, Any]]) -> list[str]:
    """Complaints about controls that cannot express a right answer.

    Reads compiled A2UI rather than Express, so it is one check for every door:
    the typed agent's inline block, the voice relay's surfaces and anything MCP
    renders all arrive here in the same shape.
    """
    said: list[str] = []
    seen: set[str] = set()

    for message in messages:
        update = message.get("updateComponents") or {}
        for node in update.get("components") or []:
            if not isinstance(node, dict):
                continue
            component = str(node.get("component") or "")
            if component not in ASKING:
                continue
            for path in _bound_paths(node):
                field = path.rsplit("/", 1)[-1]
                allowed = BY_FIELD.get(field)
                if not allowed or component in allowed:
                    continue
                key = f"{component}:{field}"
                if key in seen:
                    continue
                seen.add(key)
                said.append(
                    f"`{component}` is bound to `{path}`, which the traveller "
                    f"cannot answer correctly in one: use {INSTEAD[field]} instead — "
                    f"{WHY[field]}."
                )

    return said


def half_asked(messages: Iterable[dict[str, Any]], hops: Iterable[str]) -> str | None:
    """Why this surface asks some hops a question and not the others, or None.

    A party size belongs to a hop, not to a journey — somebody joins in Chicago,
    somebody flies home early — so a route of three hops is three counters. The
    brief says so, and its worked example drew two counters over three hops for
    months, which is what the model copied: on a measured SFO → Chicago → New
    York → home conversation the opening surface asked who was going to Chicago
    and who was going on from there, and never asked who was flying home. The
    hop home carried whatever the hop before it said, nobody was shown it, and
    the fares home were priced for a party nobody had confirmed.

    A prompt cannot guarantee this and has already failed to. This can: either
    the surface asks every hop or it asks none of them, and a surface that asks
    some is sent back naming the ones it left out.

    `hops` is every path a counter would bind to, in route order. One hop means
    nothing to be inconsistent about and the check does not run.
    """
    expected = [str(path) for path in hops]
    if len(expected) < 2:
        return None

    asked: set[str] = set()
    for message in messages:
        update = message.get("updateComponents") or {}
        for node in update.get("components") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("component") or "") not in ASKING:
                continue
            for path in _bound_paths(node):
                asked.add(path)

    answered = [path for path in expected if path in asked]
    if not answered or len(answered) == len(expected):
        return None

    absent = [path for path in expected if path not in asked]
    return (
        f"That surface asks who is on {len(answered)} of the {len(expected)} hops and "
        f"leaves out {', '.join(f'`{path}`' for path in absent)}. Every hop has its own "
        "party — somebody joins, somebody flies home early — so the hops you did not ask "
        "about will be priced for whatever the hop before them said, and nobody will have "
        "seen it. Draw one `TravelerCounter` per hop, labelled by hop and pre-filled from "
        "the trip, on the same surface with the same button."
    )


#: Keys a press uses to name the hop it belongs to. Mirrors `_leg_pressed`.
_HOP_KEYS = ("leg", "legIndex", "hop", "hopIndex")


def two_hops_at_once(messages: Iterable[dict[str, Any]]) -> str | None:
    """Why this surface offers fares for more than one hop, or None.

    A press settles one hop and spends the card it was on. So a card offering
    two hops can only ever answer one of them, and the other half — which the
    traveller was still reading — goes grey with it. It is also two sets of
    near-identical rows with nothing but a heading to say which is which, and a
    hop number in the press that nobody can see.

    Measured, this is what the model reached for every time the route had a way
    home: one card, outbound above, return below. The traveller pressed a fare,
    and which hop they had just chosen was a coin toss.

    Read off the presses rather than off the headings, because the press is
    where the hop is actually named.
    """
    hops: set[str] = set()
    for message in messages:
        update = message.get("updateComponents") or {}
        for node in update.get("components") or []:
            if not isinstance(node, dict):
                continue
            event = ((node.get("action") or {}).get("event")) or {}
            context = event.get("context")
            if not isinstance(context, dict):
                continue
            for key in _HOP_KEYS:
                value = context.get(key)
                if isinstance(value, (int, str)) and not isinstance(value, bool):
                    hops.add(f"{key}={value}")

    if len(hops) < 2:
        return None

    return (
        f"That surface offers fares for more than one hop ({', '.join(sorted(hops))}). "
        "A press settles one hop and spends the card, so the other hop's fares go grey "
        "unanswered and the traveller cannot tell which one they just chose. Draw one "
        "hop — the next one without a ticket — say which it is in the heading, and offer "
        "the hop after it once they have pressed."
    )


class AsksNothing(Exception):
    """A surface drawn on a turn that needed to ask, which asks for nothing."""


def asks_nothing(messages: Iterable[dict[str, Any]], missing: Iterable[str]) -> str | None:
    """Why this surface leaves the traveller with no way forward, or None.

    `wrong_controls` above catches a decision asked for in a control the answer
    cannot be right in. This catches the turn before that: a surface drawn while
    the trip is blocked, that does not ask for *any* of the things blocking it.

    Measured on an opening turn, which is where it happens. Told "plan me a trip
    from SFO to NYC", the model drew — in separate runs — six `StatTile`s and a
    `ProgressMeter`, and a `MapPreview` with six buttons. Both are handsome, both
    compiled, both validated, and neither contains anywhere to put a date. A
    progress meter before anything is decided is a bar at zero.

    Deliberately narrow, because most surfaces are not supposed to ask. Flight
    cards answer a question rather than posing one, and a turn that asks for
    *one* of three missing values is making progress. This fires only when the
    surface asks for none of them.
    """
    wanted = {str(field) for field in missing}
    if not wanted:
        return None

    asked: set[str] = set()
    for message in messages:
        update = message.get("updateComponents") or {}
        for node in update.get("components") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("component") or "") not in ASKING:
                continue
            for path in _bound_paths(node):
                asked.add(path.rsplit("/", 1)[-1])

    if asked & wanted:
        return None

    return (
        f"That surface asks for nothing the trip is waiting on. Still needed: "
        f"{', '.join(sorted(wanted))} — and nothing on screen is bound to any of "
        "them, so the traveller has no way to answer and the turn is spent. "
        "Draw the controls for the gaps, bound to `$/trip/…`, with one commit "
        "button. Summaries, maps and stat tiles are for a trip that exists."
    )
