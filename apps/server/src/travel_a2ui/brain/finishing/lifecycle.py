"""Each surface created once, and nothing sent to a surface that does not exist.

A2UI 1.0 gives a surface a lifecycle: `createSurface` once, then
`updateComponents` and `updateDataModel` against it, until `deleteSurface`. A
conformant renderer — `@a2ui/web_core`'s `MessageProcessor`, the SDK's own
`RendererState` — rejects the two things this server used to do every turn:

  - `createSurface` for a surface that already exists. Every panel redraw did
    it, and so did the agent's card landing on the card the host pre-drew while
    a lookup ran. A strict renderer drops the second create, which is the
    *real* card: the traveller is left looking at the placeholder.
  - `updateDataModel` for a surface that was never created. The standing
    panels were sent the trip's values at the end of every turn whether or not
    anybody had drawn them — 128 of them across the five turns of the sample.

The app's own store tolerated both by creating on update and replacing on
create, which is precisely the behaviour a second renderer would have to be
taught. So the stream is made conformant here, at the door, for every
transport, rather than relying on every client to be lenient.

**Which surfaces exist is the client's to say.** It is the only party that
knows what it holds: a stream it aborted never delivered the create the server
sent, and a page that opened on the recorded sample holds a panel this server
never drew. A request carries the ids (`client.surfaces`); without them this
falls back to what the server sent this conversation.

Data for a surface that does not exist *yet* is held rather than dropped, and
delivered right after that surface's create. A lookup files its rows while it
runs — at `/flights` on the card it will feed — and when the agent asked for no
placeholder, the card itself only arrives with the block written after the
lookup. Dropped, those rows were gone, and the card painted its heading over an
empty list in every renderer.

A repeated create becomes `updateComponents` with the same components — the
new `root` takes over, so the surface shows exactly what the create described
— plus one `updateDataModel` per top-level key of its data model. Per key, not
one write at `/`: the host files lookup rows at `/flights` and `/hotels`, and
replacing the root would wipe the rows the new card is about to read.
"""

from __future__ import annotations

from typing import Any, Iterable

from .shared import A2uiMessage


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _top_key(path: Any) -> str | None:
    """The data model key a JSON pointer starts at, unescaped; None for the root."""
    if not isinstance(path, str) or path in ("", "/"):
        return None
    head = path.lstrip("/").split("/", 1)[0]
    return head.replace("~1", "/").replace("~0", "~")


def _surface_of(message: A2uiMessage) -> str | None:
    for kind in ("createSurface", "updateComponents", "updateDataModel", "deleteSurface"):
        body = message.get(kind)
        if isinstance(body, dict):
            surface = body.get("surfaceId")
            return surface if isinstance(surface, str) else None
    return None


class SurfaceLifecycle:
    """What the client holds, and the messages rewritten to respect it."""

    def __init__(self, held: Iterable[str] = ()) -> None:
        self.held: set[str] = {surface for surface in held if isinstance(surface, str)}
        #: Data for surfaces not created yet, in arrival order, by surface.
        self.waiting: dict[str, list[A2uiMessage]] = {}

    def messages(self, messages: list[A2uiMessage]) -> list[A2uiMessage]:
        out: list[A2uiMessage] = []
        for message in messages:
            surface = _surface_of(message)
            if surface is None:
                out.append(message)
                continue
            version = message.get("version")

            if "createSurface" in message:
                if surface not in self.held:
                    self.held.add(surface)
                    out.append(message)
                    # After the create, and only where the create brings nothing
                    # of its own: a key it carries a value for is newer than
                    # anything held from before it existed.
                    seeded = message["createSurface"].get("dataModel")
                    seeded = seeded if isinstance(seeded, dict) else {}
                    for held in self.waiting.pop(surface, []):
                        key = _top_key(held["updateDataModel"].get("path"))
                        if key is None or seeded.get(key) is None:
                            out.append(held)
                    continue
                body = message["createSurface"]
                components = body.get("components")
                if components:
                    out.append(
                        {
                            "version": version,
                            "updateComponents": {"surfaceId": surface, "components": components},
                        }
                    )
                data = body.get("dataModel")
                if isinstance(data, dict):
                    for key, value in data.items():
                        out.append(
                            {
                                "version": version,
                                "updateDataModel": {
                                    "surfaceId": surface,
                                    "path": f"/{_escape(str(key))}",
                                    "value": value,
                                },
                            }
                        )
                continue

            if "deleteSurface" in message:
                if surface in self.held:
                    self.held.discard(surface)
                    out.append(message)
                continue

            # An update. To a surface nobody has created it has nothing to
            # update; when that surface is created, its create carries the
            # same values, seeded from the trip.
            if surface in self.held:
                out.append(message)
            elif "updateDataModel" in message:
                self.waiting.setdefault(surface, []).append(message)
        return out

    def event(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """A door event with its messages made conformant, or None if none are left."""
        if event.get("type") != "ui" or not isinstance(event.get("messages"), list):
            return event
        if not event["messages"]:
            return event  # nothing to make conformant, and nothing removed
        kept = self.messages(event["messages"])
        if not kept:
            return None
        return {**event, "messages": kept}


def held_by_client(body: dict[str, Any]) -> list[str] | None:
    """The surface ids a request says its client holds, if it says."""
    client = body.get("client")
    if not isinstance(client, dict):
        return None
    surfaces = client.get("surfaces")
    if not isinstance(surfaces, list):
        return None
    return [surface for surface in surfaces if isinstance(surface, str)]
