"""A whole turn, driven off a scripted model stream.

No key and no network: the model is a fake that yields exactly the events a
real one would. What is asserted is what goes wrong in this loop without
throwing: order, and who decided what.

  - prose and A2UI come out separately, and the A2UI is expanded and valid;
  - a lookup's rows go into the data model of this turn's surface, where a
    macro the model drew is bound, and the model is told where they are;
  - what the traveller pressed and changed on screen is on the trip before
    the model is asked anything;
  - a refused block, a surface that cannot be answered, a fenced block and a
    promise with nothing drawn are each handed back to the model, once;
  - a turn that ends with a trip and no panel asks the model for one.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from helpers import ASKING, SETTLED, FakeModel, base, events_of, messages_of, said_to_model

from travel_a2ui.brain import data
from travel_a2ui.brain.inbound import RendererError, SurfaceAction
from travel_a2ui.brain.ui import Canvas, Drawing
from travel_a2ui.doors.interactions import MAX_TOOL_ROUNDS, run_turn_collected
from travel_a2ui.gemini import ToolCall

FLIGHTS = (
    "<a2ui>\n"
    'heading = Text("### Outbound · JFK → MAD")\n'
    'fares = Flights(_, "/trip/selectedFlight")\n'
    "root = Column([heading, fares])\n"
    "</a2ui>"
)

SEARCH = ToolCall(
    id="c1",
    name="search_flights",
    args={"origin": "JFK", "destination": "Madrid", "date": "2027-04-12", "travelers": 2},
)


def a_panel(trip: dict[str, Any] | None = None) -> Canvas:
    """A canvas whose renderer already holds the panel, so no panel turn runs."""
    canvas = Canvas()
    values = lambda _s: data.session_values(trip or {}, None)  # noqa: E731
    Drawing(canvas, "sidebar", values).feed('<a2ui>\nsurface("sidebar")\np = Trip()\nroot = Column([p])\n</a2ui>')
    return canvas


class TestTheStream:
    def test_prose_and_a2ui_come_out_separately(self) -> None:
        events = events_of(base(message="hi", client=FakeModel([(["Here you go.\n", ASKING], [])])))
        text = "".join(event["delta"] for event in events if event["type"] == "text")
        assert "Here you go." in text and "<a2ui>" not in text and "DateRangePicker" not in text
        created = [m["createSurface"] for m in messages_of(events) if "createSurface" in m]
        assert created and created[0]["surfaceId"] == "inline-1"
        assert created[0]["sendDataModel"] is True

    def test_a_surface_paints_before_the_turn_ends(self) -> None:
        events = events_of(base(message="hi", client=FakeModel([([ASKING], [])])))
        kinds = [event["type"] for event in events]
        assert kinds.index("ui") < kinds.index("done")

    def test_a_macro_reaches_the_renderer_expanded(self) -> None:
        events = events_of(
            base(message="hi", trip=dict(SETTLED), client=FakeModel([([FLIGHTS], [])]), canvas=a_panel())
        )
        components = {
            c["component"]
            for m in messages_of(events, "inline-1")
            for c in (m.get("createSurface") or {}).get("components", [])
        }
        assert "Flights" not in components and {"List", "FlightOption"} <= components

    def test_the_controls_are_filled_from_the_record(self) -> None:
        events = events_of(base(message="hi", trip=dict(SETTLED), client=FakeModel([([ASKING], [])]), canvas=a_panel()))
        filled = {
            m["updateDataModel"]["path"]: m["updateDataModel"]["value"]
            for m in messages_of(events, "inline-1")
            if "updateDataModel" in m
        }
        assert filled["/trip/startDate"] == "2027-04-12"
        assert filled["/trip/travelers"] == 2

    def test_run_turn_collected_gathers_the_same_turn(self) -> None:
        collected = asyncio.run(run_turn_collected(base(message="hi", client=FakeModel([(["Hi.", ASKING], [])]))))
        assert collected["text"] == "Hi."
        assert any("createSurface" in message for message in collected["ui"])


class TestALookupFillsTheCardItsModelDrew:
    def turn(self) -> tuple[list[dict[str, Any]], FakeModel]:
        model = FakeModel([([FLIGHTS], [SEARCH]), (["Four fares."], [])])
        return events_of(base(message="flights", trip=dict(SETTLED), client=model, canvas=a_panel())), model

    def test_the_rows_land_where_the_macro_is_bound(self) -> None:
        events, _ = self.turn()
        rows = [
            m["updateDataModel"]
            for m in messages_of(events, "inline-1")
            if "updateDataModel" in m and m["updateDataModel"]["path"] == "/flights"
        ]
        assert rows and rows[0]["value"] and rows[0]["value"][0]["airline"]

    def test_and_the_model_is_told_where_rather_than_handed_them(self) -> None:
        _, model = self.turn()
        result = next(item for item in model.bodies[1]["input"] if item.get("type") == "function_result")
        answer = json.loads(result["result"][0]["text"])
        assert isinstance(answer["flights"], str) and "/flights" in answer["flights"]


class TestWhatTheTravellerDid:
    def test_a_press_is_on_the_trip_before_the_model_is_asked(self) -> None:
        action = SurfaceAction(
            name="select_flight",
            surface_id="inline-2",
            context={"id": "IB6250", "price": 412, "airline": "Iberia", "from": "JFK", "to": "MAD"},
            user_message="Chose Iberia",
        )
        model = FakeModel([(["Good choice."], [])])
        events = events_of(base(action=action, trip=dict(SETTLED), client=model, canvas=a_panel()))
        result = next(event for event in events if event["type"] == "__result__")["result"]
        assert result.trip["selectedFlight"] == "IB6250"
        assert "select_flight" in said_to_model(model, 0) and "Chose Iberia" in said_to_model(model, 0)

    def test_what_they_changed_on_a_form_is_committed(self) -> None:
        canvas = a_panel()
        values = lambda _s: data.session_values({}, None)  # noqa: E731
        Drawing(canvas, "inline-1", values).feed(ASKING)
        canvas.provide(values)
        action = SurfaceAction(name="find_flights", surface_id="inline-1")
        reported = {"inline-1": {"trip": {"startDate": "2027-05-01", "endDate": "2027-05-08", "travelers": 3}}}
        events = events_of(
            base(
                action=action,
                data_model=reported,
                trip={"destination": "Madrid"},
                client=FakeModel([([""], [])]),
                canvas=canvas,
            )
        )
        trip = next(event for event in events if event["type"] == "__result__")["result"].trip
        assert (trip["startDate"], trip["endDate"], trip["travelers"]) == ("2027-05-01", "2027-05-08", 3)

    def test_a_value_the_record_refuses_is_said(self) -> None:
        canvas = a_panel()
        model = FakeModel([(["ok"], [])])
        reported = {"inline-1": {"trip": {"startDate": "2027-05-08", "endDate": "2027-05-01"}}}
        values = lambda _s: data.session_values({}, None)  # noqa: E731
        Drawing(canvas, "inline-1", values).feed(ASKING)
        events_of(
            base(
                action=SurfaceAction(name="find_flights", surface_id="inline-1"),
                data_model=reported,
                client=model,
                canvas=canvas,
            )
        )
        assert "Refused" in said_to_model(model, 0)

    def test_a_renderer_error_reaches_the_model(self) -> None:
        model = FakeModel([(["Sorry."], [])])
        error = RendererError(
            code="VALIDATION_FAILED", message="bad child", surface_id="inline-1", path="/components/0"
        )
        events_of(base(message="hi", errors=[error], client=model, canvas=a_panel()))
        assert "VALIDATION_FAILED" in said_to_model(model, 0)


class TestHandedBackOnce:
    def test_a_refused_block_is_explained_and_retried(self) -> None:
        broken = '<a2ui>\nroot = Text("hi", nonsense=3)\n</a2ui>'
        model = FakeModel([([broken], []), ([ASKING], []), ([broken], [])])
        events = events_of(base(message="hi", client=model, canvas=a_panel()))
        assert len(model.bodies) == 2, "retried once, and not again"
        assert "refused" in said_to_model(model, 1)
        assert any(event["type"] == "ui_error" for event in events)

    def test_a_fenced_surface_is_retried(self) -> None:
        fenced = '```json\n{"surfaceId": "inline-1", "components": []}\n```'
        model = FakeModel([([fenced], []), ([ASKING], [])])
        events = events_of(base(message="hi", client=model, canvas=a_panel()))
        text = "".join(event["delta"] for event in events if event["type"] == "text")
        assert "surfaceId" not in text, "JSON reached the traveller as prose"
        assert len(model.bodies) == 2

    def test_a_surface_that_cannot_be_answered_is_reported(self) -> None:
        bad = (
            '<a2ui>\nsurface("inline-1", sendDataModel=true)\n'
            'd = TextField("When?", $/trip/startDate)\nroot = Column([d])\n</a2ui>'
        )
        model = FakeModel([([bad], []), ([""], [])])
        events_of(base(message="hi", client=model, canvas=a_panel()))
        assert len(model.bodies) == 2
        assert "DateRangePicker" in said_to_model(model, 1)

    def test_a_promise_with_nothing_drawn_is_nudged_once(self) -> None:
        model = FakeModel([(["Let me find some flights for you."], []), (["Let me look."], [])])
        events_of(base(message="flights", client=model, canvas=a_panel()))
        assert len(model.bodies) == 2

    def test_a_turn_that_drew_is_left_alone(self) -> None:
        model = FakeModel([(["Let me know what you think.", ASKING], [])])
        events_of(base(message="hi", client=model, canvas=a_panel()))
        assert len(model.bodies) == 1


class TestThePanel:
    def test_a_trip_with_no_panel_asks_for_one_after_the_answer(self) -> None:
        panel = '<a2ui>\nsurface("sidebar")\np = Trip("Your trip")\nroot = Column([p])\n</a2ui>'
        model = FakeModel([(["Madrid."], []), ([panel], [])])
        events = events_of(base(message="hi", trip=dict(SETTLED), client=model))
        kinds = [event["type"] for event in events]
        sidebar = [i for i, e in enumerate(events) if e["type"] == "ui" and e["surfaceId"] == "sidebar"]
        assert sidebar and sidebar[0] > kinds.index("done"), "the panel waits for the answer"
        assert len(model.bodies) == 2

    def test_a_panel_on_screen_is_not_drawn_again(self) -> None:
        model = FakeModel([(["Madrid."], []), (["unexpected"], [])])
        events_of(base(message="hi", trip=dict(SETTLED), client=model, canvas=a_panel()))
        assert len(model.bodies) == 1

    def test_no_trip_no_panel(self) -> None:
        model = FakeModel([(["Where to?"], [])])
        events_of(base(message="hi", client=model))
        assert len(model.bodies) == 1

    def test_a_decision_reaches_a_panel_on_screen_as_data(self) -> None:
        canvas = a_panel(SETTLED)
        canvas.provide(lambda _s: data.session_values(SETTLED, None))
        save = ToolCall(id="s1", name="save_trip", args={"travelers": 3})
        model = FakeModel([([""], [save]), (["Three of you."], [])])
        events = events_of(base(message="three of us", trip=dict(SETTLED), client=model, canvas=canvas))
        panel = [m["updateDataModel"] for m in messages_of(events, "sidebar") if "updateDataModel" in m]
        assert panel and "3 travelling" in json.dumps(panel[-1]["value"])


class TestTheLoopEnds:
    def test_after_the_last_round_it_says_so(self) -> None:
        call = ToolCall(id="g", name="get_trip", args={})
        model = FakeModel([([""], [call])] * MAX_TOOL_ROUNDS)
        events = events_of(base(message="hi", client=model, canvas=a_panel()))
        assert any(event["type"] == "error" and "rounds" in event["message"] for event in events)

    def test_the_receipt_comes_before_done(self) -> None:
        events = events_of(base(message="hi", client=FakeModel([([ASKING], [])])))
        kinds = [event["type"] for event in events]
        assert kinds.index("__result__") < kinds.index("done")


class TestARefusedBlockLeavesNothingBehind:
    def test_a_surface_drawn_beside_a_refused_one_can_be_drawn_again(self) -> None:
        canvas = Canvas()
        values = lambda _s: data.session_values(dict(SETTLED), None)  # noqa: E731
        both = (
            '<a2ui>\nsurface("sidebar")\np = Trip()\nroot = Column([p])\n\n'
            'surface("inline-9")\nt = Text("x")\nroot = Column([t])\n</a2ui>'
        )
        first = Drawing(canvas, "voice-1", values)
        events = [*first.feed(both), *first.close()]
        assert any(event[0] == "rejected" for event in events)
        assert canvas.wire.get_surface("sidebar") is None
        again = Drawing(canvas, "voice-1", values)
        events = [*again.feed('<a2ui>\nsurface("sidebar")\np = Trip()\nroot = Column([p])\n</a2ui>'), *again.close()]
        assert not [event for event in events if event[0] == "rejected"], events
        assert canvas.wire.get_surface("sidebar") is not None


class TestTheStreamAsTheModelSendsIt:
    """Model output arrives in small chunks; the SDK stream must read it as one block."""

    @staticmethod
    def _chunked(text: str, size: int = 7) -> list[tuple]:
        drawing = Drawing(Canvas(), "inline-1", lambda _s: data.session_values({}, None))
        events: list[tuple] = []
        for start in range(0, len(text), size):
            events += drawing.feed(text[start : start + size])
        return events + drawing.close()

    def test_a_root_first_block_is_accepted(self) -> None:
        events = self._chunked('<a2ui>\nroot = Column([a, b])\na = Text("### One")\nb = Text("Two")\n</a2ui>')
        assert not [event for event in events if event[0] == "rejected"]
        sent = [message for event in events if event[0] == "ui" for message in event[2]]
        ids = {
            c["id"]
            for m in sent
            for key in ("createSurface", "updateComponents")
            for c in (m.get(key) or {}).get("components", [])
        }
        assert {"root", "a", "b"} <= ids

    def test_a_mid_stream_error_says_what_was_wrong(self) -> None:
        events = self._chunked('<a2ui>\nroot = Column([a])\na = Text("x", bogus="y")\n</a2ui>')
        reasons = [event[1] for event in events if event[0] == "rejected"]
        assert reasons and "bogus" in reasons[0] and "Text" in reasons[0]


class TestABlockThatDrawsTwoSurfaces:
    def test_each_surface_gets_its_own_event_and_its_own_rows(self) -> None:
        trip = dict(SETTLED)
        canvas = Canvas()
        data.file_rows(canvas.lookups, "search_flights", {"hop": 1}, {"flights": [{"id": "TP1"}]}, trip)

        def values(surface_id: str) -> dict[str, Any]:
            out = data.session_values(trip, None)
            if surface_id in canvas.this_turn:
                out.update(data.turn_values(canvas.lookups, trip))
            return out

        both = (
            '<a2ui>\nsurface("sidebar")\npanel = Trip()\nroot = Column([panel])\n\n'
            'surface("voice-1")\nfares = Flights("Out", "/trip/selectedFlight", hop=1)\n'
            "root = Column([fares])\n</a2ui>"
        )
        drawing = Drawing(canvas, "voice-1", values)
        events = [*drawing.feed(both), *drawing.close()]
        by_surface = {event[1]: event[2] for event in events if event[0] == "ui"}
        assert set(by_surface) == {"sidebar", "voice-1"}
        for surface, messages in by_surface.items():
            assert all(next(iter(m[k] for k in m if k != "version"))["surfaceId"] == surface for m in messages)
        paths = [m["updateDataModel"]["path"] for m in by_surface["voice-1"] if "updateDataModel" in m]
        assert "/fares" in paths
