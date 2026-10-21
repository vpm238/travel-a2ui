"""The fingerprint that decides whether a panel is redrawn.

Not every change to a trip. Values reach a standing surface live, as
`updateDataModel` with no model in the path, so a panel's origin updates the
moment somebody changes it. What warrants a *rebuild* is the panel needing
different controls — a second hop wants a second counter — and that is what
this is a fingerprint of.

It is one function, in a file of its own, because it is the one thing in the
trip model that is about the screen rather than the trip, and because what it
does and does not watch is a decision people keep needing to read.
"""

from __future__ import annotations

from .fields import DECISIONS, Trip, _blank
from .route import party_varies

def decision_shape(trip: Trip) -> str:
    """The decisions that make the panel a *different panel*.

    Not every field. Values reach a standing surface live, as `updateDataModel`
    with no model in the path — change the departure airport on an inline card
    and the panel's origin updates immediately. What warrants a *rebuild* is the
    panel needing different controls. Rebuilding on a slider value would mean a
    model turn every time someone dragged something.

    Built from which *decisions* are recorded rather than from which rung of a
    ladder the trip had reached, since there is no ladder any more. Not every
    field: a neighbourhood they mentioned, a cabin preference or a note refines
    a decision without changing which controls the panel needs, and rebuilding
    on one would mean a model turn every time somebody said "somewhere central".
    """
    settled = ",".join(key for key in DECISIONS if not _blank(trip.get(key)))
    return "|".join(
        [
            settled,
            trip.get("destination") or "",
            trip.get("selectedFlight") or "",
            trip.get("selectedHotel") or "",
            ">".join(leg.get("destination", "") for leg in (trip.get("legs") or [])),
            # A hop's own ticket and stay, which are decisions wherever they are
            # recorded. Only the trip's flat fields were watched, and those are
            # the *first* hop's — so choosing the flight home, which is saved on
            # the leg, moved nothing in this fingerprint. The panel declined to
            # rebuild and went on saying "Flight · Awaiting selection" under a
            # hop whose flight the traveller had just picked, beside an
            # itinerary that already had its flight number in it. Same for a
            # stay booked against a later hop.
            ">".join(
                f"{leg.get('selectedFlight') or ''}/{leg.get('selectedHotel') or ''}"
                for leg in (trip.get("legs") or [])
            ),
            # Who is on which hop, once they stop being the same number.
            #
            # This is the definition of "needing different controls": one
            # TravelerCounter can express a party, and cannot express a party
            # that changes along the way — that wants one per leg, labelled by
            # leg. The rest of this fingerprint watches leg *destinations*, so a
            # round trip stated up front already has its legs and adding "two of
            # us coming back" moved nothing in it.
            #
            # The panel therefore kept the single counter it was built with, and
            # went on showing "Travellers 1" for a trip that was one out and two
            # back. Nothing was lost — the trip had it, and the return fares were
            # priced for two — but the one surface whose job is showing what has
            # been decided was the one place it did not appear.
            "split" if party_varies(trip) else "",
        ]
    )
