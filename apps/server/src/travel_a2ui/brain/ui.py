"""What the model writes, read by the A2UI SDK, and what the renderer receives.

A conversation keeps one `Canvas`, which holds two `RendererState`s:

    drafted   the surfaces as the model wrote them, macros included, over the
              catalogs the model was offered. The SDK processor checks every
              block against it, so `surface("sidebar", update=true)` in turn
              nine is checked against what turn two drew there.
    wire      the same surfaces as the renderer holds them: macros expanded,
              over the whole travel catalog. Every message is applied here
              before it is sent, so nothing leaves the server that a renderer
              would reject.

A turn reads the model through a `Drawing`, which turns the processor's stream
parts into events for the transport:

    ("text", prose)                   prose for the transcript
    ("ui", surface_id, messages)      A2UI for the renderer, already validated
    ("rejected", reason, source)      a block that was refused, for the model
    ("advice", note)                  a surface that renders but cannot be
                                      answered as drawn, for the model

The host never rewrites what the model wrote. Its part is data: when a surface
binds a root the host owns (`brain/data.py`), the host sends that root's value
as an ordinary `updateDataModel`, and sends it again whenever it changes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from a2ui.parser import A2uiPart, ErrorPart, TextPart, to_message_dicts
from a2ui.processor import A2uiRequestProcessor

from . import controls
from .catalog import PROTOCOL_VERSION, negotiate, processor_for, renderer_state
from .data import BY_HOP, LOOKUP_ROOTS, components_of, roots_bound, trip_fields_bound
from .macros import EXPANDER, MACRO_NAMES

#: Surfaces that last the whole conversation.
STANDING_SURFACES = ("sidebar", "home")

#: The values a surface may bind, by root, for one surface id.
Values = Callable[[str], dict[str, Any]]


def delete_surface(surface_id: str) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "deleteSurface": {"surfaceId": surface_id}}


def update_data(surface_id: str, path: str, value: Any) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value},
    }


def surface_of(message: dict[str, Any]) -> str | None:
    for body in message.values():
        if isinstance(body, dict) and isinstance(body.get("surfaceId"), str):
            return body["surfaceId"]
    return None


def _stamp(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _hops_changed(reported: list[Any], held: Any) -> list[dict[str, Any]] | None:
    """The fields of each hop the traveller changed, by index; None for none.

    Hop by hop and field by field, so a counter for one hop's party reports
    that party and nothing else; an untouched hop reports `{}`.
    """
    before = held if isinstance(held, list) else []
    out: list[dict[str, Any]] = []
    for index, hop in enumerate(reported):
        was = before[index] if index < len(before) and isinstance(before[index], dict) else {}
        hop = hop if isinstance(hop, dict) else {}
        out.append({key: value for key, value in hop.items() if _stamp(value) != _stamp(was.get(key))})
    return out if any(out) else None


def _hops_with_proposals(record: list[Any], held: Any, proposed: dict[str, str]) -> list[Any]:
    """The record's hops, keeping each field the model suggested a value for.

    A suggestion stands until the record's own value for that field moves, as
    for any other field (see `Canvas._record`).
    """
    shown = held if isinstance(held, list) else []
    out: list[Any] = []
    for index, hop in enumerate(record):
        hop = dict(hop) if isinstance(hop, dict) else {}
        had = shown[index] if index < len(shown) and isinstance(shown[index], dict) else {}
        for key in [k for k in proposed if k.startswith(f"legs/{index}/")]:
            field_name = key.rsplit("/", 1)[-1]
            ours = _stamp(hop.get(field_name))
            if proposed[key] in ("", ours) and field_name in had:
                proposed[key] = ours
                hop[field_name] = had[field_name]
            else:
                del proposed[key]
        out.append(hop)
    return out


@dataclass
class Canvas:
    """The surfaces one conversation's renderer holds, and the data they bind."""

    #: The renderer's `a2uiRendererCapabilities`, which choose the catalog.
    capabilities: Any = None
    drafted: Any = None
    wire: Any = field(default_factory=renderer_state)
    #: The host roots each surface binds.
    binds: dict[str, set[str]] = field(default_factory=dict)
    #: The record fields each surface binds, or `"*"` for all of them.
    trip_fields: dict[str, set[str]] = field(default_factory=dict)
    #: Record fields the model proposed in a surface's own data model, with
    #: the record's value at the time. Left alone until the record moves.
    proposed: dict[str, dict[str, str]] = field(default_factory=dict)
    #: The rows the latest lookups returned (`/flights`, `/fares/N`, …), kept
    #: for the conversation: a card drawn a turn after its search still binds
    #: them. Offered only to the surface being drawn, so earlier cards keep
    #: the rows they were drawn with.
    lookups: dict[str, Any] = field(default_factory=dict)
    #: The cards this turn has drawn or updated: the ones `lookups` go to.
    this_turn: set[str] = field(default_factory=set)
    _processors: dict[str, A2uiRequestProcessor] = field(default_factory=dict)

    # -- the processor --------------------------------------------------------

    def negotiate(self, capabilities: Any) -> str | None:
        """Adopts the renderer's capabilities, if they changed.

        Returns why not when the renderer supports none of this agent's
        catalogs (the SDK's `resolve_catalogs` refuses them), and keeps the
        capabilities it had: drawing in a catalog the renderer cannot show is
        the one thing a turn must not do.
        """
        if capabilities is None or _stamp(capabilities) == _stamp(self.capabilities):
            return None
        try:
            negotiate(capabilities)
        except Exception as error:  # noqa: BLE001 - the SDK's A2uiCatalogError, reported
            return f"The renderer supports none of this agent's catalogs: {error}"
        self.capabilities = capabilities
        self._processors.clear()
        return None

    def processor(self, surface_id: str) -> A2uiRequestProcessor:
        """The processor for a turn that draws into `surface_id` by default."""
        found = self._processors.get(surface_id)
        if found is None:
            found = processor_for(surface_id, self.capabilities)
            if len(self._processors) > 8:
                self._processors.clear()
            self._processors[surface_id] = found
        if self.drafted is None or not found.accepts_state(self.drafted):
            self.drafted = found.create_state()
        return found

    # -- what the renderer holds ---------------------------------------------

    @property
    def surfaces(self) -> set[str]:
        return set(self.wire.surface_ids)

    def drop(self, surface_ids: Iterable[str]) -> None:
        """Forgets surfaces the renderer no longer holds."""
        for surface_id in surface_ids:
            for state in (self.drafted, self.wire):
                if state is not None and state.get_surface(surface_id) is not None:
                    state.apply(delete_surface(surface_id))
            self.binds.pop(surface_id, None)
            self.trip_fields.pop(surface_id, None)
            self.proposed.pop(surface_id, None)

    def reconcile(self, held: Iterable[str] | None) -> list[dict[str, Any]]:
        """Agrees with the renderer about which surfaces exist.

        `held` is what the renderer says it holds. Surfaces this server drew
        and the renderer no longer holds are forgotten. A standing surface the
        renderer holds and this server never drew (the server restarted) is
        deleted, so the next panel is created rather than updated blind.
        """
        if held is None:
            return []
        held = {str(surface_id) for surface_id in held}
        self.drop(self.surfaces - held)
        return [
            delete_surface(surface_id) for surface_id in sorted(held - self.surfaces) if surface_id in STANDING_SURFACES
        ]

    def data_of(self, surface_id: str) -> dict[str, Any]:
        surface = self.wire.get_surface(surface_id)
        if surface is None:
            return {}
        value = surface.data_model.get("/")
        return value if isinstance(value, dict) else {}

    def edits(self, reported: dict[str, Any] | None, pressed: str | None = None) -> dict[str, Any]:
        """The record fields the traveller changed on screen.

        `reported` is the renderer's data model, by surface. A value counts
        when it differs from what this server last put there, so a surface
        that only shows the record says nothing. A surface this server never
        drew counts only when it is the one that was pressed. The mirror takes
        the reported values, so the same edit is not counted twice.
        """
        changed: dict[str, Any] = {}
        for surface_id, model in (reported or {}).items():
            if not isinstance(model, dict) or not isinstance(model.get("trip"), dict):
                continue
            known = self.wire.get_surface(surface_id) is not None
            if not known and surface_id != pressed:
                continue
            held = self.data_of(surface_id).get("trip") if known else None
            held = held if isinstance(held, dict) else {}
            for key, value in model["trip"].items():
                if key == "legs" and isinstance(value, list):
                    hops = _hops_changed(value, held.get(key))
                    if hops is None:
                        continue
                    changed[key] = hops
                elif _stamp(value) != _stamp(held.get(key)):
                    changed[key] = value
                else:
                    continue
                if known:
                    self.wire.apply(update_data(surface_id, f"/trip/{key}", value))
        return changed

    def shows(self, root: str) -> bool:
        """Whether a card this turn binds a lookup's rows, at its root or by hop."""
        wanted = {root, BY_HOP.get(root, root)}
        return any(self.binds.get(surface, set()) & wanted for surface in self.this_turn)

    # -- the data surfaces bind ----------------------------------------------

    def observe(self, messages: Iterable[dict[str, Any]]) -> set[str]:
        """Records the roots these messages bind; returns surfaces that gained one."""
        gained: set[str] = set()
        for message in messages:
            surface_id, components = components_of(message)
            if surface_id and components:
                bound = roots_bound(components)
                fields = trip_fields_bound(components)
                if bound - self.binds.get(surface_id, set()) or fields - self.trip_fields.get(surface_id, set()):
                    gained.add(surface_id)
                self.binds.setdefault(surface_id, set()).update(bound)
                self.trip_fields.setdefault(surface_id, set()).update(fields)
            created = message.get("createSurface")
            if isinstance(created, dict):
                trip = (created.get("dataModel") or {}).get("trip")
                if isinstance(trip, dict):
                    proposed = {key: "" for key, value in trip.items() if value not in (None, "") and key != "legs"}
                    # A hop's value is proposed field by field (`legs/3/travelers`),
                    # so suggesting one hop's party leaves every other hop's data
                    # to the record.
                    for index, leg in enumerate(trip.get("legs") or []):
                        if isinstance(leg, dict):
                            for field_name, value in leg.items():
                                if value not in (None, ""):
                                    proposed[f"legs/{index}/{field_name}"] = ""
                    self.proposed[created["surfaceId"]] = proposed
            deleted = message.get("deleteSurface")
            if isinstance(deleted, dict):
                self.binds.pop(deleted.get("surfaceId", ""), None)
                self.trip_fields.pop(deleted.get("surfaceId", ""), None)
                self.proposed.pop(deleted.get("surfaceId", ""), None)
        return gained

    def provide(self, values: Values, surfaces: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """`updateDataModel` for every bound root whose value is not on screen.

        Compared against the wire mirror, which holds what was sent and what
        the traveller has since set, so a value goes out only when it differs.
        `/trip` goes field by field, only the fields the surface binds, and
        never as an empty value: an absent field on the record is nothing to
        say. Applied to the mirror as sent.
        """
        out: list[dict[str, Any]] = []
        for surface_id in list(surfaces) if surfaces is not None else list(self.binds):
            bound = self.binds.get(surface_id)
            if not bound or self.wire.get_surface(surface_id) is None:
                continue
            offered = values(surface_id)
            held = self.data_of(surface_id)
            for root in sorted(bound):
                if root not in offered:
                    continue
                if root == "trip":
                    out.extend(self._record(surface_id, offered["trip"], held.get("trip")))
                elif _stamp(offered[root]) != _stamp(held.get(root)):
                    out.append(update_data(surface_id, f"/{root}", offered[root]))
        for message in out:
            self.wire.apply(message)
        return out

    def _record(self, surface_id: str, record: dict[str, Any], held: Any) -> list[dict[str, Any]]:
        held = held if isinstance(held, dict) else {}
        proposed = self.proposed.get(surface_id, {})
        fields = self.trip_fields.get(surface_id, {"*"})
        out = []
        for key, value in record.items():
            if "*" not in fields and key not in fields:
                continue
            if key == "legs" and isinstance(value, list):
                value = _hops_with_proposals(value, held.get(key), proposed)
            if value in (None, "") or _stamp(value) == _stamp(held.get(key)):
                continue
            if key in proposed:
                # The model suggested a value here; it stands until the record
                # itself moves.
                if proposed[key] in ("", _stamp(value)):
                    proposed[key] = _stamp(value)
                    continue
                del proposed[key]
            out.append(update_data(surface_id, f"/trip/{key}", value))
        return out


# --------------------------------------------------------------------------
# One round of the model's output
# --------------------------------------------------------------------------


class Drawing:
    """Reads one round of model output through the SDK, into transport events.

    `surface_id` is where a block that names no surface draws. `creatable` is
    the set of new surfaces this round may create: its own, and the standing
    panels; `"any"` lets it create a card under any id of the model's choosing
    (a call, where the model names its own cards). A block may update any
    surface the renderer already holds.
    """

    def __init__(
        self,
        canvas: Canvas,
        surface_id: str,
        values: Values,
        creatable: Iterable[str] | str | None = None,
    ) -> None:
        self.canvas = canvas
        self.surface_id = surface_id
        self.values = values
        self.any_card = creatable == "any"
        self.creatable = {surface_id, *STANDING_SURFACES} if creatable is None or self.any_card else set(creatable)
        self.processor = canvas.processor(surface_id)
        self.stream = self.processor.open_stream(wrapped=True, state=canvas.drafted, after_rejected_block="continue")
        self.gate = FenceGate()
        self.raw: list[str] = []
        #: The surface whose block was refused, until that block ends.
        self._refused: str | None = None
        #: Surfaces drawn this round, for the checks run when a block ends.
        self._touched: set[str] = set()
        self.drawn: set[str] = set()

    # -- feeding ---------------------------------------------------------------

    def feed(self, chunk: str) -> list[tuple]:
        self.raw.append(chunk)
        try:
            parts = self.stream.feed(chunk)
        except Exception as error:  # noqa: BLE001 - the stream has ended; say why
            return self._ended(error)
        return self._read(parts)

    def close(self) -> list[tuple]:
        try:
            parts = self.stream.close()
        except Exception as error:  # noqa: BLE001
            return self._ended(error, closing=True)
        events = self._read(parts)
        events.extend(self._block_ended())
        said, fenced = self.gate.flush()
        if said:
            events.append(("text", said))
        events.extend(self._fenced(fenced))
        return events

    @property
    def source(self) -> str:
        return "".join(self.raw)

    def _ended(self, error: Exception, closing: bool = False) -> list[tuple]:
        events = self._read(list(getattr(error, "partial_results", None) or []))
        events.append(("rejected", _explained(str(error)), self._last_block()))
        if not closing:
            self.stream = self.processor.open_stream(
                wrapped=True, state=self.canvas.drafted, after_rejected_block="continue"
            )
        return events

    def _last_block(self) -> str:
        text = self.source
        start = text.rfind("<a2ui>")
        if start < 0:
            return text[-2000:]
        end = text.find("</a2ui>", start)
        return text[start : end + len("</a2ui>") if end >= 0 else len(text)]

    # -- parts -----------------------------------------------------------------

    def _read(self, parts: Iterable[Any]) -> list[tuple]:
        events: list[tuple] = []
        for part in parts:
            if isinstance(part, TextPart):
                events.extend(self._block_ended())
                said, fenced = self.gate.feed(part.text)
                if said:
                    events.append(("text", said))
                events.extend(self._fenced(fenced))
            elif isinstance(part, ErrorPart):
                if self._refused is None:
                    events.append(("rejected", _explained(str(part.error)), self._last_block()))
                self._refused = None
                events.extend(self._block_ended())
            elif isinstance(part, A2uiPart):
                events.extend(self._drawn(part))
        if not self.stream.is_in_block:
            self._refused = None
        return events

    def _drawn(self, part: A2uiPart) -> list[tuple]:
        written = to_message_dicts(part.a2ui)
        targets = [surface_of(message) for message in written]
        surface_id = next((target for target in targets if target), self.surface_id)
        if self._refused is not None and surface_id == self._refused:
            return []

        new = [message["createSurface"]["surfaceId"] for message in written if "createSurface" in message]
        for created in new:
            if created not in self.creatable and not self.any_card:
                # The whole part is refused, so every surface it created goes
                # from the draft: the renderer is sent none of them.
                for drafted in new:
                    if self.canvas.wire.get_surface(drafted) is None:
                        self._forget_draft(drafted)
                self._refused = created
                return [
                    (
                        "rejected",
                        f'This turn draws into "{self.surface_id}", or updates the '
                        f'standing panels; "{created}" is not one of them. Write the '
                        f'block again with surface("{self.surface_id}") or no surface().',
                        self._last_block(),
                    )
                ]

        try:
            expanded = to_message_dicts(EXPANDER.transform_to_transport(part.a2ui))
            left = sorted(
                {
                    str(component.get("component"))
                    for message in expanded
                    for component in components_of(message)[1]
                    if component.get("component") in MACRO_NAMES
                }
            )
            if left:
                raise ValueError(
                    f"{', '.join(left)} could not be expanded with the arguments given; "
                    "check them against the signature."
                )
            self.canvas.wire.apply(expanded)
        except Exception as error:  # noqa: BLE001 - refused here, told to the model
            return self._refuse(surface_id, new, str(error))

        self._touched.add(surface_id)
        self.drawn.add(surface_id)
        if surface_id not in STANDING_SURFACES:
            self.canvas.this_turn.add(surface_id)
        gained = self.canvas.observe(expanded)
        data = self.canvas.provide(self.values, gained) if gained else []
        return [("ui", surface_id, [*expanded, *data])]

    def _refuse(self, surface_id: str, created: list[str], reason: str) -> list[tuple]:
        """A block the wire refused after the draft accepted it.

        The two mirrors must agree, so the surface goes from both. If the
        renderer already holds part of it, it is deleted there too, and the
        model is asked to draw it again whole.
        """
        self._refused = surface_id
        events: list[tuple] = []
        for other in created:
            if other != surface_id and self.canvas.wire.get_surface(other) is None:
                self._forget_draft(other)
        if surface_id in created or self.canvas.wire.get_surface(surface_id) is None:
            self._forget_draft(surface_id)
        else:
            self.canvas.drop([surface_id])
            events.append(("ui", surface_id, [delete_surface(surface_id)]))
            reason += f' Surface "{surface_id}" was removed; draw it again whole.'
        events.append(("rejected", reason, self._last_block()))
        return events

    def _forget_draft(self, surface_id: str) -> None:
        drafted = self.canvas.drafted
        if drafted is not None and drafted.get_surface(surface_id) is not None:
            drafted.apply(delete_surface(surface_id))

    def _block_ended(self) -> list[tuple]:
        """Checks a finished surface for questions it cannot get answers to."""
        events: list[tuple] = []
        for surface_id in sorted(self._touched):
            surface = self.canvas.wire.get_surface(surface_id)
            if surface is None:
                continue
            record = self.values(surface_id).get("trip") or {}
            legs = len(record.get("legs") or []) if isinstance(record, dict) else 0
            for note in controls.problems(_components(surface), surface.send_data_model, legs):
                events.append(("advice", f'On surface "{surface_id}": {note}'))
        self._touched.clear()
        return events

    def _fenced(self, fenced: list["Fenced"]) -> list[tuple]:
        return [
            (
                "rejected",
                "That was not an <a2ui> block, so nothing was drawn. Write the "
                "surface as A2UI Express inside <a2ui> and </a2ui>.",
                block.source[:2000],
            )
            for block in fenced
            if block.looks_like_a_surface
        ]


_EXISTS = re.compile(r"Surface (\S+) already exists")


def _explained(reason: str) -> str:
    """The SDK's reason, with how to fix it when the fix is always the same."""
    found = _EXISTS.search(reason)
    if found:
        surface_id = found.group(1).strip("'\".")
        return (
            f"{reason} It is on screen already, so do not create it again: to change it, "
            f'write surface("{surface_id}", update=true) and only the components that change. '
            "If nothing about it needs to change, leave it out."
        )
    return reason


def _components(surface: Any) -> list[dict[str, Any]]:
    """A surface's components as the wire spells them."""
    return [
        {**component.properties, "id": component.id, "component": component.type}
        for component in surface.components_model.values
    ]


# --------------------------------------------------------------------------
# Prose that is not prose
# --------------------------------------------------------------------------


@dataclass
class Fenced:
    """A fenced block, or a run of component markup, kept out of the prose."""

    source: str

    @property
    def looks_like_a_surface(self) -> bool:
        return bool(_SURFACE_SHAPED.search(self.source))


#: A surface written as JSON or JSX instead of Express.
_SURFACE_SHAPED = re.compile(
    r'"(?:components|call|surfaceId|surface|root|catalog|catalogId)"\s*:'
    r"|<\s*[A-Z][A-Za-z0-9]*(?:\s|/?>)"
)
_MARKUP_OPENS = re.compile(r"<\s*[A-Z]")


class FenceGate:
    """Keeps fenced blocks and component markup out of the transcript.

    Streamed text splits anywhere, so up to two backticks, or a trailing `<`,
    are held back until the next chunk says what they were.
    """

    def __init__(self) -> None:
        self._inside = False
        self._carry = ""
        self._block: list[str] = []
        self._markup = False
        self._markup_src: list[str] = []
        self._edge = ""

    def feed(self, delta: str) -> tuple[str, list[Fenced]]:
        if self._markup:
            self._markup_src.append(delta)
            return "", []
        buffer = self._carry + delta
        self._carry = ""
        out: list[str] = []
        closed: list[Fenced] = []
        while buffer:
            marker = buffer.find("```")
            if marker == -1:
                keep = next((size for size in (2, 1) if buffer.endswith("`" * size)), 0)
                body, self._carry = buffer[: len(buffer) - keep], buffer[len(buffer) - keep :]
                (self._block if self._inside else out).append(body)
                break
            before, buffer = buffer[:marker], buffer[marker + 3 :]
            (self._block if self._inside else out).append(before)
            if self._inside:
                closed.append(Fenced("".join(self._block)))
                self._block = []
            self._inside = not self._inside
        return self._without_markup("".join(out)), closed

    def _without_markup(self, said: str) -> str:
        said, self._edge = self._edge + said, ""
        if not said:
            return ""
        found = _MARKUP_OPENS.search(said)
        if found:
            self._markup = True
            self._markup_src.append(said[found.start() :])
            return said[: found.start()]
        if said.rstrip().endswith("<"):
            keep = len(said) - said.rindex("<")
            self._edge = said[-keep:]
            return said[:-keep]
        return said

    def flush(self) -> tuple[str, list[Fenced]]:
        if self._markup:
            block = Fenced("".join(self._markup_src))
            self.__init__()
            return "", [block]
        tail, self._carry = self._edge + self._carry, ""
        self._edge = ""
        if self._inside:
            self._block.append(tail)
            block = Fenced("".join(self._block))
            self.__init__()
            return "", [block]
        return tail, []


__all__ = [
    "Canvas",
    "Drawing",
    "FenceGate",
    "LOOKUP_ROOTS",
    "STANDING_SURFACES",
    "delete_surface",
    "surface_of",
    "update_data",
]
