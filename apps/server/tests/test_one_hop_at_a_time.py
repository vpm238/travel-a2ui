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

from travel_a2ui.brain.controls import two_hops_at_once
from travel_a2ui.brain.providers.fixture import (
    FixtureProvider,
    _carriers_for,
    _distance_km,
    _fold,
)


def fare(component_id: str, hop: int | None) -> dict:
    event: dict = {"name": "select_flight", "context": {"id": component_id}}
    if hop is not None:
        event["context"]["hop"] = hop
    return {
        "id": component_id,
        "component": "FlightOption",
        "airline": "SAS",
        "action": {"event": event},
    }


def surface(*nodes: dict) -> list[dict]:
    return [{"updateComponents": {"surfaceId": "inline-1", "components": list(nodes)}}]


class TestOneHopPerCard:
    def test_two_hops_on_one_card_is_sent_back(self):
        said = two_hops_at_once(surface(fare("f1", 0), fare("f2", 0), fare("r1", 1)))
        assert said is not None
        assert "more than one hop" in said
        assert "hop=0" in said and "hop=1" in said

    def test_one_hop_is_fine(self):
        assert two_hops_at_once(surface(fare("f1", 1), fare("f2", 1))) is None

    def test_fares_that_name_no_hop_are_fine(self):
        # A trip with one hop has nothing to disambiguate.
        assert two_hops_at_once(surface(fare("f1", None), fare("f2", None))) is None

    def test_a_surface_with_no_fares_is_fine(self):
        hotels = surface({"id": "h1", "component": "HotelCard", "name": "Hotel Fasanenhof"})
        assert two_hops_at_once(hotels) is None


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
