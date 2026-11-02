"""The heading a turn writes above a macro that already draws it.

`Flights()` takes a heading and draws it, which is the point of passing one.
The agent writes one anyway:

    heading = Text("Outbound · JFK → MAD · Mon 12 Apr")
    fares = Flights("Outbound · JFK → MAD · Mon 12 Apr", "/trip/selectedFlight")
    root = Column([heading, fares])

Both are correct in isolation and together they put the same line on screen
twice. Measured over a journey, on every turn that drew a list of fares — and
on the return as well, so a trip ended up with four duplicated headings.

Fixed here rather than in the brief because this is the renderer's contract
and not the flow's — the same line `on_its_own_surface` and `strip_panel_actions`
sit on. It says nothing about what a turn may draw or what it should say; it
says a surface may not show one heading twice. The alternative was a fourth
rewrite of "do not write a heading above it", and this feature has a long
record of those not holding.

Deliberately narrow. It fires only when a container holds a `Text` whose
literal text appears again, word for word, inside a sibling of that same
container — which is exactly the shape above and almost nothing else. A
repeated label that is *not* nested inside a sibling is left alone, a bound
heading is left alone because two bindings are not known to be equal until they
resolve, and the copy that is kept is the one inside the macro, next to the list
it is the heading for.
"""

from __future__ import annotations

from typing import Any

from .shared import A2uiMessage, _components_in


def _text_of(component: Any) -> str:
    """A component's heading text, if it is a `Text` with a literal in it."""
    if not isinstance(component, dict) or component.get("component") != "Text":
        return ""
    text = component.get("text")
    return text.strip() if isinstance(text, str) else ""


def _children_of(component: Any) -> list[str]:
    """The component ids a container names, when it names a plain list of them."""
    if not isinstance(component, dict):
        return []
    children = component.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, str)]


def drop_repeated_headings(messages: list[A2uiMessage]) -> list[A2uiMessage]:
    """Removes a heading a sibling already draws. See the module docstring."""
    for message in messages:
        where = _components_in(message)
        if not where:
            continue
        # `(surfaceId, components)`, not a bare list.
        _, found = where
        by_id = {
            component["id"]: component
            for component in found
            if isinstance(component, dict) and isinstance(component.get("id"), str)
        }

        def texts_under(component_id: str, depth: int = 0) -> set[str]:
            """Every literal heading at or below this component."""
            # Bounded, because a malformed tree can name itself.
            if depth > 6 or component_id not in by_id:
                return set()
            component = by_id[component_id]
            here = {_text_of(component)} - {""}
            for child in _children_of(component):
                here |= texts_under(child, depth + 1)
            return here

        for container in found:
            children = _children_of(container)
            if len(children) < 2:
                continue
            # What each sibling draws, minus itself.
            nested = {
                child: texts_under(child) - ({_text_of(by_id.get(child))} - {""})
                for child in children
            }
            keep: list[str] = []
            for child in children:
                heading = _text_of(by_id.get(child))
                if heading and any(
                    heading in nested[other] for other in children if other != child
                ):
                    # A sibling already draws this exact line, next to the thing
                    # it is a heading for. Drop this one.
                    continue
                keep.append(child)
            if len(keep) != len(children):
                container["children"] = keep
    return messages
