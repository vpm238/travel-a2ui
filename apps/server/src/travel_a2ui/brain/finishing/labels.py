"""Night counts the model wrote as text, bound to the count instead.

`nightsLabel="6 nights"` is right when it is written and wrong the moment
somebody moves a date, because it is a literal in a tree the renderer will keep
drawing. Bound to the path the count derives from, it moves when the dates do,
with no model in the loop.
"""

from __future__ import annotations

import re
from typing import Any

from ..bindings import is_binding, path_of
from ..spoken import label_for
from .shared import A2uiMessage, _components_in

# --------------------------------------------------------------------------
# Night counts the model wrote as text
# --------------------------------------------------------------------------

_COUNT_OF_NIGHTS = re.compile(r"^\d+\s*nights?$", re.IGNORECASE)


def _is_path_binding(value: Any) -> bool:
    return is_binding(value)


def _is_count_of_nights(value: Any) -> bool:
    """True for a label that is only trying to say how many nights it is.

    Missing entirely, or a bare count the model worked out this turn. A template
    is left alone — that is the right answer already, and rewriting it would
    throw away wording the model chose.
    """
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if text == "":
        return True
    if "${" in text:
        return False
    return bool(_COUNT_OF_NIGHTS.match(text))


def bind_derived_labels(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """Night counts the model wrote as text, replaced by the call that computes them.

    The interesting failure is not the one that looks broken. A model that
    writes `nightsLabel="7 nights"` produces a label that is correct in the
    screenshot and a lie the moment the traveller moves a date — and nothing
    downstream ever notices, because a string is a string.

    A2UI already has the answer: a `formatString` whose template carries
    `${calcNights(...)}` is resolved by every renderer against the live data
    model, so the label recomputes as the picker moves with no turn in between.
    """
    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        for node in found[1]:
            if node.get("component") != "DateRangePicker":
                continue
            start, end = node.get("start"), node.get("end")
            # Only when both ends are bound: a picker holding literal dates has
            # nothing to recompute against.
            if not _is_path_binding(start) or not _is_path_binding(end):
                continue
            if not _is_count_of_nights(node.get("nightsLabel")):
                continue
            node["nightsLabel"] = {
                "call": "formatString",
                "args": {
                    "value": (
                        "${calcNights(start:${" + (path_of(start) or "") + "}, "
                        "end:${" + (path_of(end) or "") + "})} nights"
                    )
                },
            }
    return messages


# --------------------------------------------------------------------------
# Cards the model drew and did not name
# --------------------------------------------------------------------------


def name_pressable_cards(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """A fare or a stay with no `accessibility.label`, named from its own fields.

    The brief asks the agent to name its cards, and asking is as far as a brief
    can go: a model that skips the house rule costs a traveller using a screen
    reader the whole card. Measured on the typed door, against a walkthrough
    that drew sixteen fares and three stays: nought named.

    So the host reads the fields back. Not a decision about what to show — the
    agent chose the card, its content and its surface, and `brain/spoken.py`
    turns the properties it already set into the sentence those properties
    read as. The same reasoning as the night counts above, and the same shape:
    look at what the model wrote, and improve it only where it is strictly
    better.

    Never overwrites a label the agent wrote. A model that named a card knows
    something this does not — which leg it is, why this one is the recommended
    one — and the point of the house rule is to let it say so.
    """
    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        for node in found[1]:
            block = node.get("accessibility")
            if isinstance(block, dict) and str(block.get("label") or "").strip():
                continue
            if is_binding(block) or (block is not None and not isinstance(block, dict)):
                # Something the agent meant as a whole-block binding, or a
                # value this does not understand. Left alone either way.
                continue
            reads = label_for(str(node.get("component") or ""), node)
            if not reads:
                continue
            node["accessibility"] = {**(block or {}), "label": reads}
    return messages
