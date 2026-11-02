"""Putting the trip into a surface, so its controls open already filled in.

A `DateRangePicker` bound to `/trip/startDate` shows nothing unless something
puts the date there, and the model cannot be relied on to write a `dataModel`
block it was merely asked for. So the host writes it: `/trip` and `/plan` on
every surface it creates, and `updateDataModel` for the panels already on
screen.

Doing it here rather than in the browser is the point. The first version of
this lived in the React app, which meant the web client knew what a trip was
and a Flutter client would have had to be taught the same things to behave the
same way — and taught again every time the trip grew a field.
"""

from __future__ import annotations

from typing import Any

from .. import trip as model
from .shared import VERSION, A2uiMessage

#: How a plan step reads on screen.
_STAGE_LABELS = {
    "route": "Where to, and from",
    "dates": "Dates",
    "party": "Who is going",
    "flight": "Flight",
    "stay": "Somewhere to stay",
    "budget": "Budget",
    "plan": "The days",
}


# --------------------------------------------------------------------------
# The plan, and the trip, as data a surface binds to
# --------------------------------------------------------------------------


def money_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """What the trip has committed to so far, and what is left of the budget.

    A *running* total, which is the difference between this and
    `estimate_cost`: that one projects a whole trip and fills in a plausible
    fare for a hop nobody has priced, because a projection with a hole in it is
    no use. This counts only what has actually been chosen, so it starts at
    nothing, rises as each decision lands, and never claims a number nobody
    agreed to.

    Per hop, because the party and the nights are per hop — a fare is one
    ticket, so it is multiplied by the people on *that* hop, and a stay is one
    night, multiplied by the nights at *that* stop. Totalling one fare by one
    party size is how a three-city trip where somebody joins in Chicago came out
    confidently and invisibly wrong, which `_estimate` documents at length.

    Numbers, not display strings. The panel binds them through
    `formatCurrency`, so the trip's own currency is applied in one place and a
    stay quoted in euros is not totalled into dollars.
    """
    from .. import trip as model

    hops = model.journey(model.normalize(trip))
    total = 0.0
    counted = False
    for hop in hops:
        if not isinstance(hop, dict):
            continue
        party = hop.get("travelers")
        party = int(party) if isinstance(party, (int, float)) and party > 0 else 1
        fare = hop.get("flightPrice")
        if isinstance(fare, (int, float)):
            total += float(fare) * party
            counted = True
        nightly = hop.get("nightlyPrice")
        nights = hop.get("nights")
        if isinstance(nightly, (int, float)) and isinstance(nights, (int, float)) and nights > 0:
            total += float(nightly) * int(nights)
            counted = True

    out: dict[str, Any] = {}
    if counted:
        out["total"] = round(total, 2)
    budget = trip.get("budget")
    if isinstance(budget, (int, float)):
        out["budget"] = round(float(budget), 2)
        if counted:
            left = round(float(budget) - total, 2)
            out["remaining"] = left
            # Said rather than inferred from a minus sign, so the panel can
            # label it without doing arithmetic of its own.
            out["over"] = left < 0
    return out


def plan_rows(trip: dict[str, Any]) -> dict[str, Any]:
    """Every decision the traveler has made, as rows a surface binds to.

    **This is what the panel is.** Not a progress checklist — that was a ladder
    of stages in Python, and it is gone — but the record of what has been
    decided, each row addressed so a Change button can release exactly that one
    and nothing else.

    Two kinds of row, because decisions come in two scopes:

      `decisions`     the trip's own — where to, from where, the dates, the
                      budget. One answer for the whole journey.
      `route[].decisions`
                      a hop's own — who is on it, its ticket, where they sleep.
                      Keyed `legs/1/travelers`, which `release` understands, so
                      "actually three of us on the way back" changes one hop
                      rather than undoing the answer on another.

    Labels and lines are resolved here, which keeps a Flutter client from
    needing an opinion about what "somewhere to stay" is called in English, and
    means a value changing costs no model turn.
    """
    varies = model.party_varies(trip)
    hops = model.journey(trip)

    #: The trip-wide half. A hop's own decisions are reported on the hop, so
    #: they are left out here rather than said twice with different scopes.
    on_a_hop = {"travelers", "selectedFlight", "selectedHotel"}
    decisions: list[dict[str, Any]] = []
    for field in model.FIELDS:
        key = field["key"]
        value = trip.get(key)
        if value is None or value == "" or field.get("kind") in model.LIST_KINDS:
            continue
        if key in on_a_hop and hops:
            continue
        text = _value_text(value, str(field.get("kind") or ""))
        decisions.append(
            {
                "key": key,
                "label": field["label"],
                "value": text,
                "line": f"{field['label']} — {text}",
            }
        )

    route: list[dict[str, Any]] = []
    for hop in hops:
        nights = hop.get("nights")
        detail = [
            f"{hop['travelers']}\u00d7" if hop.get("travelers") is not None and varies else "",
            f"{nights} nights" if nights else "same day" if nights == 0 else "",
            hop["mode"] if hop.get("mode") and hop["mode"] != "air" else "",
            hop.get("purpose") or "",
            ", ".join(hop["wants"]) if hop["wants"] else "",
        ]
        detail = [part for part in detail if part]
        joined = " \u00b7 ".join(detail)
        route.append(
            {
                "place": hop["to"],
                "from": hop.get("from") or "",
                "nights": nights if nights is not None else 0,
                "detail": joined,
                "line": f"{hop['to']} \u2014 {joined}" if detail else hop["to"],
                # Each one changeable on its own. The panel draws a Change
                # button per row and the host answers it with `release`.
                "decisions": [
                    {
                        **row,
                        "value": _value_text(row["value"], _kind_of(row["key"])),
                        "line": (
                            f"{row['label']} \u2014 "
                            f"{_value_text(row['value'], _kind_of(row['key']))}"
                        ),
                    }
                    for row in hop["decisions"]
                ],
                "wants": hop["wants"],
            }
        )

    open_hops = sum(1 for hop in hops if hop["wants"])
    settled = len(decisions) + sum(len(stop["decisions"]) for stop in route)
    return {
        "decisions": decisions,
        "route": route,
        "caption": f"{settled} decided"
        + (f" \u00b7 {len(route)} hops" if route else "")
        + (f" \u00b7 {open_hops} open" if open_hops else ""),
        "complete": bool(route) and open_hops == 0,
        # So the panel can decide whether the route is worth drawing at all.
        "multiStop": len(route) > 1,
    }


