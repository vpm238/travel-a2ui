"""Fares for one hop, on data that reads like a schedule.

Two complaints, both about the fare card. "Remove the complex flight card
redraw... show outbound options; once the user has selected then the return
options" — a card offering both hops can only ever answer one of them, and the
other half goes grey unanswered. And "the flight options are unrealistic for
that prompt" — Copenhagen to Berlin came back on Delta and American, then on
Air France, KLM and TAP, none of which fly it.
"""

from __future__ import annotations

import asyncio
import pathlib

from travel_a2ui.brain.providers.fixture import (
    FixtureProvider,
    _carriers_for,
    _distance_km,
    _fold,
)


class TestOneHopPerCardIsTheBriefsJob:
    """Where the rule lives, now that the host does not enforce it.

    There was a `two_hops_at_once` check here that rejected a fare card
    offering more than one hop. It went the same way as `asks_nothing`: "one
    hop per card" is a flow rule, and in this app flow lives in the skill, not
    in a host veto over what the agent drew. The brief says it; this checks the
    brief says it, which is the only honest thing to assert.
    """

    def test_the_brief_says_one_hop_at_a_time(self):
        brief = (
            pathlib.Path(__file__).resolve().parents[3] / "prompts" / "journey.md"
        ).read_text("utf-8")
        assert "### One hop at a time" in brief
        assert "only that hop" in brief
        # And how to go back, because that is the half that makes it safe.
        assert "release_decision" in brief


class TestTheScheduleReadsLikeOne:
    """Carriers are offered on routes they actually fly."""

    def flights(self, **query) -> list[dict]:
        return asyncio.run(FixtureProvider().search_flights(query)).items

    def test_copenhagen_to_berlin_is_flown_by_the_three_who_fly_it(self):
        airlines = {flight["airline"] for flight in self.flights(
            origin="CPH", destination="Berlin", date="2026-10-12", travelers=2
        )}
        assert airlines <= {"SAS", "Norwegian", "Eurowings"}
        assert airlines

    def test_and_nobody_connects_on_a_350km_hop(self):
        for flight in self.flights(origin="CPH", destination="Berlin", date="2026-10-12"):
            assert flight["stops"] == "Nonstop"

    def test_a_short_hop_takes_about_an_hour_and_a_half(self):
        for flight in self.flights(origin="CPH", destination="Berlin", date="2026-10-12"):
            hours, minutes = flight["duration"].split("h ")
            assert int(hours) == 1, flight["duration"]
            assert 0 <= int(minutes.rstrip("m")) < 60

    def test_a_connection_goes_through_the_carriers_own_hub(self):
        # Iberia via Paris and Delta via Lisbon are what pairing the hub and the
        # airline independently produced, for a quarter of every list.
        hubs = {"TAP Air Portugal": "LIS", "Air France": "CDG", "Iberia": "MAD",
                "Lufthansa": "FRA", "KLM": "AMS"}
        for flight in self.flights(origin="JFK", destination="Madrid", date="2027-04-12"):
            if flight["stops"] == "Nonstop":
                continue
            hub = flight["stops"].split("· ")[1]
            expected = hubs.get(flight["airline"])
            if expected:
                assert hub == expected, f"{flight['airline']} via {hub}"

    def test_the_long_haul_route_keeps_its_long_haul_carriers(self):
        pool = {carrier["name"] for carrier in _carriers_for("JFK", "MAD", _distance_km("JFK", "MAD"))}
        assert "Eurowings" not in pool
        assert {"Iberia", "American", "Delta"} <= pool

    def test_a_domestic_hop_stays_domestic(self):
        pool = {carrier["name"] for carrier in _carriers_for("SFO", "JFK", _distance_km("SFO", "JFK"))}
        assert pool == {"Delta", "United", "American"}


class TestStaysWorthChoosingBetween:
    def stays(self, **query) -> list[dict]:
        return asyncio.run(FixtureProvider().search_hotels(query)).items

    def test_berlin_has_written_down_stays(self):
        names = {hotel["name"] for hotel in self.stays(destination="Berlin", nights=3)}
        assert "Pension Savignyplatz" in names

    def test_close_to_kurfurstendamm_filters_rather_than_relabels(self):
        found = self.stays(destination="Berlin", nights=3, neighborhood="Kurfürstendamm")
        assert found
        # Each one keeps the neighbourhood it is actually in...
        assert {hotel["neighborhood"] for hotel in found} == {"Charlottenburg"}
        # ...and the ones across the city are not offered.
        assert "Feldhaus Tempelhof" not in {hotel["name"] for hotel in found}

    def test_without_the_umlaut_too(self):
        assert _fold("Kurfürstendamm") == _fold("kurfurstendamm")
        plain = self.stays(destination="Berlin", nights=3, neighborhood="kurfurstendamm")
        assert {hotel["name"] for hotel in plain} == {
            hotel["name"]
            for hotel in self.stays(destination="Berlin", nights=3, neighborhood="Kurfürstendamm")
        }

    def test_a_city_nobody_wrote_down_keeps_the_generated_ones(self):
        found = self.stays(destination="Madrid", nights=5)
        assert found
        assert all(hotel["id"].startswith("h_MAD_") for hotel in found)

    def test_copenhagen_is_priced_in_kroner(self):
        for hotel in self.stays(destination="Copenhagen", nights=2):
            assert hotel["price"].startswith("DKK ")


