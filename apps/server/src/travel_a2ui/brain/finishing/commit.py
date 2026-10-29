"""One surface, one button, everything on it sent together.

The distinction the whole interaction model rests on: dragging a slider or
typing a name is somebody still answering, and only a button means they are
done. Which means the button has to carry every value on its surface — if it
carries only what the model remembered to bind to it, the traveller sets three
things, presses once, and two of them are lost.

So the host gathers every editable path on the surface and puts them on the
commit button itself. Per surface, which is what makes two composed blocks
still answer with one press.
"""

from __future__ import annotations

from typing import Any

from ..bindings import bind, is_binding, path_of
from .shared import (
    VALUE_EDITORS,
    A2uiMessage,
    _bound_paths,
    _components_in,
    _event_of,
    _root_of,
)

def _key_for(path: str, taken: set[str]) -> str:
    """`/trip/startDate` → `startDate`, kept unique against what is already there."""
    segments = [part for part in path.split("/") if part]
    base = segments[-1] if segments else "value"
    if base not in taken:
        return base
    # `/trip/origin` colliding with `/leg/origin` becomes `tripOrigin`.
    for depth in range(2, len(segments) + 1):
        parts = segments[-depth:]
        candidate = parts[0] + "".join(part[0].upper() + part[1:] for part in parts[1:])
        if candidate not in taken:
            return candidate
    number = 2
    while f"{base}{number}" in taken:
        number += 1
    return f"{base}{number}"


def bind_commit_context(
    messages: list[A2uiMessage], carried: dict[str, dict[str, None]] | None = None
) -> list[A2uiMessage]:
    """Adds every editable path on a surface to that surface's commit buttons.

    A2UI already has the canonical mechanism for submitting a form: a button
    whose action declares a *context* of bound paths, which every renderer
    resolves against the data model and posts back. The catch is that it depends
    on the model remembering to bind every field it asked about. Forget one and
    the traveller's answer is silently dropped — the hardest class of bug to
    see, because the surface looks right and the trip is merely wrong.

    So this closes it server-side. Paths the model already bound are left
    exactly as they are, under whatever key it chose: it names things better
    than an algorithm splitting on slashes, and a context that changes shape
    between turns is worse than an ugly key.
    """
    # Components arrive across several messages for one surface, and a button
    # can be created before the field it must carry. So: collect per surface.
    #
    # A dict rather than a set, and the reason is not style. These paths become
    # the keys of the button's context in iteration order, and `_key_for`
    # resolves a collision by qualifying whichever path it reaches *second* —
    # so an unordered set produces `origin`/`legOrigin` one run and
    # `legOrigin`/`origin` the next. The payload a client receives would then
    # change shape between deploys for no reason anybody could see.
    # `carried` makes this span a whole turn rather than one block. A turn that
    # writes two blocks composes them onto one surface, and its single button
    # has to carry what *both* asked — otherwise pressing it sends the second
    # block's answers and silently drops the first's, which is the same
    # forgotten-field bug this function exists to close, one level up.
    editable: dict[str, dict[str, None]] = carried if carried is not None else {}
    buttons: dict[str, list[dict[str, Any]]] = {}

    for message in messages:
        found = _components_in(message)
        if not found:
            continue
        surface_id, components = found
        for node in components:
            if node.get("component") in VALUE_EDITORS:
                paths = editable.setdefault(surface_id, {})
                for path in _bound_paths(node):
                    paths.setdefault(path, None)
            if _event_of(node):
                buttons.setdefault(surface_id, []).append(node)

    # A surface of editors with nothing to press is a dead end: the traveller
    # has composed an answer and there is no way to send it. The skill says to
    # draw the button, and mostly it does; this is the case where it did not.
    #
    # Adding one here rather than in the browser is what keeps the guarantee
    # portable. The old fix was a bar the React app drew for itself, which meant
    # the Flutter client shipped the dead end.
    for surface_id, paths in editable.items():
        if not paths or buttons.get(surface_id):
            continue

        # The components are wherever they actually are: `createSurface` carries
        # them in v1.0 and often nothing in v0.9.1, where they arrive in a
        # following `updateComponents`. Taking the first message for the surface
        # would find an empty one and give up.
        components = None
        root = None
        for message in messages:
            found = _components_in(message)
            if not found or found[0] != surface_id or not found[1]:
                continue
            candidate = found[1]
            maybe_root = _root_of(candidate)
            if maybe_root is not None and isinstance(maybe_root.get("children"), list):
                components = candidate
                root = maybe_root
        if components is None or root is None:
            continue

        commit = {
            "id": "__commit",
            "component": "Button",
            "label": "Send",
            "action": {"event": {"name": "commit_surface", "context": {}}},
        }
        components.append(commit)
        root["children"].append(commit["id"])
        buttons[surface_id] = [commit]

    for surface_id, paths in editable.items():
        if not paths:
            continue
        for node in buttons.get(surface_id, []):
            event = _event_of(node)
            if event is None:
                continue

            context = event.get("context")
            existing = dict(context) if isinstance(context, dict) else {}

            already_bound = {
                path_of(value) for value in existing.values() if is_binding(value)
            }

            keys = set(existing)
            for path in paths:
                if path in already_bound:
                    continue
                key = _key_for(path, keys)
                keys.add(key)
                existing[key] = bind(path)

            event["context"] = existing

    return messages
