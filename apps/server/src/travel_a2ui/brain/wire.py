"""Where the components in a message are, whichever message carries them.

In 0.9 a surface arrived in two messages: `createSurface` named it, and a
following `updateComponents` filled it. In 1.0 the create carries its own
components — and its data model — so a whole surface is one message.

That is the single best thing about the upgrade (one round trip instead of
two, and no window in which a layout exists with nothing in it), and it is
also the change most likely to be missed, because nothing fails loudly. A pass
that scans only `updateComponents` does not crash on a 1.0 payload: it finds no
components, concludes there is nothing to check or bind, and returns the
surface untouched. Every check in this package then passes by vacancy.

Which is exactly what happened here while this was being written: the control
check stopped refusing a date in a text box, and said nothing about it.

So the question "which components does this message carry?" is asked in one
place, by every pass that asks it.
"""

from __future__ import annotations

from typing import Any

A2uiMessage = dict[str, Any]

#: The two messages that can carry components, newest spelling first.
CARRIERS = ("createSurface", "updateComponents")


def components_in(message: Any) -> tuple[str, list[dict[str, Any]]] | None:
    """The surface this message addresses and the components it carries.

    None when the message carries no components at all — a data model update,
    a delete, a function call — which a caller should skip rather than treat
    as an empty surface.
    """
    if not isinstance(message, dict):
        return None
    for key in CARRIERS:
        body = message.get(key)
        if isinstance(body, dict):
            surface_id = body.get("surfaceId")
            if isinstance(surface_id, str):
                return surface_id, list(body.get("components") or [])
    return None


def components_of(message: Any) -> list[dict[str, Any]]:
    """Just the components, for the callers that do not need the surface.

    Tolerant of a message that names no surface, which `components_in` is not:
    a check that only reads components has no use for the id, and a test that
    builds one message by hand should not have to invent one to be understood.
    """
    if not isinstance(message, dict):
        return []
    for key in CARRIERS:
        body = message.get(key)
        if isinstance(body, dict):
            return [node for node in (body.get("components") or []) if isinstance(node, dict)]
    return []
