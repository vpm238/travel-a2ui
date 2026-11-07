"""Whether a surface can be answered as drawn.

These are checks on what the model drew, reported back to it; the host never
changes the surface itself. Each one is about whether the traveller can give a
right answer at all, not about layout:

  - A trip field has a control that fits it (`data/controls.json`): a date is a
    date picker, a party is a counter, an airport is an airport picker. A date
    typed into a text box is a date someone can get wrong.
  - A surface that asks for a record field sends its data model
    (`sendDataModel`), or the answer never reaches the agent.
  - A party asked per hop is asked of every hop.

The same table is rendered into the prompt (`as_rules`), so the rule the model
is taught and the rule it is held to are the same rows.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .. import ROOT

_ROWS: list[dict[str, Any]] = json.loads((ROOT / "data" / "controls.json").read_text("utf-8"))["controls"]

#: Which controls may be bound to which trip field, by the field's name.
BY_FIELD: dict[str, tuple[str, ...]] = {row["field"]: tuple(row["allow"]) for row in _ROWS}
INSTEAD: dict[str, str] = {row["field"]: row["instead"] for row in _ROWS}
WHY: dict[str, str] = {row["field"]: row["why"] for row in _ROWS}

_CATALOG = json.loads((ROOT / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8"))

#: Components that take an answer: the catalog marks them `Checkable`.
ASKING: frozenset[str] = frozenset(
    name for name, entry in _CATALOG["components"].items() if "$defs/Checkable" in json.dumps(entry)
)

#: The properties an answer arrives in. A Button's `action` carries answers
#: rather than asking for one.
ANSWER_KEYS = frozenset({"value", "start", "end"})


def as_rules() -> str:
    """The table, as lines for the prompt."""
    return "\n".join(f"- **{row['field']}** → {row['instead']} — {row['why']}." for row in _ROWS)


def _asked(component: dict[str, Any]) -> list[str]:
    """The data paths this component asks the traveller to fill."""
    if str(component.get("component") or "") not in ASKING:
        return []
    paths = []
    for key in ANSWER_KEYS:
        value = component.get(key)
        if isinstance(value, dict) and isinstance(value.get("@path"), str):
            paths.append(value["@path"])
    return paths


def wrong_controls(components: Iterable[dict[str, Any]]) -> list[str]:
    said: list[str] = []
    for component in components:
        name = str(component.get("component") or "")
        for path in _asked(component):
            field = path.rsplit("/", 1)[-1]
            allowed = BY_FIELD.get(field)
            if allowed and name not in allowed:
                line = (
                    f"`{name}` is bound to `{path}`, which cannot be answered correctly "
                    f"in one: use {INSTEAD[field]} instead — {WHY[field]}."
                )
                if line not in said:
                    said.append(line)
    return said


def unsent(components: Iterable[dict[str, Any]], sends_data_model: bool) -> list[str]:
    """A surface that asks for record fields and never sends them."""
    if sends_data_model:
        return []
    asked = sorted({path for component in components for path in _asked(component) if path.startswith("/trip/")})
    if not asked:
        return []
    return [
        f"it asks for {', '.join(f'`{path}`' for path in asked)} but was created without "
        "sendDataModel, so the answers never reach you. Create it with "
        'surface("<id>", sendDataModel=true).'
    ]


def half_asked(components: Iterable[dict[str, Any]], legs: int = 0) -> list[str]:
    """A party asked of some hops and not the others.

    `legs` is how many hops the route has after the first. A surface either
    asks who is on every hop or on none of them.
    """
    if legs < 1:
        return []
    expected = ["/trip/travelers", *(f"/trip/legs/{index}/travelers" for index in range(legs))]
    asked = {path for component in components for path in _asked(component)}
    answered = [path for path in expected if path in asked]
    if not answered or len(answered) == len(expected):
        return []
    missing = [path for path in expected if path not in asked]
    return [
        f"it asks who is on {len(answered)} of the {len(expected)} hops and leaves out "
        f"{', '.join(f'`{path}`' for path in missing)}. Every hop has its own party; "
        "draw one `TravelerCounter` per hop, labelled by hop."
    ]


def problems(components: Iterable[dict[str, Any]], sends_data_model: bool, legs: int = 0) -> list[str]:
    """Everything that stops this surface being answered, as notes for the model."""
    components = list(components)
    return [
        *wrong_controls(components),
        *unsent(components, sends_data_model),
        *half_asked(components, legs),
    ]
