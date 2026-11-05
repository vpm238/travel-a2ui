"""What the traveller did, before the model is asked anything.

A turn starts with two facts the model has no part in: what the browser sent,
and what was on screen when they pressed something. This is the vocabulary for
both — the request a door hands the agent, the press it carries, the result it
gets back — plus the three small jobs that have to happen before the model is
asked: put what they set into the trip, work out which hop a press belongs to,
and turn the press into a sentence the model can read. Those three are the
brain's (`brain/presses.py`), because the voice door does them too.

None of it needs a model, which is the point of it being here rather than in
the turn: a value somebody typed is a fact, and should not wait on the model
noticing and calling `save_trip`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...brain import trip as model
from ...brain.providers.types import TravelProvider
from ..settings import DEFAULT_EFFORT

#: Values a commit is not allowed to corrupt the trip with. One table, in the
#: model, so a press and a `save_trip` are refused for the same reasons.
REFUSABLE = model.REFUSABLE


@dataclass
class SurfaceAction:
    """An interaction on a surface, in A2UI's own shape.

    This is what a renderer produces when someone presses something — any
    renderer, on any platform, with nothing taught to it. It replaced a sentence
    the browser used to compose, which was a private protocol wearing the
    costume of a user message.

    `context` is the answer: the action's bound paths, resolved. `data_model` is
    the rest of the surface, opaque and optional — it keeps trip state exact
    without asking any client to know what a trip is, and a client that omits it
    still works.
    """

    name: str
    surface_id: str
    context: dict[str, Any] = field(default_factory=dict)
    data_model: dict[str, Any] | None = None
    source_component_id: str | None = None


@dataclass
class TurnRequest:
    api_key: str
    model: str
    #: What the traveller typed. Empty when `action` carries the turn instead.
    message: str = ""
    action: SurfaceAction | None = None
    #: The last interaction, or None to start a new conversation. The transcript
    #: lives on the server; this is the thread back to it.
    interaction_id: str | None = None
    trip: dict[str, Any] = field(default_factory=dict)
    surface: str = "inline"
    surface_id: str = "inline-1"
    skill: str = "express-modular"
    effort: str = DEFAULT_EFFORT
    #: What the browser knows about when the traveller is. See `_today`.
    client_hints: dict[str, Any] | None = None
    #: Which setup the conversation was started against, if it was started.
    #:
    #: A fingerprint of the stable half of the prompt. When it no longer matches
    #: — the traveller changed the skill variant, or the deployment shipped a new
    #: catalog — the conversation is not continued against rules nobody is
    #: reading any more: the chain is dropped and the new setup is sent.
    setup: str | None = None
    #: The decision shape the standing surfaces were last drawn for.
    shape: str | None = None
    #: How the agent composed each standing surface, from the session.
    #:
    #: A panel re-rendered from this costs no model call. See `Session.panels`
    #: and `panels.replayed`.
    panels: dict[str, str] = field(default_factory=dict)
    provider: TravelProvider | None = None
    #: Injectable so a test can drive the loop from a scripted stream.
    client: Any | None = None


@dataclass
class TurnResult:
    interaction_id: str | None
    trip: dict[str, Any]
    stop_reason: str | None
    shape: str | None = None
    #: Any standing surface the agent composed this turn, to be remembered.
    panels: dict[str, str] = field(default_factory=dict)
    #: The setup this conversation is bound to. See `TurnRequest.setup`.
    setup: str | None = None


# What a press settles, and the sentence the model is told about it, are the
# brain's: both doors record a press the same way. Re-exported under the names
# this module has always had.
from ...brain.presses import (  # noqa: E402,F401
    _SAVES_AS,
    _belongs_on_the_leg,
    _commit,
    _leg_pressed,
    RecordedPress,
    as_trip_fields,
    describe_action,
    record_press,
    stop_of_fare,
)


def _party_paths(trip: dict[str, Any]) -> tuple[str, ...]:
    """Where each hop's party lives, in route order.

    The trip's own `travelers` is the first hop's; every hop after it keeps its
    own on its leg. A surface asking who is on the journey has to ask it once
    per hop, and these are the paths those counters bind to.
    """
    legs = trip.get("legs")
    count = len(legs) if isinstance(legs, list) else 0
    paths = [model.binding_for("travelers")] if trip.get("destination") else []
    paths += [f"/trip/legs/{index}/travelers" for index in range(count)]
    # Mirrors `stops`: the flat fields are the first hop when there is a
    # destination to be the first hop, and `legs` is everything after it. One
    # hop has nothing to be inconsistent about.
    return tuple(paths) if len(paths) > 1 else ()
