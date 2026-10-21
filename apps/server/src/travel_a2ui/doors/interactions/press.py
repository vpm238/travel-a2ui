"""What the traveller did, before the model is asked anything.

A turn starts with two facts the model has no part in: what the browser sent,
and what was on screen when they pressed something. This is the vocabulary for
both — the request a door hands the agent, the press it carries, the result it
gets back — plus the three small jobs that have to happen before the model is
asked: put what they set into the trip, work out which hop a press belongs to,
and turn the press into a sentence the model can read.

None of it needs a model, which is the point of it being here rather than in
the turn: a value somebody typed is a fact, and should not wait on the model
noticing and calling `save_trip`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ...brain import trip as model
from ...brain.providers.types import TravelProvider
from ...brain.finishing import STANDING_SURFACES
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
    provider: TravelProvider | None = None
    #: Injectable so a test can drive the loop from a scripted stream.
    client: Any | None = None


@dataclass
class TurnResult:
    interaction_id: str | None
    trip: dict[str, Any]
    stop_reason: str | None
    shape: str | None = None
    #: The setup this conversation is bound to. See `TurnRequest.setup`.
    setup: str | None = None


def _leg_pressed(context: dict[str, Any] | None) -> int | None:
    """The leg index a press named, if it named one.

    Several spellings, because the model picks one and this is not worth a
    round trip to correct: `leg` is the index into `legs` and `hop` counts hops
    from one, so hop two is `legs[0]`. Anything else is not an index.
    """
    if not isinstance(context, dict):
        return None
    for key, offset in (("leg", 0), ("legIndex", 0), ("hop", -2), ("hopIndex", -1)):
        value = context.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, str) and value.lstrip("-").isdigit():
            value = int(value)
        if isinstance(value, int):
            index = value + offset
            return index if index >= 0 else None
    return None


def _commit(saved: dict[str, Any], proposed: dict[str, Any], today: str) -> tuple[dict, list[str]]:
    """Applies what a surface sent, minus anything that would break the trip.

    `save_trip` has always validated, so a model that invented a return date
    before the departure was told so. A *commit* went nowhere near it: the
    traveller's own values were merged straight in, and a picker handing back
    20 April → 12 April priced four flights against a trip with negative nights.

    The rule itself is `model.sieve`, so a value arriving from a press is held
    to exactly what a value arriving from the model is held to. It used to live
    here, and `save_trip` had its own stricter one — refuse the call, not the
    field — which is how a stay the traveller had chosen was lost to a hop's
    dates being a day out.
    """
    return model.sieve(saved, proposed, today)


def describe_action(action: SurfaceAction) -> str:
    """What the model is told when someone presses something.

    The wire carries an action, not a sentence. The model still needs a
    sentence, and this is the one place that decides what it says — which is
    where it belongs: how this agent interprets a tap on a read-only panel is a
    fact about this agent, not about the tap, and a client should not be in the
    business of explaining it.
    """
    said = json.dumps(action.context or {}, ensure_ascii=False)
    where = action.surface_id

    # A panel is a record, not a form. An interaction there is a request to
    # re-open a decision in the conversation, where there is one place to edit
    # a value and a history of when it changed.
    if where in STANDING_SURFACES:
        field_name = (action.context or {}).get("field")
        if field_name:
            return (
                f'[interface] The traveler pressed "{action.name}" on the {where} for '
                f"`{field_name}`. Release that decision and ask for it again inline, "
                "pre-filled with what was there, along with anything that depended on it."
            )
        return (
            f'[interface] The traveler pressed "{action.name}" on the {where} (context {said}). '
            "The panel is read-only — ask them that in the conversation instead, with the "
            "controls it needs."
        )

    # A press that names a hop is told where the hop keeps things.
    #
    # The rule is in the flow brief, and a general rule read four turns ago is
    # not what gets followed at the moment of a press: measured, the model put
    # the hop in the context every time and still saved the ticket nowhere.
    # Saying it here costs a sentence and removes the inference — the traveller
    # chose a flight home, and it has to land on the hop that flies home rather
    # than on the trip's own field, which is the outbound's.
    leg = _leg_pressed(action.context)
    if leg is not None:
        return (
            f"[interface] {action.name} on {where} — context {said}. "
            f"That is hop {leg + 2}, so whatever it settled belongs on "
            f"`legs[{leg}]` — save it there, and leave the trip's own fields "
            "alone: those are the first hop's."
        )

    return f"[interface] {action.name} on {where} — context {said}"


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
