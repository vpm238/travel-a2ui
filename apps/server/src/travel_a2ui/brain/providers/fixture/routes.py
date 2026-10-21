"""Which airline flies this, and whether it has to stop on the way.

A fare is only believable if the carrier is one that flies the route and the
stopover is somewhere it actually goes. So carriers carry their hubs and their
range, and a connection is chosen from the hubs of the carrier that is flying
it — TAP via Lisbon, Air France via Paris — rather than from a list of plausible
airports.
"""

from __future__ import annotations

import math

from typing import Any, Callable

from .numbers import _pick
from .tables import _AIRLINES, _CONNECTIONS, _HUBS, _PLACE

def _distance_km(origin: str, destination: str) -> float | None:
    """Great-circle kilometres between two airports we know.

    `None` when either is unknown, so every caller has to say what it does
    without geography rather than quietly pretending the distance is zero.
    """

    a, b = _PLACE.get(origin), _PLACE.get(destination)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def _hubs_on_the_way(origin: str, destination: str) -> list[str]:
    """Hubs a flight between these two could plausibly stop at.

    Split out of `_connection` so a carrier's connection can go through a hub
    that carrier actually has. Pairing them at random is a third of why the
    fixtures read as invented: "1 stop · CDG" on Iberia, "1 stop · LIS" on
    Delta. Now TAP connects in Lisbon and Air France in Paris, because that is
    where their aircraft are.
    """
    direct = _distance_km(origin, destination)
    candidates = [
        hub
        for hubs in _HUBS.values()
        for hub in hubs
        if hub not in (origin, destination) and hub in _PLACE
    ]
    if not direct:
        pool = sorted(hub for hub in candidates if hub not in (origin, destination))
        return pool or sorted(_CONNECTIONS)

    detours: list[tuple[float, str]] = []
    for hub in candidates:
        first, second = _distance_km(origin, hub), _distance_km(hub, destination)
        if first is None or second is None:
            continue
        detours.append(((first + second) / max(direct, 1.0), hub))
    # A quarter over the direct distance is about where a real connection stops
    # being worth it, and it is tight enough to rule out the ones that fly
    # backwards: San Francisco to Tokyo via Denver is only a third longer and is
    # still pointed the wrong way.
    return sorted(hub for ratio, hub in detours if ratio <= 1.25)


def _carriers_for(origin: str, destination: str, km: float | None) -> list[dict[str, Any]]:
    """The carriers that fly this route, and how.

    Each entry is the carrier with the two things the schedule needs: whether it
    can fly the route nonstop — one end is one of its hubs — and which of its
    own hubs it could route a connection through.

    This is what stopped Copenhagen to Berlin coming back on Air France, KLM
    and TAP Air Portugal. All three are European; none of them flies it. SAS and
    Norwegian are out of Copenhagen and Eurowings is out of Berlin, and those
    are the three you get.
    """
    on_the_way = set(_hubs_on_the_way(origin, destination))
    offered: list[dict[str, Any]] = []
    for carrier in _AIRLINES:
        if carrier["maxKm"] and km and km > carrier["maxKm"]:
            continue
        hubs = set(carrier["hubs"])
        nonstop = bool(hubs & {origin, destination})
        via = sorted(hubs & on_the_way)
        if nonstop or via:
            offered.append({**carrier, "nonstop": nonstop, "via": via})
    return offered


def _connection(origin: str, destination: str, random: Callable[[], float]) -> str | None:
    """Somewhere a flight between these two would plausibly stop, or nothing.

    `None` means no hub is on the way, and the honest answer is then that this
    route does not have a connecting option — which is true of short ones.
    London to Paris is 347 km and every hub that is not London or Paris adds
    more than double the journey; a "1 stop · FRA" on it is not a cheaper
    alternative, it is a joke at the traveller's expense.

    A hub has to be roughly *on the way*. Region alone is not enough: picking
    from the regions at either end still offered San Francisco to Tokyo via New
    York, and New York to Madrid via Los Angeles — both of them flying several
    thousand kilometres backwards before setting off.

    So every hub is scored by how far it drags the journey — the two legs
    against the direct distance — and only those within a reasonable detour are
    candidates. That is also what makes a domestic hop connect domestically,
    without having to say so: Frankfurt is not on the way from San Francisco to
    New York, so it scores itself out.

    A route between airports we have no geography for falls back to every hub we
    know, which is the old behaviour and at least claims nothing.
    """
    near = _hubs_on_the_way(origin, destination)
    return _pick(near, random) if near else None
