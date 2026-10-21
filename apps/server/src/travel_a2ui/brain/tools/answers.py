"""Turning what a provider found into what the model should read.

Everything here is about the *answer*, not the lookup: what to say when a
search cannot run yet, what to say when it ran and found nothing, how to price
a fare for a party of two without the model reading a per-person figure as a
total, and how to write a sum of money in the currency the trip is actually in.

It is the largest part of the tools and the least interesting to read on the
way to something else, which is why it is its own file. The rule it exists to
serve is the architectural one: tools return data, so the data has to be worded
well enough that a model reading it draws the right card.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .. import trip as model
from ..providers.types import Found, NotFound, TravelProvider
from .contracts import ToolContext

def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _num(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _needs_input(what: str, missing: list[str]) -> dict[str, Any]:
    """A refusal that tells the model exactly how to stop being stuck.

    The failure this prevents is the confident one: with no dates the agent
    would price a week nobody chose, label it "estimated", and the traveller is
    then looking at fares for a trip that does not exist.
    """
    bound = ", ".join(f"${model.binding_for(key)}" for key in missing)
    return {
        "needs": missing,
        "message": (
            f"Cannot {what} without {model.ask_for(missing)}, and inventing a plausible answer "
            f"is worse than asking. Draw the controls for all of it in one surface — bound to "
            f"{bound} so the host pre-fills them — with a single commit button, and wait. If the "
            "traveler explicitly asked for a rough or seasonal figure, call again with "
            "flexible: true and label what you draw as indicative."
        ),
    }


def _cannot(outcome: NotFound) -> dict[str, Any]:
    """A provider with nothing, turned into something the model can act on.

    The counterpart to `_needs_input`. That one says "you have not asked the
    traveller enough"; this says "I asked and there is no answer" — and both end
    in a concrete next step rather than an empty surface.
    """
    return {
        "found": False,
        "reason": outcome.reason,
        "message": outcome.message,
        "options": outcome.recover,
        "provenance": outcome.provenance.as_dict(),
        "instruction": (
            "Say this in one short line and draw the options as choices the traveler can press. "
            "Do not substitute a different city, invent an airport code, or show an empty list."
        ),
    }


async def _trip_currency(
    provider: TravelProvider, context: ToolContext, fallback: dict[str, Any] | None = None
) -> str:
    """The one currency this trip's money is quoted in.

    The *trip's* destination, because that is what the stays are quoted in and a
    trip priced in two currencies cannot be totalled. Dollars when there is no
    destination yet, which is what every caller got before this existed.

    The session's trip rather than the argument-merged one, and that is the
    whole subtlety: pricing the way home means calling `search_flights` with
    `destination: "CPH"`, so a currency read off the merged trip came back as
    kroner for the return of a Berlin trip whose outbound and hotel were both in
    euros. The hop is not the trip.
    """
    where = (context.trip or {}).get("destination") or (fallback or {}).get("destination")
    if not where:
        return "USD"
    resolved = await provider.resolve_destination(str(where))
    return str((resolved or {}).get("currency") or "USD")


def _effective_trip(args: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """The trip a tool should reason about: what is saved, plus what this call says.

    The subtlety is **which stop**. A trip's flat fields describe the first one,
    so pricing any later stop against them quietly used the wrong party size,
    the wrong dates and the wrong departure airport — "New York back to SFO, two
    of us this time" priced one ticket, out of the original origin, on the
    outbound dates, and looked entirely plausible doing it.
    """
    saved = model.normalize(context.trip)
    asked = _str(args.get("destination"))

    stop = None
    if asked:
        # `stops()` resolves each leg against the one before it, so a leg that
        # never said where it departs from arrives here with that filled in.
        for leg in model.stops(saved):
            if leg.get("destination", "").lower() == asked.lower():
                stop = leg
                break

    base = dict(saved)
    if stop:
        base["destination"] = stop["destination"]
        for key in ("origin", "startDate", "endDate", "selectedHotel"):
            if stop.get(key):
                base[key] = stop[key]
        if stop.get("travelers") is not None:
            base["travelers"] = stop["travelers"]

    return model.merge(
        base,
        {
            "destination": args.get("destination"),
            "origin": args.get("origin"),
            "startDate": args.get("date") or args.get("startDate"),
            "endDate": args.get("endDate"),
            "travelers": args.get("travelers"),
            "cabin": args.get("cabin"),
            "maxFare": args.get("maxPrice"),
            "maxNightly": args.get("maxNightly"),
            "neighborhood": args.get("neighborhood"),
        },
    )


def _route_note(saved: dict[str, Any], searched: dict[str, Any]) -> dict[str, Any]:
    """What the route still does not cover, said where it will be read.

    Two facts and their conjunction: where the recorded route ends, and whether
    a hop back to `origin` exists. No opinion about what to do — search it, ask
    whether they are coming back, or record a one-way — which stays with the
    agent, in `prompts/journey.md`.

    It lives on the tool result rather than only in the prompt because that is
    where it works. Measured, three times: the prompt said the route ends in
    Madrid and home is JFK, and the agent read it, answered "here are the
    *outbound* flights" — so it knew — and moved on to hotels, with the
    traveller still in Madrid. A line arriving with the fares, at the moment it
    is deciding what to draw, is a different thing from a line in a system
    instruction thirteen thousand tokens earlier.
    """
    home = saved.get("origin")
    if not home or not saved.get("endDate") or "return" in set(saved.get("skip") or []):
        return {}

    hops = model.journey(saved)
    landing = hops[-1]["to"] if hops else saved.get("destination")
    if not landing or landing == home:
        return {}

    # The hop just priced may itself be the way home, in which case there is
    # nothing to point out — they are pricing it right now.
    if (searched.get("destination") or "").upper() == home.upper():
        return {}

    return {
        "routeNote": (
            f"These are the fares for one hop. The recorded route ends at {landing} and "
            f"home is {home}; the trip ends {saved['endDate']} and no hop from {landing} "
            f"back to {home} is recorded, so as it stands the journey does not come back. "
            f"Price that hop too and offer both in the same surface, or ask whether they "
            f"are coming back — do not move on to stays with it unsettled."
        )
    }


def _priced_for(
    items: list[dict[str, Any]],
    *,
    each: str,
    count: int | None,
    unit: str,
    whole: str,
    currency: str = "USD",
) -> list[dict[str, Any]]:
    """Every option, with what it costs *this* party as well as what it costs one.

    A fare is per traveller and a nightly rate is per night, and neither said so.
    The card showed `$352` beside a trip for two, and `$200 / night` beside seven
    nights — both correct, both read as the total, and both out by a factor the
    traveller only discovers at the summary. The number they are choosing between
    should be the number they are going to pay.

    So each option carries three things: what one costs (`price`, unchanged),
    what the whole of it costs (`total`), and `priceLabel` — the two of them in
    one string, ready to bind to a card's `price`. With a party of one and a
    single night there is nothing to multiply, and the label is just the price:
    "$352 each · $352 for 1" is noise.
    """
    if not count or count < 1:
        return items

    out: list[dict[str, Any]] = []
    for item in items:
        value = _num(item.get(each))
        if value is None:
            out.append(item)
            continue
        total = value * count
        out.append(
            {
                **item,
                "perUnit": _money_text(value, currency),
                "units": count,
                "total": _money_text(total, currency),
                "totalValue": model._js_round(total),
                "priceLabel": (
                    f"{_money_text(value, currency)} {unit} · "
                    f"{_money_text(total, currency)} {whole}"
                    if count > 1
                    else _money_text(value, currency)
                ),
            }
        )
    return out


def _nights_between(start: Any, end: Any) -> int:
    """Nights between two ISO dates, or 0 when either is missing or wrong-way."""
    if not isinstance(start, str) or not isinstance(end, str):
        return 0
    try:
        first = _dt.date.fromisoformat(start[:10])
        last = _dt.date.fromisoformat(end[:10])
    except ValueError:
        return 0
    return max(0, (last - first).days)


def _estimate(
    destination: str,
    travelers: int | None,
    nights: int | None,
    flight_price: float | None,
    nightly_price: float | None,
    legs: list[dict[str, Any]] | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """What a trip comes to, line by line.

    Arithmetic over numbers the caller already has, so it queries nothing and
    stays here rather than behind the provider interface.

    **A trip with stops is costed stop by stop.** This used to take one fare,
    one party size and one destination and multiply: a San Francisco → Chicago →
    New York → home trip where a second person joins in Chicago came out as one
    hop for one person, and the total was confidently, invisibly wrong. Every
    hop has its own ticket and its own number of people on it; every stop that
    needs a bed has its own nights. So each is a line, and the total is their
    sum.

    A single-stop trip produces exactly what it did before, which is what keeps
    the goldens meaningful.
    """
    from ..providers.fixture import _js_round, _money, _rng, _seed, code_for_seed

    # The trip's own currency, because the stays are quoted in it. Totalling a
    # "€112 / night" card as "$336" is the whole reason this is a parameter.
    people = max(1, travelers or 2)
    stay_nights = max(1, nights or 5)
    # Seeded on the resolved airport code, not the text. "Madrid", "madrid" and
    # "MAD" are one destination, and seeding on the spelling gives each of them
    # its own set of plausible prices for the same trip.
    code = code_for_seed(destination)
    random = _rng(_seed(f"estimate-{code}-{people}-{stay_nights}"))

    fallback_fare = 380 + random() * 180
    fallback_nightly = 140 + random() * 90

    hops = list(legs or [])
    if len(hops) > 1:
        # Stop by stop. Each hop's own fare and its own party; each stop's own
        # nights, and only where somebody is actually sleeping.
        flight = 0.0
        stay = 0.0
        food = 0.0
        lines = []
        for index, leg in enumerate(hops):
            party = max(1, int(leg.get("travelers") or people))
            fare = leg.get("flightPrice")
            fare = float(fare) if fare is not None else (
                float(flight_price) if index == 0 and flight_price is not None else fallback_fare
            )
            leg_flight = fare * party
            flight += leg_flight
            lines.append(
                {
                    "label": (
                        f"{leg.get('origin') or '?'} → {leg.get('destination') or '?'} "
                        f"({party} traveler{'' if party == 1 else 's'})"
                    ),
                    "amount": _money(leg_flight, currency),
                    "note": "fare" if leg.get("flightPrice") is not None else "estimated",
                }
            )

            leg_nights = _nights_between(leg.get("startDate"), leg.get("endDate"))
            if leg.get("needsStay") is False or not leg_nights:
                continue
            rate = leg.get("nightlyPrice")
            rate = float(rate) if rate is not None else (
                float(nightly_price) if index == 0 and nightly_price is not None else fallback_nightly
            )
            leg_stay = rate * leg_nights
            stay += leg_stay
            food += 55 * party * leg_nights
            lines.append(
                {
                    "label": (
                        f"{leg.get('destination')}, {leg_nights} "
                        f"night{'' if leg_nights == 1 else 's'}"
                    ),
                    "amount": _money(leg_stay, currency),
                    "note": "nightly rate" if leg.get("nightlyPrice") is not None else "estimated",
                }
            )

        nights_total = sum(
            _nights_between(leg.get("startDate"), leg.get("endDate"))
            for leg in hops
            if leg.get("needsStay") is not False
        )
        food = food or 55 * people * (nights_total + 1)
        local = 24 * (nights_total + len(hops))
        lines.append({"label": "Food and drink", "amount": _money(food, currency), "note": "estimated"})
        lines.append(
            {"label": "Local transport", "amount": _money(local, currency), "note": "metro and taxis"}
        )
        total = flight + stay + food + local
        return {
            "lines": lines,
            "total": _money(total, currency),
            "totalValue": model._js_round(total),
            "currency": currency,
        }

    flight = (flight_price if flight_price is not None else fallback_fare) * people
    stay = (nightly_price if nightly_price is not None else fallback_nightly) * stay_nights
    food = 55 * people * (stay_nights + 1)
    local = 24 * (stay_nights + 1)

    lines = [
        {
            "label": f"Flights ({people} traveler{'' if people == 1 else 's'})",
            "amount": _money(flight, currency),
        },
        {
            "label": f"Stay ({stay_nights} night{'' if stay_nights == 1 else 's'})",
            "amount": _money(stay, currency),
        },
        {"label": "Food and drink", "amount": _money(food, currency), "note": "estimated"},
        {"label": "Local transport", "amount": _money(local, currency), "note": "metro and taxis"},
    ]
    total = flight + stay + food + local
    return {
        "lines": lines,
        "total": _money(total, currency),
        "totalValue": model._js_round(total),
        "currency": currency,
    }


def _day_text(value: Any) -> str:
    """A date as a reader says it — "12 Apr" — rather than as it is stored.

    The stored form is ISO because everything downstream sorts and compares it.
    A page somebody reads is the one place that stops being the right shape.
    """
    if not isinstance(value, str):
        return ""
    try:
        when = _dt.date.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{when.day} {when.strftime('%b')}"


#: The symbol for each currency the fixtures quote in.
#:
#: A total printed in the wrong currency is worse than no total: "$847" under a
#: list of "€121 / night" cards is a figure nobody can act on and everybody
#: believes. Anything not named here keeps its ISO code, which is ugly and
#: honest.
_SYMBOLS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5"}


def _money_text(value: Any, currency: str = "USD") -> str:
    """A figure as a reader sees it, without importing the fixture's formatter."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    symbol = _SYMBOLS.get((currency or "USD").upper())
    figure = f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
    return f"{symbol}{figure}" if symbol else f"{figure} {currency.upper()}"
