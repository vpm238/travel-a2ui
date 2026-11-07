"""A second flight needs somewhere to live, and a press has to say where.

Reported as "the return flight in the sidebar does not get populated in the
flow", and it was three faults stacked on one another. The panel was innocent:
give it a trip whose leg carries a flight and it draws both, always did.
"""

from __future__ import annotations

import json
import pathlib

from travel_a2ui.brain import trip as model
from travel_a2ui.doors.interactions import _leg_pressed

ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = json.loads((ROOT / "data" / "tools.json").read_text("utf-8"))


def _save_trip_leg_properties() -> dict:
    tools = TOOLS["tools"] if isinstance(TOOLS, dict) else TOOLS
    save = next(tool for tool in tools if tool["name"] == "save_trip")
    return save["input_schema"]["properties"]["legs"]["items"]["properties"]


class TestTheToolCanRecordIt:
    """The fault underneath the other two.

    `save_trip`'s leg took `selectedHotel` and `nightlyPrice` but no flight at
    all. Measured, the model did everything right and still failed: it put the
    hop in the press, wrote the leg, saved its origin, dates, party, even
    `selectedHotel: ""` — and dropped the one field it was called about,
    because there was nowhere to put it. A rule the schema cannot express is
    not a rule the model can follow.
    """

    def test_a_leg_can_hold_a_flight(self) -> None:
        props = _save_trip_leg_properties()
        assert "selectedFlight" in props, (
            "a hop after the first has no way to record its ticket, so the "
            "return can only overwrite the outbound"
        )
        assert "flightPrice" in props

    def test_it_can_still_hold_a_stay(self) -> None:
        props = _save_trip_leg_properties()
        assert "selectedHotel" in props and "nightlyPrice" in props


class TestThePressSaysWhichHop:
    def test_the_spellings_the_model_actually_uses(self) -> None:
        """Measured across runs: `leg`, `legIndex`, and `hop` counting from one."""
        assert _leg_pressed({"leg": 0, "id": "IB925"}) == 0
        assert _leg_pressed({"legIndex": 1}) == 1
        assert _leg_pressed({"hop": 2}) == 0, "hop two is the second hop, legs[0]"
        assert _leg_pressed({"hopIndex": 1}) == 0

    def test_a_press_about_nothing_in_particular_names_no_hop(self) -> None:
        assert _leg_pressed({"id": "IB925", "price": 286}) is None
        assert _leg_pressed({}) is None
        assert _leg_pressed(None) is None

    def test_a_flag_is_not_an_index(self) -> None:
        """`True` is an `int` in Python, and would read as hop one."""
        assert _leg_pressed({"leg": True}) is None


class TestTheTicketLandsOnTheHop:
    TRIP = {
        "origin": "JFK",
        "destination": "Madrid",
        "selectedFlight": "IB6250",
        "flightPrice": 412,
        "legs": [{"destination": "JFK", "origin": "MAD", "travelers": 2}],
    }

    def test_the_return_does_not_overwrite_the_outbound(self) -> None:
        out = model.onto_leg(self.TRIP, {"selectedFlight": "IB925", "flightPrice": 286}, 0)
        assert out["selectedFlight"] == "IB6250", "the outbound is the first hop's"
        assert out["legs"][0]["selectedFlight"] == "IB925"
        assert out["legs"][0]["flightPrice"] == 286

    def test_what_the_hop_does_not_own_stays_on_the_trip(self) -> None:
        out = model.onto_leg(self.TRIP, {"selectedFlight": "IB925", "budget": 3000}, 0)
        assert out["budget"] == 3000
        assert "budget" not in out["legs"][0]

    def test_a_hop_that_does_not_exist_is_not_invented(self) -> None:
        """A stale button should do nothing, not grow the route."""
        out = model.onto_leg(self.TRIP, {"selectedFlight": "XX1"}, 4)
        assert len(out["legs"]) == 1
        assert out["legs"][0].get("selectedFlight") is None
        assert out["selectedFlight"] == "IB6250"

    def test_a_trip_with_no_legs_at_all_is_left_alone(self) -> None:
        flat = {"origin": "JFK", "destination": "Madrid", "selectedFlight": "IB6250"}
        assert model.onto_leg(flat, {"selectedFlight": "IB925"}, 0) == flat


