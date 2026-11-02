"""Changing a trip: merging, confirming, releasing, and hops of their own.

Every write to the record goes through one of these, which is what makes the
rules about writes true in one place rather than in each caller. `merge` is the
ordinary one; `onto_leg` sends a hop's own decisions to its leg rather than the
trip's flat fields; `release` lets a decision be taken back and drops whatever
depended on it, so changing the destination does not leave yesterday's hotel
attached to a city nobody is visiting.
"""

from __future__ import annotations

from typing import Any, Sequence

from .fields import Trip, _LEG_KEY
from .route import _legs_of
from .values import coerce

def normalize(value: Any) -> Trip:
    """Everything in `value` that belongs to a trip, in the shape a trip wants."""
    if not isinstance(value, dict):
        return {}
    out: Trip = {}
    for key, raw in value.items():
        coerced = coerce(key, raw)
        if coerced is not None:
            out[key] = coerced
    return out


def _legs_merged(saved: Any, patched: list[Any]) -> list[Any]:
    """Each hop merged with the hop at its index, rather than the route replaced.

    `legs` is the one value on a trip that is a list of objects, and `{**trip,
    **patch}` replaced it whole. The agent's `save_trip` takes the whole trip and
    it re-sends the route it knows — the cities, the dates, the party — so every
    save silently deleted whatever was on a leg and not in that call.

    What was on the leg and not in the call was the fare. The host records a
    press itself, so pressing a return put `selectedFlight`, `flightPrice`,
    `airline`, `departTime` and `arriveTime` on `legs[0]`; the agent's own
    `save_trip` landed moments later with the route, and three of the five were
    gone. The panel's return row then read

        BER → CPH / SK / SK6955 / Copenhagen / €71.00 / Economy

    against an outbound row carrying the airline and both times — because the
    trip's flat fields are hop one's and nothing was overwriting *those*.

    This is `sieve`'s argument one level down: a save is applied field by field
    and never refused whole, for exactly the reason that a model saving the route
    and a hotel in one call must not lose the hotel. A leg is the same shape of
    mistake, and it cost the same thing.

    The patch decides how many hops there are, so a route that genuinely lost a
    hop loses it. Only the *fields* of a surviving hop are preserved.
    """
    before = [leg if isinstance(leg, dict) else {} for leg in (saved or [])]
    out: list[Any] = []
    for index, leg in enumerate(patched):
        if not isinstance(leg, dict):
            out.append(leg)
            continue
        was = before[index] if index < len(before) else {}
        out.append({**was, **leg})
    return out


def merge(trip: Trip, patch: Any) -> Trip:
    """A patch applied to a trip, with the patch normalised first.

    `assumed` is the one field that does not simply overwrite. A patch saying
    "these two were guesses" is talking about the fields in *that* patch, and a
    later patch stating one of them for real has to clear its mark. So anything
    the patch sets is confirmed unless the patch itself names it as assumed, and
    marks on fields the patch does not mention are kept.
    """
    nxt = normalize(patch)
    declared = list(nxt.get("assumed") or [])
    touched = {key for key in nxt if key != "assumed"}

    assumed = [key for key in (trip.get("assumed") or []) if key not in touched] + declared

    merged: Trip = {**trip, **nxt}
    if isinstance(nxt.get("legs"), list):
        merged["legs"] = _legs_merged(trip.get("legs"), nxt["legs"])
    if assumed:
        merged["assumed"] = list(dict.fromkeys(assumed))
    else:
        merged.pop("assumed", None)
    return merged


def confirm(trip: Trip, fields: Iterable[str]) -> Trip:
    """Marks fields as confirmed — what a traveller pressing a button means."""
    said = set(fields)
    left = [key for key in (trip.get("assumed") or []) if key not in said]
    nxt = dict(trip)
    if left:
        nxt["assumed"] = left
    else:
        nxt.pop("assumed", None)
    return nxt


#: Trip fields a hop owns for itself, rather than sharing with the trip.
#:
#: The flat fields on a trip describe its *first* hop. Everything after it
#: keeps its own copy on its leg, which is why a second ticket has somewhere to
#: live at all.
#: Kept in step with what `Trip()` binds under `legs/N/`, which is the thing
#: that actually reads them. They disagreed, and the disagreement was invisible
#: from either side: the panel bound a hop's row to `legs/0/airline`,
#: `legs/0/departTime` and `legs/0/arriveTime`, this list did not carry them, so
#: `onto_leg` dropped all three on their way in and the row had nothing to draw.
#: Measured through Chromium, the return hop's row read
#:
#:     BER → Copenhagen / SK / SK6955 / BER / Copenhagen / €71.00 / Economy
#:
#: against an outbound row carrying the airline, the flight number and both
#: times. It was read as the model failing to save them — the brief,
#: `save_trip`'s argument descriptions and the press's own sentence were each
#: rewritten to insist on it — and none of that could ever have worked, because
#: the field was discarded one layer below wherever it was written.
#:
#: `test_every_binding_a_hop_draws_is_a_field_a_hop_owns` holds the two lists
#: together now.
LEG_OWNED: tuple[str, ...] = (
    "selectedFlight",
    "flightPrice",
    "airline",
    "departTime",
    "arriveTime",
    "selectedHotel",
    "hotelName",
    "nightlyPrice",
    "startDate",
    "endDate",
    "travelers",
    "needsStay",
    "neighborhood",
)


