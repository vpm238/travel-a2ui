"""The shareable page: one trip, as a page somebody can send to somebody else.

The one thing the agent produces that is not a surface and not a tool result.
It is written here rather than drawn as A2UI because its reader has no renderer
— it is a link, opened by whoever the traveller sent it to, in whatever they
happen to be using.
"""

from __future__ import annotations

from typing import Any

from .. import trip as model
from .answers import _day_text, _money_text

#: What a shared page says about where its numbers came from.
#:
#: The label travels with the page rather than staying in the app. A plan sent
#: to somebody who was never in the conversation is the one place a sample fare
#: can be mistaken for a real one, because every piece of context that said
#: otherwise has been left behind.
FIXTURE_NOTE = (
    "Sample data. The fares, rates and totals here are generated for a demo — "
    "nothing is booked and nothing is bookable."
)


def _share_page(trip: dict[str, Any], note: str, today: str) -> str:
    """The trip as a page somebody outside the conversation can read.

    Markdown rather than a surface, and that is the point: a surface is drawn by
    a renderer this reader does not have. What travels is the plan itself.

    Assembled here rather than asked of the model because it is a *rendering* of
    recorded state — every line of it is already in the trip, and a model
    retelling it is a model with an opportunity to get a date wrong. The model's
    judgement goes into `note`, which is the one line that is genuinely writing.
    """
    legs = model.stops(trip)
    lines: list[str] = []

    title = trip.get("destination") or "The trip"
    lines.append(f"# {title}")
    if note:
        lines.append("")
        lines.append(f"*{note}*")

    basis = model.basis_of(trip)
    if basis:
        lines.append("")
        lines.append(basis)

    if legs:
        lines.append("")
        lines.append("## Getting there")
        for index, leg in enumerate(legs):
            where = f"{leg.get('origin') or '?'} → {leg.get('destination') or '?'}"
            when = " – ".join(
                _day_text(part) for part in (leg.get("startDate"), leg.get("endDate")) if part
            )
            party = leg.get("travelers")
            who = f"{party} traveller{'' if party == 1 else 's'}" if party else ""
            flight = leg.get("selectedFlight")
            fare = leg.get("flightPrice")
            held = f"**{flight}**" if flight else "_no flight chosen yet_"
            cost = f" · {_money_text(fare)}" if fare is not None else ""
            detail = " · ".join(part for part in (when, who) if part)
            lines.append(f"{index + 1}. {where} — {held}{cost}" + (f"  \n   {detail}" if detail else ""))

    staying = [leg for leg in legs if leg.get("selectedHotel")]
    if staying:
        lines.append("")
        lines.append("## Where you are staying")
        for leg in staying:
            rate = leg.get("nightlyPrice")
            per = f" · {_money_text(rate)} a night" if rate is not None else ""
            lines.append(f"- **{leg['destination']}** — {leg['selectedHotel']}{per}")

    days = trip.get("days")
    if isinstance(days, list) and days:
        lines.append("")
        lines.append("## The days")
        for day in days:
            if not isinstance(day, dict):
                continue
            heading = " — ".join(
                part
                for part in (day.get("title"), _day_text(day.get("date")))
                if part
            )
            lines.append("")
            lines.append(f"### {heading or 'A day'}")
            if day.get("summary"):
                lines.append(f"*{day['summary']}*")
            activities = day.get("activities")
            if not isinstance(activities, list) or not activities:
                # Said rather than left blank: an empty day is a rest day, and a
                # heading with nothing under it reads as a mistake.
                lines.append("- A day with nothing booked.")
                continue
            for item in activities:
                if not isinstance(item, dict):
                    continue
                when = f"**{item['time']}** " if item.get("time") else ""
                tail = " · ".join(
                    part for part in (item.get("duration"), item.get("note")) if part
                )
                lines.append(f"- {when}{item.get('title', '')}" + (f" — {tail}" if tail else ""))

    if trip.get("budget") is not None or trip.get("spent") is not None:
        lines.append("")
        lines.append("## What it comes to")
        if trip.get("spent") is not None:
            lines.append(f"- Booked so far: {_money_text(trip['spent'])}")
        if trip.get("budget") is not None:
            lines.append(f"- Budget: {_money_text(trip['budget'])}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(FIXTURE_NOTE)
    return "\n".join(lines)
