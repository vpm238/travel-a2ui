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


async def stop_of_fare(
    context: dict[str, Any] | None, trip: dict[str, Any], provider: Any
) -> int | None:
    """Which stop of the route a pressed fare flies, read off the fare itself.

    0 is the first hop, whose choices are the trip's own fields; stop N is
    `legs[N - 1]`. None when the fare names no route, or when its route matches
    no stop, or more than one.

    A fare card carries `from` and `to` — the airports it flies between — so the
    hop it belongs to does not depend on the agent having passed `hop` when it
    drew the list. It did not always: the same return list came back with
    `hop: 2`, `hop: 1` and no hop at all, and a press without one was recorded
    on the first hop's fields. The panel then showed the flight home on the
    outbound card until the agent saved things back, and the return card, saved
    by the agent with an id and a price and nothing else, had no airline.
    """
    if not isinstance(context, dict):
        return None
    flies_from = str(context.get("from") or "").strip().casefold()
    flies_to = str(context.get("to") or "").strip().casefold()
    if not flies_from or not flies_to:
        return None

    names: dict[str, set[str]] = {}

    async def known_as(place: Any) -> set[str]:
        """A place as the trip spells it, plus its airport code and city."""
        said = str(place or "").strip()
        if said not in names:
            out = {said.casefold()} if said else set()
            if said and provider is not None:
                try:
                    found = await provider.resolve_destination(said)
                except Exception:  # noqa: BLE001 - an unresolvable place is just unmatched
                    found = None
                if isinstance(found, dict):
                    out |= {
                        str(found.get(key) or "").strip().casefold()
                        for key in ("airport", "city")
                    } - {""}
            names[said] = out
        return names[said]

    matched = [
        index
        for index, stop in enumerate(model.stops(trip))
        if flies_from in await known_as(stop.get("origin"))
        and flies_to in await known_as(stop.get("destination"))
    ]
    return matched[0] if len(matched) == 1 else None


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


#: What a press carries, named as the trip field it belongs in.
#:
#: Per press, because `id` and `price` mean different fields depending on what
#: was pressed: a fare's id is `selectedFlight` and a stay's is
#: `selectedHotel`. One shared mapping told a traveller choosing a hotel to
#: save it as a flight.
#:
#: Spelling it out at all is the point. This sentence used to say "whatever it
#: settled belongs on `legs[N]`", and the model read "it settled" as the flight
#: id: `legs[0].selectedFlight` landed every time; `airline`, `departTime` and
#: `arriveTime` never did, through two live runs and two rewrites of the same
#: rule in the brief and in `save_trip`'s argument descriptions.
_SAVES_AS: dict[str, tuple[tuple[str, str], ...]] = {
    "select_flight": (
        ("id", "selectedFlight"),
        ("price", "flightPrice"),
        ("airline", "airline"),
        ("flightNumber", "flightNumber"),
        ("departTime", "departTime"),
        ("arriveTime", "arriveTime"),
    ),
    "select_hotel": (
        ("id", "selectedHotel"),
        ("name", "hotelName"),
        ("price", "nightlyPrice"),
    ),
}


def _belongs_on_the_leg(name: str, context: dict[str, Any]) -> str:
    """The press's own fields, named as the trip names them.

    Checked against the trip's field table, so a field added for the panel to
    read cannot be left out of the sentence that says where to put it.
    """
    said = []
    for context_key, trip_key in _SAVES_AS.get(name, ()):
        if context_key in (context or {}) and trip_key in model.TRIP_KEYS:
            said.append(trip_key if context_key == trip_key else f"{trip_key} (`{context_key}`)")
    if not said:
        return ""
    spelled = ", ".join(f"`{one}`" if "(" not in one else one for one in said)
    return f" That means {spelled}."


def as_trip_fields(action: SurfaceAction | None) -> dict[str, Any]:
    """A press's context under the trip's own field names.

    A fare card's context is `{id, price, airline, departTime, arriveTime}`,
    because those are the row's names. The trip calls the first two
    `selectedFlight` and `flightPrice`, so `normalize` — which keeps trip fields
    and drops everything else — threw them away, and recording the choice was
    left to the model noticing and calling `save_trip`.

    Which it does by halves. Measured through Chromium, on the hop that is not
    the first: `selectedFlight` and `flightPrice` landed on the leg and
    `airline`, `departTime` and `arriveTime` did not, so the panel's return row
    read `SK / SK6955 / BER / Copenhagen / €71.00` against an outbound row
    carrying the airline, the flight number and both times. Three rewrites of
    that rule — in the brief, in `save_trip`'s argument descriptions, and in the
    sentence this file builds for the press — did not move it.

    So the host does it. A press is a fact, which is this module's whole premise:
    "a value somebody typed is a fact, and should not wait on the model noticing
    and calling `save_trip`." `_SAVES_AS` already said which trip field each of
    the press's keys belongs in — it was only being used to *describe* the press
    to the model. Using it to record the press as well costs nothing and removes
    the inference.

    The model is still told what happened and still saves what it likes; this
    just means the panel does not depend on it getting all five right.
    """
    if action is None:
        return {}
    context = action.context or {}
    renamed: dict[str, Any] = {}
    for context_key, trip_key in _SAVES_AS.get(action.name, ()):
        if context_key in context and context[context_key] is not None:
            renamed[trip_key] = context[context_key]
    return renamed


_FROM_CONTEXT: Any = object()


def describe_action(action: SurfaceAction, leg: Any = _FROM_CONTEXT) -> str:
    """What the model is told when someone presses something.

    `leg` is the hop the host worked out the press belongs to (see
    `stop_of_fare`); left out, it is read from the press's own `hop`.

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
    if leg is _FROM_CONTEXT:
        leg = _leg_pressed(action.context)
    if leg is not None:
        # Named, not implied.
        #
        # This said "whatever it settled belongs on `legs[N]`", and the model
        # read "it settled" as the flight id: `legs[0].selectedFlight` landed
        # every time, `airline`, `departTime` and `arriveTime` never did. Two
        # live runs, and two rewrites of the same rule in the brief and in
        # `save_trip`'s argument descriptions, neither of which moved it.
        #
        # The host knows exactly which facts the press carries, because the
        # macro put them in the context. So it lists them, which is the one
        # thing a general rule cannot do.
        fields = _belongs_on_the_leg(action.name, action.context or {})
        return (
            f"[interface] {action.name} on {where} — context {said}. "
            f"That is hop {leg + 2}, so everything it settled belongs on "
            f"`legs[{leg}]`.{fields} Save them there, and leave the trip's own "
            "fields alone: those are the first hop's."
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