class TestThePanelIsToldAboutIt:
    """A ticket bought for a hop is a decision, wherever it is recorded.

    The panel binds `/panel`, built from the record hop by hop, so a flight home
    saved on its leg is on the panel's second hop and not the first.
    """

    TRIP = {
        "origin": "CPH",
        "destination": "BER",
        "startDate": "2026-10-12",
        "endDate": "2026-10-15",
        "travelers": 2,
        "selectedFlight": "SK8603",
        "legs": [
            {"origin": "BER", "destination": "CPH", "startDate": "2026-10-15", "travelers": 1}
        ],
    }

    def test_the_flight_home_is_on_the_second_hop(self) -> None:
        from travel_a2ui.brain import data

        after = model.onto_leg(self.TRIP, {"selectedFlight": "DY1242"}, 0)
        hops = data.panel_rows(after)["hops"]
        assert [fare["flightNumber"] for fare in hops[1]["flights"]] == ["DY1242"]
        assert [fare["flightNumber"] for fare in hops[0]["flights"]] == ["SK8603"]

    def test_so_is_a_stay_booked_against_a_hop(self) -> None:
        from travel_a2ui.brain import data

        after = model.onto_leg(self.TRIP, {"selectedHotel": "h_CPH_nyhavn"}, 0)
        assert data.panel_rows(after)["hops"][1]["stays"]


class TestTheHostRecordsTheWholeFareItself:
    """Every fact a press carried, on the hop it belongs to, with no model in it.

    The panel binds a hop's row to `airline`, `departTime`, `arriveTime`,
    `selectedFlight` and `flightPrice`. Measured through Chromium on the return
    hop, only the last two arrived: the panel read

        BER → Copenhagen / SK / SK6955 / BER / Copenhagen / €71.00 / Economy

    against an outbound row carrying the airline, the flight number and both
    times. The macro was binding all five correctly; the trip simply did not
    have three of them, because recording the press was left to the model and it
    saved two of the five.

    `id` and `price` are why. The trip calls them `selectedFlight` and
    `flightPrice`, so `normalize` dropped them and the host could not record the
    press at all — which made the model the only thing that could, and three
    rewrites of that instruction did not make it reliable.
    """

    @staticmethod
    def _pressed(name: str, context: dict, leg: int | None) -> dict:
        from travel_a2ui.doors.interactions.press import (
            SurfaceAction,
            _commit,
            as_trip_fields,
        )
        from travel_a2ui.brain import trip as model

        action = SurfaceAction(name=name, surface_id="inline-3", context=context)
        before = {
            "origin": "CPH",
            "destination": "Berlin",
            "startDate": "2026-11-09",
            "endDate": "2026-11-12",
            "travelers": 2,
            "legs": [
                {
                    "origin": "BER",
                    "destination": "Copenhagen",
                    "startDate": "2026-11-12",
                    "travelers": 1,
                }
            ],
        }
        renamed = {
            **model.normalize(action.context),
            **model.normalize(as_trip_fields(action)),
        }
        proposed = (
            model.onto_leg({**before}, dict(renamed), leg)
            if leg is not None
            else {**before, **renamed}
        )
        trip, _ = _commit(before, proposed, "2026-11-02")
        return trip

    FARE = {
        # An id that is not the flight number, as with any real provider: the
        # fixture's ids are flight-shaped and hid that the panel showed the id.
        "id": "off_2Xq81",
        "price": 71,
        "airline": "SAS",
        "flightNumber": "SK6955",
        "departTime": "12:19",
        "arriveTime": "13:36",
        "hop": 2,
    }

    def test_the_return_hop_gets_all_six_facts(self) -> None:
        leg = self._pressed("select_flight", self.FARE, 0)["legs"][0]
        assert leg["selectedFlight"] == "off_2Xq81"
        assert leg["flightNumber"] == "SK6955"
        assert leg["flightPrice"] == 71
        assert leg["airline"] == "SAS", "the panel's return row has no airline to draw"
        assert leg["departTime"] == "12:19"
        assert leg["arriveTime"] == "13:36"

    def test_and_leaves_the_outbound_alone(self) -> None:
        """The trip's own fields are hop one's. A return must not overwrite them."""
        trip = self._pressed("select_flight", self.FARE, 0)
        for field in ("selectedFlight", "flightNumber", "airline", "departTime", "arriveTime"):
            assert field not in trip, f"the return's {field} landed on the outbound"

    def test_the_first_hop_gets_them_on_the_trip(self) -> None:
        outbound = {k: v for k, v in self.FARE.items() if k != "hop"}
        trip = self._pressed("select_flight", outbound, None)
        assert trip["selectedFlight"] == "off_2Xq81"
        assert trip["flightNumber"] == "SK6955"
        assert trip["airline"] == "SAS"
        assert trip["departTime"] == "12:19"

    def test_a_stay_saves_as_a_stay_and_never_as_a_flight(self) -> None:
        """One shared mapping once told a hotel press to save itself as a flight."""
        stay = {"id": "h_BER_2", "name": "Pension Savignyplatz", "price": 112}
        leg = self._pressed("select_hotel", {**stay, "hop": 2}, 0)["legs"][0]
        assert leg["selectedHotel"] == "h_BER_2"
        assert leg["hotelName"] == "Pension Savignyplatz"
        assert leg["nightlyPrice"] == 112
        assert "selectedFlight" not in leg
        assert "airline" not in leg

    def test_and_the_panel_then_has_every_binding_it_draws(self) -> None:
        """The end of the chain: the row the traveller sees, filled."""
        from travel_a2ui.brain import data

        trip = self._pressed("select_flight", self.FARE, 0)
        hops = data.panel_rows(trip)["hops"]
        assert len(hops) >= 2 and hops[1]["flights"], "the panel has no fare row for the hop"
        row = hops[1]["flights"][0]
        for field in ("airline", "flightNumber", "departTime", "arriveTime", "price"):
            assert row[field], f"the panel's return row has no {field}: {row}"