class TestOneCurrencyPerTrip:
    """A card reading "€112 / night" became "$336" in the same summary.

    Fares were priced in dollars and stays in the destination's currency, and
    the total added them together as if they were the same money. One currency
    per trip, chosen by the destination — and the caller picks it, because the
    provider is handed one hop and cannot tell a Copenhagen–Berlin outbound
    from the Berlin–Copenhagen return.
    """

    BERLIN = {
        "destination": "BER",
        "origin": "CPH",
        "startDate": "2026-10-12",
        "endDate": "2026-10-15",
        "travelers": 2,
        "nightlyPrice": 112,
        "flightPrice": 75,
    }

    def run(self, tool: str, args: dict, trip: dict) -> dict:
        from travel_a2ui.brain import tools
        from travel_a2ui.brain.providers.fixture import FixtureProvider

        context = tools.ToolContext(
            trip=dict(trip), provider=FixtureProvider(), save=lambda patch: None, today="2026-10-06"
        )
        result, _ = asyncio.run(tools.run_tool(tool, args, context))
        return result

    def test_the_fares_are_in_the_trips_currency(self):
        flights = self.run("search_flights", {}, self.BERLIN)["flights"]
        assert all(fare["priceLabel"].startswith("€") for fare in flights)

    def test_and_so_are_the_stays(self):
        stays = self.run("search_hotels", {}, self.BERLIN)["hotels"]
        assert all((stay.get("priceLabel") or stay["price"]).startswith("€") for stay in stays)

    def test_and_so_is_the_total(self):
        total = self.run("estimate_cost", {}, self.BERLIN)
        assert total["currency"] == "EUR"
        assert total["total"].startswith("€")
        assert all(line["amount"].startswith("€") for line in total["lines"])

    def test_a_trip_with_no_destination_yet_is_still_in_dollars(self):
        # Which is what every caller got before this existed.
        from travel_a2ui.brain.providers.fixture import FixtureProvider

        outcome = asyncio.run(
            FixtureProvider().search_flights({"origin": "CPH", "destination": "Berlin"})
        )
        assert outcome.currency == "USD"

    def test_copenhagen_prices_in_kroner(self):
        trip = {**self.BERLIN, "destination": "CPH", "origin": "BER"}
        assert self.run("estimate_cost", {}, trip)["currency"] == "DKK"

    def test_the_way_home_is_priced_in_the_trips_currency_not_the_hops(self):
        # Pricing the return means `search_flights(destination="CPH")`, and a
        # currency read off the merged arguments came back in kroner for the
        # return of a Berlin trip whose outbound and hotel were both in euros.
        trip = {
            **self.BERLIN,
            "legs": [
                {"destination": "CPH", "origin": "BER", "startDate": "2026-10-15", "travelers": 1}
            ],
        }
        home = self.run(
            "search_flights",
            {"destination": "CPH", "origin": "BER", "date": "2026-10-15", "travelers": 1},
            trip,
        )["flights"]
        assert all(
            (fare.get("priceLabel") or fare["price"]).startswith("€") for fare in home
        ), [fare.get("priceLabel") for fare in home]


class TestAHopHasToGoSomewhere:
    """A hop whose origin is its destination, which nothing caught.

    What an ambiguous route turns into. "JFK to Chicago then New York then back
    home" — where home *is* New York — came back recorded as three hops ending
    JFK → JFK, and `problems` returned nothing at all. That is not a hop: it
    cannot be priced, `search_flights` has nothing to look for, and the panel
    draws a row for it that can never be filled, so the agent goes on trying to
    ticket it every turn.

    Refused rather than reported, because `legs` is already REFUSABLE: the agent
    is told and asks which city they meant, instead of committing to a reading
    of a sentence that had two.
    """

    @staticmethod
    def _problems(trip: dict) -> list[str]:
        from travel_a2ui.brain import trip as model

        return [found["message"] for found in model.problems(trip, "2026-11-02")]

    NOWHERE = {
        "origin": "JFK",
        "destination": "ORD",
        "travelers": 2,
        "startDate": "2027-04-10",
        "endDate": "2027-04-20",
        "legs": [
            {"origin": "ORD", "destination": "JFK", "travelers": 3},
            {"origin": "JFK", "destination": "JFK", "travelers": 2},
        ],
    }

    def test_it_is_a_problem(self) -> None:
        found = self._problems(self.NOWHERE)
        assert any("has to go somewhere" in message for message in found), (
            f"a JFK → JFK hop saved cleanly: {found}"
        )

    def test_and_the_save_is_turned_away_so_the_agent_asks(self) -> None:
        from travel_a2ui.brain import trip as model

        saved = {k: v for k, v in self.NOWHERE.items() if k != "legs"}
        _, refused = model.sieve(saved, self.NOWHERE, "2026-11-02")
        assert refused, "the nowhere hop was recorded without a word to the agent"
        assert any("has to go somewhere" in message for message in refused)

    def test_but_a_there_and_back_is_fine(self) -> None:
        """The commonest route there is. Coming home is not a hop to nowhere."""
        there_and_back = {
            "origin": "JFK",
            "destination": "MAD",
            "travelers": 2,
            "startDate": "2027-04-10",
            "endDate": "2027-04-20",
            "legs": [{"origin": "MAD", "destination": "JFK", "travelers": 2}],
        }
        assert self._problems(there_and_back) == []

    def test_and_a_city_visited_twice_is_fine(self) -> None:
        """Only *consecutive* stops in the same place are nowhere to go."""
        returning = {
            "origin": "JFK",
            "destination": "MAD",
            "travelers": 1,
            "startDate": "2027-04-10",
            "endDate": "2027-04-24",
            "legs": [
                {"origin": "MAD", "destination": "LIS", "travelers": 1},
                {"origin": "LIS", "destination": "MAD", "travelers": 1},
                {"origin": "MAD", "destination": "JFK", "travelers": 1},
            ],
        }
        assert self._problems(returning) == []
