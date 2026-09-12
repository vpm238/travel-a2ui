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
