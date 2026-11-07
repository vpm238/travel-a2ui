"""What a press settled, written onto the trip, and said to the model.

A press is a fact: the traveller chose this fare, these dates, that stay. The
host records it onto the trip, onto the hop it belongs to, before any model is
asked anything, and then tells the model what happened in a sentence. Both
doors do this — a typed turn and a voice call — so it lives here, in the brain,
and each door hands it the press it received.

An action here is a v1.0 renderer action (`brain/inbound.py`): `name`,
`surface_id`, `context`, `user_message`. What the traveller changed on screen
arrives separately, as the record fields that differ from what the agent last
put there (`Canvas.edits`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import trip as model
from .ui import STANDING_SURFACES

#: What a `change` on a panel card re-opens, by the card's `what`.
_CHANGED = {"flight": "selectedFlight", "stay": "selectedHotel"}


def _changed_field(context: dict[str, Any] | None) -> str | None:
    """The trip field a panel card's `change` names: `legs/2/selectedFlight`."""
    if not isinstance(context, dict):
        return None
    field_name = _CHANGED.get(str(context.get("what") or ""))
    if field_name is None:
        return None
    leg = _leg_pressed(context)
    return f"legs/{leg}/{field_name}" if leg is not None else field_name


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


async def stop_of_fare(context: dict[str, Any] | None, trip: dict[str, Any], provider: Any) -> int | None:
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
                    out |= {str(found.get(key) or "").strip().casefold() for key in ("airport", "city")} - {""}
            names[said] = out
        return names[said]

    matched = [
        index
        for index, stop in enumerate(model.stops(trip))
        if flies_from in await known_as(stop.get("origin")) and flies_to in await known_as(stop.get("destination"))
    ]
    return matched[0] if len(matched) == 1 else None


#: What a press carries, named as the trip field it belongs in.
#:
#: Per press, because `id` and `price` mean different fields depending on what
#: was pressed: a fare's id is `selectedFlight` and a stay's is
#: `selectedHotel`. One shared mapping told a traveller choosing a hotel to
#: save it as a flight.
#:
#: Spelling every field out is the point: told only that "whatever it settled
#: belongs on `legs[N]`", the model records the flight id and drops `airline`,
#: `departTime` and `arriveTime`.
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


def as_trip_fields(action: Any) -> dict[str, Any]:
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


@dataclass
class RecordedPress:
    """A press, written onto the trip. See `record_press`."""

    #: The trip after the press, with whatever it settled no longer `assumed`.
    trip: dict[str, Any]
    #: What looks wrong with the trip as recorded, as notes for the model.
    notes: list[str]
    #: Which leg the press landed on, or None for the trip's own fields.
    leg: int | None
    #: The trip fields the press said something about.
    said: list[str]


async def record_press(
    action: Any,
    trip: dict[str, Any],
    provider: Any,
    today: str,
    edits: dict[str, Any] | None = None,
) -> RecordedPress:
    """Writes what a press settled onto the trip, before any model hears of it.

    Values the traveller set on screen are facts, and the host records them
    rather than depending on the model to notice and call `save_trip`. One
    function for both doors: a typed turn and a voice call record the same press
    the same way, onto the same hop.

    The action's own context wins over `edits`: the context is what the
    button declared it was sending, and the edits are whatever else the
    traveller changed on a surface that sends its data model. A fare's context says `id` and `price` where the trip says
    `selectedFlight` and `flightPrice`; `as_trip_fields` renames them. The hop
    comes from the fare's own route when it can (`stop_of_fare`) and from the
    `hop` the list was drawn with when it cannot.
    """
    if edits is None:
        edits = (action.data_model or {}).get("trip") if action is not None else None
    from_surface = model.screen_patch(trip, edits)
    from_context = {
        **model.normalize(action.context),
        **model.normalize(as_trip_fields(action)),
    }
    stop = await stop_of_fare(action.context, {**trip, **from_surface}, provider)
    leg = (stop - 1 if stop > 0 else None) if stop is not None else _leg_pressed(action.context)

    proposed = {**trip, **from_surface, **from_context}
    if leg is not None:
        proposed = model.onto_leg({**trip, **from_surface}, dict(from_context), leg)
    committed = proposed
    said = [*from_surface.keys(), *from_context.keys()]
    # Pressing a button *is* saying so: whatever the surface sent stops being a
    # guess. Replaced rather than merged, because `confirm` removes `assumed`
    # once nothing is assumed, and a merge cannot take a key away.
    if said:
        committed = model.confirm(committed, said)
    committed = await complete_chosen_flights(committed, provider)
    notes = [problem["message"] for problem in model.problems(committed, today)]
    return RecordedPress(trip=committed, notes=notes, leg=leg, said=said)