def test_every_binding_a_hop_draws_is_a_field_a_hop_owns() -> None:
    """`Trip()` and `LEG_OWNED` have to name the same set, or a row draws nothing.

    The two disagreed and neither side could see it. The panel bound a hop's
    row to `legs/0/airline`, `legs/0/departTime` and `legs/0/arriveTime`;
    `LEG_OWNED` did not carry them; `onto_leg` dropped all three on the way in.
    So the field was written correctly, discarded one layer below, and the
    missing row was read as the model failing to save it — through three
    rewrites of that instruction, none of which could have worked.

    Read off what `/panel` actually holds for a settled second hop, so a new
    field on the panel fails this until a press can put it on the hop.
    """
    from travel_a2ui.brain import data

    settled = {
        "origin": "CPH",
        "destination": "Berlin",
        "startDate": "2026-11-09",
        "endDate": "2026-11-12",
        "travelers": 2,
        "selectedFlight": "EW8405",
        "flightPrice": 74,
        "airline": "Eurowings",
        "departTime": "10:45",
        "arriveTime": "12:15",
        "legs": [
            {
                "origin": "BER",
                "destination": "Copenhagen",
                "startDate": "2026-11-12",
                "endDate": "2026-11-14",
                "travelers": 1,
                "needsStay": True,
                "selectedFlight": "SK139",
                "flightPrice": 71,
                "airline": "SAS",
                "flightNumber": "SK139",
                "departTime": "12:19",
                "arriveTime": "13:36",
                "selectedHotel": "h_CPH_1",
                "hotelName": "Hotel Sanders",
                "nightlyPrice": 190,
            }
        ],
    }
    hop = data.panel_rows(settled)["hops"][1]
    fare, stay = hop["flights"][0], hop["stays"][0]
    assert (fare["airline"], fare["departTime"], fare["arriveTime"]) == ("SAS", "12:19", "13:36")
    assert stay["name"] == "Hotel Sanders"
    # Every leg field the panel reads is one a press may write.
    from travel_a2ui.brain.trip import LEG_OWNED

    for field in ("airline", "flightNumber", "departTime", "arriveTime", "hotelName"):
        assert field in LEG_OWNED, field


