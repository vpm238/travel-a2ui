"""What every pass needs to know about an A2UI message.

A pass over a surface is always the same shape — find the components, find the
one called `root`, find the action on a button — and five files doing that
five ways is five places for "the renderer draws `root`" to drift. So the
reading is here, once, and the passes are about what they change.
"""

from __future__ import annotations

from typing import Any

A2uiMessage = dict[str, Any]

VERSION = "v0.9.1"

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
        # A child-list template's `path` points at a collection to repeat over,
        # not at a value someone edited.
        if isinstance(value.get("path"), str) and "componentId" not in value:
            found.append(value["path"])
        for key, nested in value.items():
            if key == "path":
                continue
            walk(nested)

    for key, value in node.items():
        if key in ("id", "component"):
            continue
        walk(value)
    return found


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