_FROM_CONTEXT: Any = object()


def describe_action(action: Any, leg: Any = _FROM_CONTEXT) -> str:
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
    words = getattr(action, "user_message", None)
    if words:
        said = f'{said} — in their words: "{words}"'

    # A panel is a record, not a form. An interaction there is a request to
    # re-open a decision in the conversation, where there is one place to edit
    # a value and a history of when it changed.
    if where in STANDING_SURFACES:
        field_name = (action.context or {}).get("field") or _changed_field(action.context)
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


#: The facts about a chosen fare that the trip panel draws, by trip field.
_FARE_DETAILS = (
    ("airline", "airline"),
    ("flightNumber", "flightNumber"),
    ("departTime", "departTime"),
    ("arriveTime", "arriveTime"),
)


async def complete_chosen_flights(trip: dict[str, Any], provider: Any) -> dict[str, Any]:
    """The trip with every chosen fare's details filled in from the provider.

    A hop's fare can be chosen three ways — a press, a spoken "the Air France
    one", or the agent's own `save_trip` — and only a press carries the details.
    The other two usually save an id and a price, and the trip panel then drew
    the return with no airline: it binds what the record has when it is drawn,
    and a card drawn with a blank stays blank. So the host completes the record
    from the fare it offered, whoever chose it: the same search, asked again,
    and the row with that id.

    Only for a hop that has chosen a fare and is missing something about it, so
    a complete trip costs nothing. Returns a new trip; the input is not changed.
    """
    out = {**trip, "legs": [dict(leg) for leg in trip.get("legs") or [] if isinstance(leg, dict)]}
    for index, stop in enumerate(model.stops(trip)):
        own = out if index == 0 else (out["legs"][index - 1] if index - 1 < len(out["legs"]) else None)
        if own is None:
            continue
        chosen = str(own.get("selectedFlight") or "").strip()
        if not chosen or all(own.get(field) for field, _ in _FARE_DETAILS):
            continue
        if not (stop.get("origin") and stop.get("destination") and stop.get("startDate")):
            continue
        try:
            found = await provider.search_flights(
                {
                    "origin": stop["origin"],
                    "destination": stop["destination"],
                    "date": stop["startDate"],
                    "travelers": stop.get("travelers") or trip.get("travelers") or 1,
                }
            )
        except Exception:  # noqa: BLE001 - an incomplete card beats a failed save
            continue
        fares = [item for item in getattr(found, "items", None) or [] if isinstance(item, dict)]
        # By id, and by flight number for a model that saved "Air France AF242".
        fare = next((item for item in fares if str(item.get("id")) == chosen), None) or next(
            (item for item in fares if item.get("flightNumber") and str(item["flightNumber"]) in chosen),
            None,
        )
        if fare is None:
            continue
        for field, key in _FARE_DETAILS:
            if not own.get(field) and fare.get(key):
                own[field] = fare[key]
        if own.get("flightPrice") in (None, "") and isinstance(fare.get("priceValue"), (int, float)):
            own["flightPrice"] = fare["priceValue"]
        if str(fare.get("id") or "") and own.get("selectedFlight") != fare["id"]:
            own["selectedFlight"] = fare["id"]
    if not out["legs"] and "legs" not in trip:
        out.pop("legs")
    return out
