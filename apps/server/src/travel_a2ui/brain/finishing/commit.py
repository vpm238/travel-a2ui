"""One surface, one button, and every value on it sent with the press.

The distinction the whole interaction model rests on: dragging a slider or
typing a name is somebody still answering, and only a button means they are
done. So the press has to carry every value on its surface — if it carries only
what the model remembered to bind to it, the traveller sets three things,
presses once, and two of them are lost.

That used to be done here by hand: a pass walked every editor on a surface,
gathered the paths it was bound to, and wrote them all into the commit button's
action context. It worked, and it was an application protocol layered over
A2UI — paths inside templates and macro output could slip past it, and a second
renderer had no idea the context it posted had been assembled for it.

A2UI has the mechanism already. `createSurface.sendDataModel: true` asks the
renderer to send the surface's whole data model with every action it reports,
so the trip arrives exact, every field, with nothing to gather. The server reads
it (`from_surface` in `doors/interactions/turn.py`). What is left here is the
part the protocol cannot do for us: a surface of editors with no button at all
is a form nobody can submit, so it gets one.
"""

from __future__ import annotations

from typing import Any

from .shared import VALUE_EDITORS, A2uiMessage, _components_in, _event_of, _root_of


def declare_send_data_model(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """Every surface created asks for its data model back with each action."""
    for message in messages:
        body = message.get("createSurface")
        if isinstance(body, dict):
            body["sendDataModel"] = True
    return messages


def ensure_commit_button(
    messages: list[A2uiMessage], carried: dict[str, dict[str, None]] | None = None
) -> list[A2uiMessage]:
    """Gives a surface of editors with nothing to press a button to press.

    The skill says to draw the button, and mostly it does; this is the case where
    it did not. Here rather than in the browser so the guarantee is portable —
    the old fix was a bar the React app drew for itself, and the Flutter client
    shipped the dead end.

    `carried` remembers, across the blocks of one turn, which surfaces have
    editors, so a button in a later block answers for editors in an earlier one.
    """
    editable: dict[str, dict[str, None]] = carried if carried is not None else {}
    buttons: dict[str, bool] = {}

    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        surface_id, components = found
        for node in components:
            if node.get("component") in VALUE_EDITORS:
                editable.setdefault(surface_id, {})[node.get("id", "")] = None
            if _event_of(node):
                buttons[surface_id] = True

    for surface_id, editors in editable.items():
        if not editors or buttons.get(surface_id):
            continue

        # The components are wherever they actually are: the last message for
        # this surface that has a root with children.
        components = None
        root = None
        for message in messages:
            found = _components_in(message)
            if not found or found[0] != surface_id or not found[1]:
                continue
            maybe_root = _root_of(found[1])
            if maybe_root is not None and isinstance(maybe_root.get("children"), list):
                components = found[1]
                root = maybe_root
        if components is None or root is None:
            continue

        # A face, then the button that points at it: a `Button` has no `label`,
        # its face is the component its required `child` names.
        face: dict[str, Any] = {"id": "__commit_label", "component": "Text", "text": "Send"}
        commit: dict[str, Any] = {
            "id": "__commit",
            "component": "Button",
            "child": face["id"],
            "variant": "primary",
            "action": {"event": {"name": "commit_surface", "context": {}}},
        }
        components.extend([face, commit])
        root["children"].append(commit["id"])
        buttons[surface_id] = True

    return messages
