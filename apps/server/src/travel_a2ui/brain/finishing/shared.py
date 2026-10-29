"""What every pass needs to know about an A2UI message.

A pass over a surface is always the same shape — find the components, find the
one called `root`, find the action on a button — and five files doing that
five ways is five places for "the renderer draws `root`" to drift. So the
reading is here, once, and the passes are about what they change.
"""

from __future__ import annotations

from typing import Any

from ..bindings import _READ_PATH, is_binding, path_of
from ..catalog import PROTOCOL_VERSION

A2uiMessage = dict[str, Any]

#: The version stamped on every message this server composes itself.
#:
#: Taken from the catalog rather than written here, so the host's own messages
#: and the compiler's agree by construction. They did not have to: a pass that
#: stamps 0.9 on a message beside a 1.0 surface produces a payload no renderer
#: accepts as a whole, and the failure is per-message rather than obvious.
VERSION = PROTOCOL_VERSION

#: The surfaces that show current state rather than a moment in the past.
#:
#: Both stay live: a value the traveller sets anywhere reaches them as an
#: `updateDataModel`, with no model in the path, so a built home screen keeps up
#: with the trip without costing a turn.
STANDING_SURFACES = ("sidebar", "home")

#: The ones a chat turn may rebuild, which is not the same list.
#:
#: A home screen is a summary of a trip, and a chat turn is where a trip is
#: still being decided — so rebuilding it mid-conversation composes a dashboard
#: of a thing that does not exist yet. It also cost a second model call on every
#: shape change, in parallel with the sidebar and for nobody: the traveller is
#: looking at the conversation.
#:
#: Worse than the latency, it put `StatTile`, `ProgressMeter` and `MapPreview`
#: in front of the model on turns that needed a date picker, and measurably that
#: is what it reached for. The home screen is built when somebody asks for it,
#: from the transcript and the trip, which is the only point at which there is
#: anything to summarise.
REBUILT_IN_A_TURN = ("sidebar",)

#: Components that compose an answer rather than commit one.
#:
#: The distinction is the whole interaction model: dragging a slider or typing a
#: name is someone still answering, and only a button means they are done. These
#: are the components whose bound paths a commit button must therefore carry.
VALUE_EDITORS = frozenset(
    {
        "TextField",
        "CheckBox",
        "ChoicePicker",
        "Slider",
        "DateTimeInput",
        "DateRangePicker",
        "TravelerCounter",
    }
)


# --------------------------------------------------------------------------
# Making "one surface, one button, everything sent together" a guarantee
# --------------------------------------------------------------------------


def _bound_paths(node: dict[str, Any]) -> list[str]:
    """Every `{path}` binding anywhere inside a component's properties."""
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        # A child-list template's path points at a collection to repeat over,
        # not at a value someone edited — which `is_binding` knows.
        if is_binding(value):
            found.append(path_of(value))
        for key, nested in value.items():
            if key in _READ_PATH:
                continue
            walk(nested)

    for key, value in node.items():
        if key in ("id", "component"):
            continue
        walk(value)
    return found


def _named_root(components: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The component actually called `root`, and nothing else.

    For callers that are watching a block *arrive*. A block streams: the
    compiler sends the components defined so far, and the one called `root` is
    by definition the last line of the block, so every message before the final
    one has no root in it at all. Guessing one from the structure — see
    `_root_of`, which does — answers "the component nothing claims as a child",
    and in a half-written block that is simply the first component.

    That is not hypothetical. At 1.0 a flight list streamed as `heading`, then
    `heading, f1`, then `heading, f1, f2` … and the guess made `heading` the
    root of a block whose real root arrived four messages later. Both were then
    composed under a new `root` — `children: ["heading", "root"]`, a root
    containing itself — and the four fares, claimed by nothing, vanished. The
    traveller saw a heading over an empty card.
    """
    for node in components:
        if node.get("id") == "root":
            return node
    return None


def _root_of(components: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The container everything else hangs off.

    `root` by convention — the Express examples and the generated skill both use
    it — and otherwise the one component nothing else lists as a child, which is
    the same thing said structurally.
    """
    for node in components:
        if node.get("id") == "root":
            return node
    claimed: set[str] = set()
    for node in components:
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, str):
                    claimed.add(child)
    for node in components:
        if node.get("id") not in claimed:
            return node
    return None


def _event_of(node: dict[str, Any]) -> dict[str, Any] | None:
    """The `action.event` object on a component, when it has one."""
    action = node.get("action")
    if not isinstance(action, dict):
        return None
    event = action.get("event")
    return event if isinstance(event, dict) else None


def _components_in(message: A2uiMessage) -> tuple[str, list[dict[str, Any]]] | None:
    if "createSurface" in message:
        surface = message["createSurface"]
        return surface["surfaceId"], surface.get("components") or []
    if "updateComponents" in message:
        update = message["updateComponents"]
        return update["surfaceId"], update.get("components") or []
    return None
