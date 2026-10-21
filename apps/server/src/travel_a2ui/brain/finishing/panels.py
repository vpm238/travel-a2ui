"""Keeping the panel's one interaction out of the conversation.

A standing panel is the record of what has been decided, and its only
interaction is Change — which does not answer anything, it reopens a decision
in the conversation. A `change` button anywhere else is therefore a button that
reopens a question the traveller is in the middle of answering, so it is taken
back off before the surface goes out.
"""

from __future__ import annotations

from typing import Any, Iterable

from .seeding import trip_updates
from .shared import STANDING_SURFACES, A2uiMessage, _event_of

# --------------------------------------------------------------------------
# Keeping the panel's one interaction out of the conversation
# --------------------------------------------------------------------------


def panel_events(trip: dict[str, Any]) -> list[A2uiMessage]:
    """The standing panels, brought up to date, as events for any transport.

    Every door does this at the end of a turn and each used to do it itself: the
    same loop over `STANDING_SURFACES`, the same `trip_updates`, the same event
    shape, written twice. That is not a lot of code, and duplication of exactly
    this size is how the doors drift — the typed path grew a per-turn surface id
    and a departure-airport hint that the voice path did not, for no reason
    except that nobody was looking at both.

    Returned rather than yielded because one caller is a synchronous generator
    and the other is inside a websocket pump; a list is the shape both can use
    without either pretending to be the other.
    """
    events: list[A2uiMessage] = []
    for surface_id in STANDING_SURFACES:
        updates = trip_updates(surface_id, trip)
        if updates:
            events.append(
                {
                    "type": "ui",
                    "surfaceId": surface_id,
                    "messages": updates,
                    "done": True,
                }
            )
    return events


def strip_panel_actions(
    messages: list[A2uiMessage], standing_surfaces: Iterable[str] = STANDING_SURFACES
) -> list[A2uiMessage]:
    """Removes a `change` action from anywhere that is not a standing panel.

    The split this whole app is built on is that the conversation is where you
    decide and the panel is where decisions live — so the panel is read-only
    except for one thing, a `change` that re-opens a settled decision back in
    the conversation. That direction is enforced: editors drawn on a panel are
    ignored by the host.

    The other direction was only asked for, and a live run showed it being
    ignored: under a card asking for dates, the model drew the panel's own
    record again, so the same decision had two Change buttons on screen at once,
    one of them inside the surface the traveller was still filling in.
    """
    standing = set(standing_surfaces)

    def prune(surface_id: str, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if surface_id in standing:
            return components

        dropped = {
            str(node["id"])
            for node in components
            if (_event_of(node) or {}).get("name") == "change"
        }
        if not dropped:
            return components

        # Repeated, because dropping a button can empty the row that held it,
        # and an empty row is a gap on screen that nothing explains.
        kept = [node for node in components if str(node.get("id")) not in dropped]
        for _ in range(5):
            changed = False
            for node in kept:
                children = node.get("children")
                if not isinstance(children, list):
                    continue
                filtered = [
                    child
                    for child in children
                    if not isinstance(child, str) or child not in dropped
                ]
                if len(filtered) != len(children):
                    node["children"] = filtered
                    changed = True
                # A container that only ever held the button, and is not root.
                if (
                    not filtered
                    and node.get("id") != "root"
                    and str(node.get("id")) not in dropped
                ):
                    dropped.add(str(node.get("id")))
                    changed = True
            if not changed:
                break
            kept = [node for node in kept if str(node.get("id")) not in dropped]
        return kept

    for message in messages:
        if "createSurface" in message:
            surface = message["createSurface"]
            if surface.get("components"):
                surface["components"] = prune(surface["surfaceId"], surface["components"])
        elif "updateComponents" in message:
            update = message["updateComponents"]
            update["components"] = prune(update["surfaceId"], update.get("components") or [])

    return messages