def onto_leg(trip: Trip, patch: dict[str, Any], index: int) -> Trip:
    """Writes a press's values onto one hop's leg instead of the trip.

    Pressing a fare sends back what was pressed, and the host records it
    without waking the model. That worked while every trip had one ticket. Give
    it a second, and the press said only "IB925, $286" — and the only field
    those fit is the trip's flat `selectedFlight`, which belongs to the
    *outbound*. So choosing a flight home overwrote the flight out: the
    traveller watched the fare they had already chosen turn into the one they
    just picked, and the panel never gained a way home at all.

    The fare now names its hop, and this puts it where the hop keeps it. Only
    the fields a hop actually owns move; anything else in the press — a budget,
    a note — is still the trip's and is left alone.

    An index past the end is dropped rather than growing the route. A press
    cannot invent a hop, and a trip that sprouts an empty leg because a button
    carried a stale number is a worse answer than a press that did nothing.
    """
    legs = [dict(leg) for leg in (trip.get("legs") or []) if isinstance(leg, dict)]
    if not (0 <= index < len(legs)):
        return dict(trip)

    moved = {key: patch[key] for key in LEG_OWNED if key in patch}
    if not moved:
        return dict(trip)

    legs[index] = {**legs[index], **moved}
    rest = {key: value for key, value in patch.items() if key not in moved}
    return {**trip, **rest, "legs": legs}


#: What else has to be let go when one decision is released.
#:
#: Changing the dates does not just change the dates: the flight was priced
#: against them and the stay was booked for those nights. Deliberately shallow —
#: one level, and only where the dependency is real. Cascading further would
#: clear a trip someone spent an hour on because they moved a date by a day.
DEPENDENTS: dict[str, list[str]] = {
    "destination": [
        "selectedFlight",
        "flightPrice",
        "selectedHotel",
        "nightlyPrice",
        "neighborhood",
        "planned",
    ],
    "origin": ["selectedFlight", "flightPrice"],
    "startDate": ["selectedFlight", "flightPrice", "selectedHotel", "nightlyPrice", "planned"],
    "endDate": ["selectedHotel", "nightlyPrice", "planned"],
    "travelers": ["selectedFlight", "flightPrice", "selectedHotel", "nightlyPrice"],
    "selectedFlight": ["flightPrice"],
    "selectedHotel": ["nightlyPrice"],
}


def released(keys: Sequence[str]) -> list[str]:
    """The fields a release clears: the one named, plus what depended on it."""
    out: dict[str, None] = {}
    for key in keys:
        out[key] = None
        for dependent in DEPENDENTS.get(key, []):
            out[dependent] = None
    return list(out)


def release(trip: Trip, keys: Sequence[str]) -> tuple[Trip, list[str]]:
    """Lets go of a decision so it can be made again.

    A key is either a trip field — `startDate` — or one that belongs to a
    single hop — `legs/1/travelers`. Both spellings matter, because both are
    decisions somebody made and can change: "actually three of us on the way
    back" is a change to one leg's party, and clearing the trip's `travelers`
    for it would undo a different answer on a different hop.
    """
    nxt = dict(trip)
    cleared: list[str] = []

    for key in released(keys):
        leg_key = _LEG_KEY.match(key)
        if leg_key is None:
            if trip.get(key) is not None:
                cleared.append(key)
                nxt.pop(key, None)
            continue

        index, field = int(leg_key.group(1)), leg_key.group(2)
        legs = [dict(leg) for leg in _legs_of(nxt)]
        if index < len(legs) and legs[index].get(field) is not None:
            legs[index].pop(field, None)
            nxt["legs"] = legs
            cleared.append(key)

    return nxt, cleared


def unskip(trip: Trip, stage: str) -> Trip:
    """Puts a ruled-out stage back into the plan."""
    remaining = [entry for entry in (trip.get("skip") or []) if entry != stage]
    nxt = dict(trip)
    if remaining:
        nxt["skip"] = remaining
    else:
        nxt.pop("skip", None)
    return nxt
