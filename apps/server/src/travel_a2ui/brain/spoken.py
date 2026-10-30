"""A card's fields, as the sentence a screen reader should read.

A `FlightOption` read in DOM order is "TAP Air Portugal TP622 15:39 JFK 02:30 +1
MAD 10h 51m 1 stop · LIS $989" — every fact, in no order, the price last. A
`HotelCard` is the same shape of problem. The fields are all there and the
reading of them is not a sentence, which is the gap `accessibility.label` exists
to close.

**Only for the cards the host draws itself**, which is the whole of why this
file is allowed to exist. Naming a card the *agent* composed is the agent's
job, taught in the brief and shown in the worked examples; a host pass that
filled it in for the model was the first version of this and the wrong one,
because it moved a decision about what a card says out of the prompt and into
Python.

Two producers are left, and both of them compose the entire card already:

  `builders.py`   the surfaces behind the `show_*` tools, which is what a voice
                  call draws. The Live API has no way to send Express, so the
                  host writes the heading, the rows, the events and the
                  provenance caption — the label is part of the same act.
  `skeleton.py`   the rows painted the moment a lookup starts, before the model
                  has said anything at all.
"""

from __future__ import annotations

from typing import Any

from .bindings import is_binding


def _literal(fields: dict[str, Any], key: str) -> str:
    """A field's value, only when it is a plain string.

    A bound property — `{"@path": "/trip/legs/0/airline"}` — has no value here
    to read: it is resolved in the renderer against a data model this never
    sees. Rather than invent one, the field is left out of the sentence and the
    rest of it still reads.
    """
    value = fields.get(key)
    if is_binding(value) or isinstance(value, dict):
        return ""
    return value.strip() if isinstance(value, str) else ""


def _joined(identity: str, parts: list[str]) -> str:
    """The clauses that have something in them — or nothing, if too few do.

    A card whose fields are mostly bindings yields a sentence of one clause,
    and a one-clause label is worse than no label: `aria-label` *replaces* what
    a screen reader would otherwise read, so "€281" on a card that says
    "Norwegian, 07:15 CPH, nonstop, €281" is a card that lost everything but
    its price. Two clauses and the identity — the airline, the hotel's name —
    are the floor for being an improvement on the card's own text.
    """
    clauses = [part for part in parts if part]
    if not identity or len(clauses) < 2:
        return ""
    return ", ".join(clauses)


def _run(parts: list[str]) -> str:
    """The parts that have something in them, as one phrase."""
    return " ".join(part for part in parts if part)


def flight_label(fields: dict[str, Any]) -> str:
    """What a fare card says, in one line.

    `total` before `price` on purpose: a leg carrying two people shows both, and
    a sentence that read only the fare would present one traveller's price as
    the price — the exact mistake the card was changed to stop making.
    """
    airline = _run([_literal(fields, "airline"), _literal(fields, "flightNumber")])
    depart = _run([_literal(fields, "departTime"), _literal(fields, "origin")])
    arrive = _run([_literal(fields, "arriveTime"), _literal(fields, "destination")])
    leg = f"{depart} to {arrive}" if depart and arrive else depart or arrive
    # "1 stop · LIS" is a visual convention. Read aloud the dot is either
    # announced as a character or swallowed, and "1 stop, LIS" sounds like two
    # separate facts; "1 stop via LIS" is the sentence it stands in for.
    # "Nonstop" carries no dot and is left alone.
    stops = _literal(fields, "stops").replace(" · ", " via ")
    price = _literal(fields, "total") or _literal(fields, "price")
    return _joined(airline, [airline, leg, stops, price])


def hotel_label(fields: dict[str, Any]) -> str:
    """What a stay says, in one line."""
    name = _literal(fields, "name")
    rating = _literal(fields, "rating")
    return _joined(
        name,
        [
            name,
            _literal(fields, "neighborhood"),
            f"rated {rating}" if rating else "",
            _literal(fields, "price"),
        ],
    )


#: The cards worth naming, and the sentence for each.
#:
#: Only the two that read as fragments. A `StatTile` is a label and a value and
#: reads as one already; a `Text` is its own sentence. Naming everything would
#: be noise in the one channel that cannot be skimmed.
LABELS = {"FlightOption": flight_label, "HotelCard": hotel_label}


def label_for(component: str, fields: dict[str, Any]) -> str:
    """The sentence for this kind of card, or empty if it does not need one."""
    make = LABELS.get(component)
    return make(fields) if make else ""