class TestASaveDoesNotEraseWhatIsOnALeg:
    """`legs` is merged hop by hop, not replaced whole.

    `legs` is the one value on a trip that is a list of objects, and
    `{**trip, **patch}` replaced it entire. `save_trip` takes the whole trip and
    the agent re-sends the route it knows — cities, dates, party — so every save
    quietly deleted whatever was on a leg and not in that call.

    What was on the leg and not in the call was the fare. The host records a
    press itself, so pressing the return put all five facts on `legs[0]`; the
    agent's own `save_trip` landed moments later with the route, and three of
    them were gone. The panel's return row drew blank where the outbound's drew
    the airline and both times — because the trip's flat fields are hop one's,
    and nothing was overwriting those.

    This is `sieve`'s argument one level down: a save is applied field by field
    and never refused whole, precisely so a model saving the route and a hotel
    in one call does not lose the hotel.
    """

    PRESSED = {
        "origin": "CPH",
        "destination": "BER",
        "startDate": "2026-11-09",
        "endDate": "2026-11-12",
        "travelers": 2,
        "legs": [
            {
                "origin": "BER",
                "destination": "CPH",
                "startDate": "2026-11-12",
                "travelers": 1,
                "selectedFlight": "SK6955",
                "flightPrice": 71,
                "airline": "SAS",
                "departTime": "12:19",
                "arriveTime": "13:36",
            }
        ],
    }

    def test_the_agent_resending_the_route_keeps_the_fare_on_it(self) -> None:
        from travel_a2ui.brain import trip as model

        # What `save_trip` sends: the route as the agent knows it, no fare.
        after = model.merge(
            self.PRESSED,
            {
                "legs": [
                    {
                        "origin": "BER",
                        "destination": "CPH",
                        "startDate": "2026-11-12",
                        "travelers": 1,
                    }
                ]
            },
        )
        leg = after["legs"][0]
        for field in ("selectedFlight", "flightPrice", "airline", "departTime", "arriveTime"):
            assert field in leg, f"the agent's save erased {field} from the hop"
        assert leg["airline"] == "SAS"
        assert leg["departTime"] == "12:19"

    def test_and_a_value_the_save_does_name_still_wins(self) -> None:
        """Merging must not make a leg unwritable."""
        from travel_a2ui.brain import trip as model

        # With the route, because a leg without a destination is not a leg:
        # `normalize` drops it, which is its own rule and not this one's.
        after = model.merge(
            self.PRESSED,
            {"legs": [{"origin": "BER", "destination": "CPH", "travelers": 3}]},
        )
        assert after["legs"][0]["travelers"] == 3
        assert after["legs"][0]["airline"] == "SAS", "the rest of the hop was lost"

    def test_and_a_route_that_loses_a_hop_loses_it(self) -> None:
        """The patch decides how many hops there are. Only a survivor's fields are kept."""
        from travel_a2ui.brain import trip as model

        three = {**self.PRESSED, "legs": [*self.PRESSED["legs"], {"origin": "CPH", "destination": "OSL"}]}
        after = model.merge(three, {"legs": [{"origin": "BER", "destination": "CPH"}]})
        assert len(after["legs"]) == 1, "a dropped hop came back"
        assert after["legs"][0]["airline"] == "SAS"

    def test_and_a_route_that_gains_one_gains_it_empty(self) -> None:
        from travel_a2ui.brain import trip as model

        after = model.merge(
            self.PRESSED,
            {"legs": [{"origin": "BER", "destination": "CPH"}, {"origin": "CPH", "destination": "OSL"}]},
        )
        assert len(after["legs"]) == 2
        assert after["legs"][0]["airline"] == "SAS"
        assert "airline" not in after["legs"][1], "a new hop inherited the old hop's fare"
