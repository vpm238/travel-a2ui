"""A panel that failed to draw must not be reported as drawn.

Found on the deployed app, on the turn that books the hotel. The trip had
`selectedHotel` on it — the server said so when asked — and the panel beside the
conversation still read "Stay in Berlin · Awaiting selection", "STAYS 0 of 1".
Asking that same session for a fresh sidebar drew the hotel immediately, so
nothing was wrong with the trip or with the brief: the panel had simply never
been redrawn for it, and nothing was ever going to redraw it.

Two things had to be true at once for that to happen, and both were:

  * the rebuild reports the shape it *attempted*, not the shape it reached, so
    a draw that came back empty — the panel model busy, the block not
    compiling — still wrote "panels are current as of S2" into the session and
    into the client's receipt. The next turn compares the trip to S2, sees no
    change, and declines to rebuild. One turn stale becomes stale for good.

  * the client's own catch-up, which exists for exactly this, could never fire.
    It marked the panel current on any event for a standing surface, and the
    host sends one of those every turn — `panel_events`, which pushes values
    into the panels and draws nothing.

Either one alone would have caught it. This file holds the server half; the
client half is `redrawsSurface` in `conversation.ts`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from travel_a2ui.brain import trip as model
from travel_a2ui.doors.interactions import TurnRequest
from travel_a2ui.doors.interactions.panels import _rebuild_panels

TODAY = "2027-03-01"

BOOKED = {
    "destination": "Madrid",
    "origin": "JFK",
    "startDate": "2027-04-12",
    "endDate": "2027-04-19",
    "travelers": 2,
    "selectedFlight": "IB426",
    "selectedHotel": "h_MAD_1",
}


class Busy:
    """A model that is not there — the failure this is all about.

    Shaped like the SDK client the panel path calls, the same way `FakeModel`
    in `test_interactions` is, and it refuses the way the real one does when
    Google is at capacity. Measured on the eval that settled the defaults:
    twelve of thirty-six turns came back exactly like this.
    """

    def __init__(self) -> None:
        self.asked = 0

    @property
    def aio(self):  # noqa: ANN201 - shaped like the SDK client, not typed like it
        return self

    @property
    def interactions(self):  # noqa: ANN201
        return self

    async def create(self, **_: Any):  # noqa: ANN201
        self.asked += 1
        raise RuntimeError("the model is currently experiencing high demand")


def rebuild(trip: dict[str, Any], was: str | None, client: Any) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        request = TurnRequest(
            api_key="k",
            model="m",
            trip=dict(trip),
            shape=was,
            client=client,
        )
        return [event async for event in _rebuild_panels(request, dict(trip), TODAY)]

    return asyncio.run(run())


def shape_reported(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "__shape__":
            return event.get("shape")
    raise AssertionError("the rebuild reported no shape at all")


class TestAFailedDrawStaysBehind:
    def test_it_reports_the_shape_it_came_in_on(self) -> None:
        """So the next turn sees a difference, and tries again."""
        was = "something older"
        events = rebuild(BOOKED, was, Busy())
        assert shape_reported(events) == was

    def test_and_draws_nothing(self) -> None:
        """Silently: the traveller's answer already arrived and painted."""
        events = rebuild(BOOKED, "something older", Busy())
        assert [event for event in events if event.get("type") == "ui"] == []

    def test_the_next_turn_therefore_rebuilds(self) -> None:
        """The whole point of the shape it reports.

        A rebuild is skipped when the trip's shape matches the one the panels
        are at. Reporting the attempted shape is what made the second attempt
        never happen.
        """
        busy = Busy()
        first = rebuild(BOOKED, "something older", busy)
        tried = busy.asked
        assert tried, "the first turn never asked for a panel at all"

        # Counted rather than compared to a number: a refused call is retried
        # and then tried on the standby model, so one rebuild is several asks.
        rebuild(BOOKED, shape_reported(first), busy)
        assert busy.asked > tried, "the second turn did not try the panel again"


class TestADeliberateDeclineIsNotAFailure:
    """Two early returns say "there is nothing to draw", and they stay.

    A trip with no destination has no panel worth drawing — "a panel saying no
    trip is a panel nobody wants" — and the panels genuinely are current with
    respect to it. Reporting the old shape there would mean retrying forever.
    """

    def test_nothing_to_draw_reports_the_new_shape(self) -> None:
        empty = {"travelers": 2}
        events = rebuild(empty, "something older", Busy())
        assert shape_reported(events) == model.decision_shape(empty)

    def test_an_unchanged_shape_reports_itself(self) -> None:
        settled = model.decision_shape(BOOKED)
        events = rebuild(BOOKED, settled, Busy())
        assert shape_reported(events) == settled

    def test_neither_asks_the_model_anything(self) -> None:
        busy = Busy()
        rebuild({"travelers": 2}, "older", busy)
        rebuild(BOOKED, model.decision_shape(BOOKED), busy)
        assert busy.asked == 0
