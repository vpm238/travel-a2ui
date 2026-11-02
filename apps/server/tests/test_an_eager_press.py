"""The trip has to survive a traveller who presses before the turn finishes.

The fares are drawn the moment they land — a card bound to where the host files
the rows fills in as they arrive —
so the obvious thing to do is press one straight away, while the turn is still
running its sidebar rebuild. Doing that aborted the stream, and everything that
remembered the trip was written *after* that rebuild: the receipt the client
sends back, and this instance's own session. Neither landed. The next turn ran
against an empty trip and the agent asked for the route, the dates and the party
again — all of which were on screen at the time, in a sidebar the turn before
had drawn.

Reproduced through the real browser against the deployed service: the press went
out with `resume.trip: null` and an `interactionId` from the *warm-up*, which
carries no trip at all.
"""

from __future__ import annotations

import asyncio
from typing import Any

from travel_a2ui.doors.interactions import TurnRequest, run_turn


def _events(request: TurnRequest) -> list[dict[str, Any]]:
    async def drain() -> list[dict[str, Any]]:
        return [event async for event in run_turn(request)]

    return asyncio.run(drain())


class TestTheReceiptComesBeforeThePanels:
    """`__result__` is what the door turns into a receipt and a session write."""

    def test_the_receipt_is_handed_over_before_the_turn_is_called_done(self) -> None:
        from test_interactions import ASKING, FakeModel, base  # noqa: PLC0415

        events = _events(base(message="a week in Madrid", client=FakeModel([([ASKING], [])])))
        kinds = [event["type"] for event in events]

        assert "__result__" in kinds, "nothing was ever handed back"
        assert kinds.index("__result__") < kinds.index("done"), (
            "the receipt lands after the turn is finished, so a press that "
            "interrupts the tail loses the trip"
        )

    def test_and_it_carries_the_trip(self) -> None:
        from test_interactions import ASKING, FakeModel, base  # noqa: PLC0415

        events = _events(
            base(
                message="a week in Madrid",
                client=FakeModel([([ASKING], [])]),
                trip={"destination": "Madrid", "startDate": "2027-04-12"},
            )
        )
        first = next(event for event in events if event["type"] == "__result__")
        assert first["result"].trip["destination"] == "Madrid"
        assert first["result"].trip["startDate"] == "2027-04-12"

    def test_a_turn_still_ends_with_one(self) -> None:
        # The second carries the panel shape, which is only known after the
        # rebuild. A client that reads to the end gets the better receipt; one
        # that presses early already has a usable one.
        from test_interactions import ASKING, FakeModel, base  # noqa: PLC0415

        events = _events(base(message="a week in Madrid", client=FakeModel([([ASKING], [])])))
        results = [event for event in events if event["type"] == "__result__"]
        assert len(results) >= 2, "the end-of-turn receipt went missing"
        assert results[-1]["result"].trip == results[0]["result"].trip


class TestTheSessionIsWrittenAsTheTripMoves:
    def test_the_door_saves_on_every_trip_event(self) -> None:
        # Read off the door rather than mocked: the save has to sit on the
        # `trip` event, which arrives while the turn is still streaming, not
        # only on the receipt at the end.
        import inspect

        from travel_a2ui.doors import http

        source = inspect.getsource(http)
        relay = source[source.index("async for event in run_turn(turn):") :]
        assert 'if event["type"] == "trip"' in relay
        assert "sessions.save(session_id, trip=event[\"trip\"])" in relay


class TestAPressGetsItsPanelRowStraightAway:
    """The replay fires on the press that added the row, not a turn later.

    `panels()` asks "is the panel drawn for a different set of rows than the
    trip now has". The baseline has to be what the *panel* was drawn for —
    `request.shape`, the receipt the client sends back. Baselining on the trip
    instead reads it after the press has already been committed, so the one
    change the replay exists for is invisible and it never fires.
    """

    def test_the_baseline_is_what_the_panel_was_drawn_for(self) -> None:
        import inspect

        from travel_a2ui.doors.interactions import turn as door

        body = inspect.getsource(door.run_turn)
        start = body.index("shape_was = ")
        assigned = body[start : body.index("\n", start)]
        assert "request.shape" in assigned, (
            "the replay is baselined on the trip, so a press's own row never "
            f"triggers it: {assigned.strip()}"
        )

    def test_and_a_press_that_adds_a_row_replays_the_panel(self) -> None:
        """End to end through the turn loop: press a fare, watch the panel gain its row."""
        from test_interactions import SURFACE, FakeModel, base  # noqa: PLC0415
        from travel_a2ui.brain import trip as model
        from travel_a2ui.brain.finishing import STANDING_SURFACES
        from travel_a2ui.doors.interactions.press import SurfaceAction

        composed = 'surface("sidebar")\npanel = Trip("Trip to Berlin")\nroot = Column([panel])'
        before = {
            "origin": "CPH",
            "destination": "Berlin",
            "startDate": "2026-11-09",
            "endDate": "2026-11-12",
            "travelers": 2,
        }
        request = base(
            trip=before,
            client=FakeModel([([SURFACE], [])]),
            action=SurfaceAction(
                name="select_flight",
                surface_id="inline-2",
                context={
                    "id": "EW8405",
                    "price": 74,
                    "airline": "Eurowings",
                    "departTime": "10:45",
                    "arriveTime": "12:15",
                },
            ),
        )
        # The panel as it stands: drawn for a trip with no fare chosen.
        request.shape = model.decision_shape(model.normalize(before))
        request.panels = {"sidebar": composed}

        events = _events(request)
        panel = [
            event
            for event in events
            if event.get("type") == "ui" and event.get("surfaceId") in STANDING_SURFACES
        ]
        assert panel, "the panel was never redrawn for the row the press added"
        kinds = [
            component["component"]
            for event in panel
            for message in event["messages"]
            if message.get("createSurface")
            for component in message["createSurface"]["components"]
        ]
        assert "FlightOption" in kinds, f"the replayed panel has no fare row: {kinds}"

    def test_but_not_when_the_panel_is_already_current(self) -> None:
        """A price or a date moving is data. Replaying components for it is waste."""
        from test_interactions import SURFACE, FakeModel, base  # noqa: PLC0415
        from travel_a2ui.brain import trip as model
        from travel_a2ui.brain.finishing import STANDING_SURFACES

        settled = {
            "origin": "CPH",
            "destination": "Berlin",
            "startDate": "2026-11-09",
            "endDate": "2026-11-12",
            "travelers": 2,
        }
        request = base(trip=settled, client=FakeModel([([SURFACE], [])]), message="who else is coming?")
        request.shape = model.decision_shape(model.normalize(settled))
        request.panels = {
            "sidebar": 'surface("sidebar")\npanel = Trip("Trip to Berlin")\nroot = Column([panel])'
        }

        events = _events(request)
        redrawn = [
            event
            for event in events
            if event.get("type") == "ui"
            and event.get("surfaceId") in STANDING_SURFACES
            and any(message.get("createSurface") for message in event["messages"])
        ]
        assert not redrawn, f"the panel was replayed for a change that was only data: {redrawn}"