def _kind_of(key: str) -> str:
    """The trip model's kind for a decision key, hop-scoped or not.

    `legs/1/flightPrice` is a `flightPrice`, and the panel should say `$412`
    for it on hop two exactly as it does on hop one.
    """
    field = model.field_for(key.rsplit("/", 1)[-1])
    return str((field or {}).get("kind") or "")


def _value_text(value: Any, kind: str = "") -> str:
    """A decided value as one short string, whatever kind it is.

    `kind` comes from the trip model, and the one that matters is `money`: the
    panel is where somebody checks what they agreed to, and "what that flight
    costs — 412" is a number in no currency. Every price field is already
    declared `money` in `data/trip-model.json`, so there is nothing to guess.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item) or "—"
    if kind == "money" and isinstance(value, (int, float)):
        return f"${value:,.0f}"
    return str(value)


def _stated_facts(trip: dict[str, Any]) -> list[tuple[str, Any]]:
    """Trip fields worth putting on a surface: set, and not empty."""
    facts: list[tuple[str, Any]] = []
    for key in model.TRIP_KEYS:
        value = trip.get(key)
        if value is None or value == "":
            continue
        facts.append((key, value))
    return facts


def seed_surface_trip(messages: list[A2uiMessage], trip: dict[str, Any]) -> list[A2uiMessage]:
    """Fills a newly created surface's `/trip` with what the trip already knows.

    Only fields the surface left unset. A model that deliberately wrote a value
    — a suggested date, a widened budget — is *proposing* something, and a
    proposal should beat the older fact it proposes to replace.

    Written into `createSurface.dataModel` rather than as following
    `updateDataModel` messages, so the surface is complete in the message that
    creates it and never paints once empty and again filled.
    """
    facts = _stated_facts(trip)

    for message in messages:
        if "createSurface" not in message:
            continue
        surface = message["createSurface"]
        data_model = dict(surface.get("dataModel") or {})
        seeded = dict(data_model.get("trip") or {})
        for key, value in facts:
            # Declared-and-empty is not a proposal.
            #
            # `key in seeded` treated a path the surface merely *mentions* as a
            # value the model meant, and a bound control mentions every path it
            # writes to. So a date picker bound to `$/trip/startDate` arrived
            # carrying `startDate: null`, the seed was skipped, and the control
            # rendered blank over a trip that knew the answer — which is the
            # whole of "why does it not auto-fill the form". Say "two weeks from
            # next Friday" or "three of us" and the agent records it, draws the
            # form to confirm it, and the form came up empty.
            #
            # The panel had it worse, because a panel is never filled in by
            # hand: its `createSurface` carried `legs: null` and landed on top
            # of the `/trip/legs` sent moments before, so a hop's airline and
            # times were wiped from the client's data model after the server had
            # got them right. That was the last layer of the return row drawing
            # blank.
            #
            # A real value still wins — a suggested date, a widened budget is a
            # proposal and should beat the older fact it proposes to replace.
            if seeded.get(key) not in (None, ""):
                continue
            seeded[key] = value
        # No early return on an empty trip: `/plan` still has to be here, or a
        # panel drawn before anything is decided binds to nothing and renders
        # blank rather than rendering the sequence it is about to walk through.
        data_model["trip"] = seeded
        data_model["plan"] = plan_rows(trip)
        # The running total, beside the decisions it is the sum of.
        data_model["money"] = money_rows(trip)
        surface["dataModel"] = data_model

    return messages


def trip_updates(surface_id: str, trip: dict[str, Any]) -> list[A2uiMessage]:
    """`updateDataModel` messages bringing a standing surface up to date.

    For the panels, which outlive the turn that drew them. An inline card is
    deliberately not included: it is the record of what was asked at the time,
    and rewriting history underneath it is worse than letting it be old.
    """
    messages: list[A2uiMessage] = [
        {
            "version": VERSION,
            "updateDataModel": {"surfaceId": surface_id, "path": f"/trip/{key}", "value": value},
        }
        for key, value in _stated_facts(trip)
    ]
    # The checklist moves whenever the trip does, and it moves without a model
    # turn: the agent drew the shape once and the rows arrive as data.
    messages.append(
        {
            "version": VERSION,
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/plan",
                "value": plan_rows(trip),
            },
        }
    )
    # The running total, which moves whenever a decision does and so belongs
    # with the data rather than behind a redraw. See `money_rows`.
    messages.append(
        {
            "version": VERSION,
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/money",
                "value": money_rows(trip),
            },
        }
    )
    return messages
