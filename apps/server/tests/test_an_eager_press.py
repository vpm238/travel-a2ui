"""The trip has to survive a traveller who presses before the turn finishes.

The fares are drawn the moment they land — that is the point of the skeleton —
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
