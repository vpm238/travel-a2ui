"""The sentence a card reads as, where the *host* is the one drawing it.

`accessibility.label` is the one property whose absence nothing notices. The
card draws, the screenshot is right, the suite is green, and a traveller using
a screen reader hears "Norwegian DY1234 07:15 CPH 11:40 BER 2h 25m nonstop
€281" — every fact, in no order, the price last.

Naming a card the *agent* composed is the agent's job, taught in the brief and
in the worked examples; a host pass that filled it in was this file's first
answer and the wrong one, because it put a decision about what a card says
into Python. What is left here are the two surfaces the host composes itself
— the tool-built surfaces a voice call draws, and the skeleton painted while
a lookup runs — where the host already authors every other string on the
card and the label is part of the same act.
"""

from __future__ import annotations

from typing import Any

from travel_a2ui.brain.spoken import flight_label, hotel_label, label_for

FARE: dict[str, Any] = {
    "id": "f0",
    "component": "FlightOption",
    "airline": "Norwegian",
    "flightNumber": "DY1234",
    "departTime": "07:15",
    "origin": "CPH",
    "arriveTime": "11:40",
    "destination": "BER",
    "duration": "2h 25m",
    "stops": "1 stop · OSL",
    "price": "€281",
    "action": {"event": {"name": "select_flight", "context": {"id": "DY1234"}}},
}

STAY: dict[str, Any] = {
    "id": "h0",
    "component": "HotelCard",
    "name": "Pension Savignyplatz",
    "neighborhood": "Charlottenburg",
    "rating": "4.3 (612)",
    "price": "€112 / night",
    "action": {"event": {"name": "select_hotel", "context": {"id": "h0"}}},
}


def surface(*components: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "version": "v1.0",
            "createSurface": {
                "surfaceId": "inline-1",
                "catalogId": "https://travel-a2ui.dev/catalogs/a2ui-travel/catalog.json",
                "components": [*components],
            },
        }
    ]


def labels(messages: list[dict[str, Any]]) -> list[Any]:
    body = messages[0]["createSurface"]
    return [(node.get("accessibility") or {}).get("label") for node in body["components"]]


class TestTheSentence:
    def test_a_fare_reads_as_one(self) -> None:
        assert flight_label(FARE) == (
            "Norwegian DY1234, 07:15 CPH to 11:40 BER, 1 stop via OSL, €281"
        )

    def test_the_visual_separator_becomes_a_word(self) -> None:
        """`1 stop · OSL` read aloud is a character or a silence.

        And "1 stop, OSL" sounds like two separate facts, which is why this is
        not simply a comma.
        """
        assert "via OSL" in flight_label(FARE)
        assert "·" not in flight_label(FARE)

    def test_nonstop_is_left_alone(self) -> None:
        assert "Nonstop" in flight_label({**FARE, "stops": "Nonstop"})

    def test_the_party_pays_the_total_not_the_fare(self) -> None:
        """A leg carrying two shows both numbers; one of them is the price.

        Reading only `price` would present the per-traveller fare as the price,
        which is the mistake the card itself was changed to stop making.
        """
        reads = flight_label({**FARE, "total": "€562 for 2"})
        assert "€562 for 2" in reads
        assert "€281" not in reads

    def test_a_stay_reads_as_one(self) -> None:
        assert hotel_label(STAY) == (
            "Pension Savignyplatz, Charlottenburg, rated 4.3 (612), €112 / night"
        )

    def test_a_bound_field_is_left_out_rather_than_invented(self) -> None:
        """A binding has no value here — it resolves in the renderer."""
        reads = flight_label({**FARE, "stops": {"@path": "/trip/legs/0/stops"}})
        assert reads == "Norwegian DY1234, 07:15 CPH to 11:40 BER, €281"

    def test_one_clause_is_worse_than_no_label(self) -> None:
        """`aria-label` replaces the card's text; it does not add to it.

        A panel card with everything bound but the price would otherwise be
        announced as "€281" and nothing else.
        """
        mostly_bound = {
            "component": "FlightOption",
            "airline": {"@path": "/trip/legs/0/airline"},
            "price": "€281",
        }
        assert flight_label(mostly_bound) == ""

    def test_nothing_is_said_about_a_card_that_reads_as_a_sentence(self) -> None:
        """A `StatTile` is a label and a value. It does not need this."""
        assert label_for("StatTile", {"label": "Nights", "value": "6"}) == ""
        assert label_for("Text", {"text": "Prices are per traveller."}) == ""


class TestTheSkeleton:
    """The cards a traveller sees first, and often presses.

    The host paints these the moment a lookup starts and fills them from the
    data model when it lands — no recompile, no second component send, which is
    what makes them nearly free. It also means every value on them is a
    binding, so the label cannot be a literal and cannot be a `$` path either:
    the catalog marks `accessibility` static. It is a `formatString` over one
    field the fill writes, which is also why it reads as nothing while the row
    is still blank.
    """

    def pending(self):
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.skeleton import pending_surface_for

        found = pending_surface_for("search_flights", "inline-1", parser_for("inline-1"))
        assert found is not None, "the skeleton did not compile"
        return found

    def cards(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for message in messages:
            for key in ("createSurface", "updateComponents"):
                body = message.get(key)
                if isinstance(body, dict):
                    out.extend(
                        node
                        for node in body.get("components") or []
                        if node.get("component") == "FlightOption"
                    )
        return out

    def test_the_card_asks_for_a_sentence_it_does_not_have_yet(self) -> None:
        card = self.cards(self.pending().opening)[0]
        assert card["accessibility"]["label"] == {
            "@call": "formatString",
            "args": {"value": "${reads}"},
        }

    def test_the_fill_writes_the_sentence_beside_the_row(self) -> None:
        filled = self.pending().fill(
            {
                "flights": [
                    {
                        "id": "DY1234",
                        "airline": "Norwegian",
                        "flightNumber": "DY1234",
                        "departTime": "07:15",
                        "origin": "CPH",
                        "arriveTime": "11:40",
                        "destination": "BER",
                        "stops": "Nonstop",
                        "price": "€281",
                    }
                ]
            }
        )
        assert filled is not None
        rows = filled[0]["updateDataModel"]["value"]
        assert rows[0]["reads"] == "Norwegian DY1234, 07:15 CPH to 11:40 BER, Nonstop, €281"
        # And the provider's own fields are untouched beside it.
        assert rows[0]["price"] == "€281"

    def test_a_row_too_thin_to_describe_gets_no_sentence(self) -> None:
        """Rather than a field holding punctuation for the renderer to read."""
        filled = self.pending().fill({"flights": [{"id": "X", "price": "€281"}]})
        assert filled is not None
        assert "reads" not in filled[0]["updateDataModel"]["value"][0]

    def test_the_blank_rows_say_nothing(self) -> None:
        """`${reads}` over an empty row resolves to "", which the renderer drops.

        Which is the point of putting it in one field rather than interpolating
        six: a template spelling out every field would read ",  to , ," for the
        second the skeleton is on screen with nothing in it.
        """
        seed = next(
            message
            for message in self.pending().opening
            if "updateDataModel" in message or "dataModel" in message.get("createSurface", {})
        )
        blanks = (
            seed.get("updateDataModel", {}).get("value")
            or seed["createSurface"]["dataModel"]["flights"]
        )
        assert blanks, "no blank rows to check"
        assert all("reads" not in row for row in blanks)
