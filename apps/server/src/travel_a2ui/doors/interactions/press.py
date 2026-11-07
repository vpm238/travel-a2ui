"""What the traveller did, before the model is asked anything.

A turn starts with facts the model has no part in: what the renderer sent
(`brain/inbound.py`) and what the traveller changed on screen. This is the
vocabulary for a turn, the request a door hands the agent and the result it
gets back, plus the jobs that happen before the model is asked: put what they
set into the trip, work out which hop a press belongs to, and turn the press
into a sentence. Those are the brain's (`brain/presses.py`), because the voice
door does them too.

None of it needs a model, which is the point of it being here rather than in
the turn: a value somebody typed is a fact, and should not wait on the model
noticing and calling `save_trip`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...brain import trip as model
from ...brain.inbound import RendererError, SurfaceAction
from ...brain.providers.types import TravelProvider
from ...brain.ui import Canvas
from ..settings import DEFAULT_EFFORT


@dataclass
class TurnRequest:
    api_key: str
    model: str
    #: What the traveller typed. Empty when `action` carries the turn instead.
    message: str = ""
    #: The press this turn answers, as the renderer reported it (v1.0).
    action: SurfaceAction | None = None
    #: Errors the renderer reported since the last turn.
    errors: list[RendererError] = field(default_factory=list)
    #: The renderer's data model by surface (`a2uiRendererDataModel`).
    data_model: dict[str, Any] = field(default_factory=dict)
    #: The last interaction, or None to start a new conversation.
    interaction_id: str | None = None
    trip: dict[str, Any] = field(default_factory=dict)
    surface: str = "inline"
    surface_id: str = "inline-1"
    effort: str = DEFAULT_EFFORT
    #: What the browser knows about when the traveller is. See `_today`.
    client_hints: dict[str, Any] | None = None
    #: A fingerprint of the stable half of the prompt the conversation started
    #: with. When it no longer matches, the conversation is not continued.
    setup: str | None = None
    #: The agent's mirror of the renderer's surfaces, from the session.
    canvas: Canvas = field(default_factory=Canvas)
    provider: TravelProvider | None = None
    #: Injectable so a test can drive the loop from a scripted stream.
    client: Any | None = None


@dataclass
class TurnResult:
    interaction_id: str | None
    trip: dict[str, Any]
    stop_reason: str | None
    #: The setup this conversation is bound to. See `TurnRequest.setup`.
    setup: str | None = None


# What a press settles, and the sentence the model is told about it, are the
# brain's: both doors record a press the same way. Re-exported under the names
# this module has always had.
from ...brain.presses import (  # noqa: E402,F401
    _SAVES_AS,
    RecordedPress,
    _belongs_on_the_leg,
    _leg_pressed,
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
