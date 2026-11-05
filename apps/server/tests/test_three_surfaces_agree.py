"""The two ways in have to behave like one agent.

There are two front doors — the Interactions API for typed turns and the Live
API for calls — and one agent behind them. (There were three: an MCP door for
Claude, removed along with the plugin.) Keeping that true has been done by
remembering, and remembering does not work. In a single afternoon the same class
of bug was fixed three separate times:

  * Inline surfaces collided, so a new card overwrote the last. Fixed for typed
    turns; found again weeks later in live, where surfaces were keyed by *what*
    they showed rather than *when*, so a second flight search replaced the first
    mid-call.
  * The departure-airport hint was computed for typed turns and simply never
    passed to a call, so voice asked people to say an airport code out loud —
    the exact question the hint exists to avoid.
  * Invented component names were caught by the streaming compiler and not by
    the tool, and the tool is what a voice call goes through, so a typo became a
    grey box and a success reported to the model.

None of those looked like a bug from inside the path that had it. Each was a
thing one door did and another did not, and the only way to see it was to put
them side by side — which is what this file does.

It asserts *agreement*, not implementation. Where the two genuinely differ —
Live takes a different tool shape, because its replies are audio and a function
call is the only way it can reach a screen — the difference is named here as a
fact, so that changing it has to be deliberate rather than accidental.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "parity"))


class TestOneVocabulary:
    """All three compose from the same catalog and the same skills."""

    def test_the_same_catalog_id_everywhere(self) -> None:
        from travel_a2ui.doors.interactions import CATALOG_ID, CATALOG_JSON

        assert CATALOG_ID == CATALOG_JSON["$id"]

    def test_a_call_is_offered_every_declared_surface(self) -> None:
        """A layout that is declared and unreachable is a layout that does not exist."""
        from travel_a2ui.doors.live import SURFACE_TOOLS, voice_tools

        declared = {tool["name"] for tool in SURFACE_TOOLS}
        spoken = {tool["name"] for tool in voice_tools() if tool["name"].startswith("show_")}
        assert declared == spoken, f"only one side has {declared ^ spoken}"

    def test_the_typed_path_and_a_call_share_the_data_tools(self) -> None:
        from travel_a2ui.brain.tools import gemini_tools
        from travel_a2ui.doors.live import voice_tools

        typed = {tool["name"] for tool in gemini_tools()}
        spoken = {tool["name"] for tool in voice_tools()}
        assert typed <= spoken, f"a call cannot {sorted(typed - spoken)}"


class TestOneSetOfRules:
    """The prompt is assembled once; every door gets the same rules."""

    def test_a_call_is_given_the_same_inventory(self) -> None:
        """Voice used to be handed a prompt with no idea what data existed."""
        from travel_a2ui.brain.providers.fixture import _DESTINATIONS
        from travel_a2ui.brain.skills import build_system_prompt

        said = build_system_prompt(
            variant="express-modular",
            surface="inline",
            surface_id="voice-1",
            catalog_id="travel",
            trip={},
            today="2027-03-01",
        )
        for entry in _DESTINATIONS:
            assert entry["city"] in said

    def test_a_call_asks_where_they_are_flying_from_too(self) -> None:
        """Voice used to ask for an airport code out loud, and nothing else did.

        The fix was not a better guess for the call — it was removing the guess
        everywhere. All three doors read the same rule out of `role.md`, so the
        thing to hold is that the rule is in the shared half rather than in one
        surface's brief.
        """
        from travel_a2ui.brain.skills import build_system_prompt

        for surface in ("inline", "sidebar", "home"):
            said = build_system_prompt(
                variant="express-modular",
                surface=surface,
                surface_id="voice-1",
                catalog_id="travel",
                trip={},
                today="2027-03-01",
            )
            assert "always asked, never inferred" in said


class TestOneSurfacePerDrawing:
    """A card is a thing that was asked, on every door that has a feed."""

    def test_a_call_gives_each_drawing_its_own_id(self) -> None:
        from travel_a2ui.brain.builders import _surface_id_for

        first = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-1"})
        second = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-2"})
        assert first != second

    def test_a_panel_is_still_singular(self) -> None:
        """The opposite case, and the reason this is not a blanket rule."""
        from travel_a2ui.brain.builders import _surface_id_for

        assert _surface_id_for("sidebar", "mcp-flights", {"surfaceId": "voice-9"}) == "mcp-sidebar"


class TestOneIdeaOfBroken:
    """An invented component is an error on every door, not just the streamed one."""

    def test_the_tool_rejects_what_the_stream_rejects(self) -> None:
        import asyncio

        from travel_a2ui.doors.interactions import COMPONENT_NAMES
        from travel_a2ui.brain.express import unknown_components
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.builders import build_surface

        source = 'root = Colunm([Txt("hi")])'
        assert unknown_components(source, COMPONENT_NAMES), "the stream would reject this"

        async def render() -> None:
            await build_surface(
                "render_a2ui_express", {"source": source}, FixtureProvider(), "2027-03-01"
            )

        try:
            asyncio.run(render())
        except ValueError as error:
            assert "Colunm" in str(error), "the error has to name what is wrong"
        else:  # pragma: no cover - the assertion is the point
            raise AssertionError("the tool accepted a component the catalog does not have")


class TestBehaviourLivesInMarkdown:
    """How the agent behaves is edited in `prompts/`, not in Python.

    Five briefs and the generated skills are the whole of what the agent is
    told, and they are markdown on purpose: changing how it behaves should be
    changing a file someone can read, review and diff — not a triple-quoted
    string three imports deep in a relay.

    The voice brief was the one exception, a `VOICE_BRIEF = \"\"\"...\"\"\"` in
    `live.py`, and the exception is exactly where behaviour drifted: it is the
    door that was missing the inventory, missing the origin hint, and keyed its
    surfaces differently. Prose living somewhere nobody edits is prose nobody
    keeps in step.
    """

    def test_every_brief_is_a_file(self) -> None:
        briefs = sorted(path.name for path in (ROOT / "prompts").glob("*.md"))
        assert briefs == [
            "flow.md",
            "journey.md",
            "live.md",
            "role.md",
            "surface-home.md",
            "surface-inline.md",
            "surface-sidebar.md",
        ]

    def test_no_module_still_holds_a_brief_of_its_own(self) -> None:
        """A long triple-quoted string in the server is prose that escaped."""
        import re

        offenders: list[str] = []
        for path in (ROOT / "apps" / "server" / "src" / "travel_a2ui").glob("*.py"):
            for match in re.finditer(r'^[A-Z][A-Z_]* = """(.*?)"""', path.read_text("utf-8"), re.S | re.M):
                # Short constants are formats and templates, not instructions.
                if len(match.group(1)) > 400:
                    offenders.append(f"{path.name}: {match.group(0)[:40]}…")
        assert not offenders, f"move these into prompts/: {offenders}"

    def test_the_call_brief_is_read_from_that_file(self) -> None:
        from travel_a2ui.doors.live import VOICE_BRIEF

        assert VOICE_BRIEF == (ROOT / "prompts" / "live.md").read_text("utf-8").strip()



def door_source(module) -> str:
    """Everything a door is made of, whether it is a file or a package.

    `interactions` is a package — the press, the turn, the panels, the warm-up
    — and `inspect.getsource` on a package reads its `__init__.py`, which is an
    address book. The checks below are about what the door *does*, so they have
    to read what the door is made of.
    """
    import inspect
    import pathlib

    file = pathlib.Path(inspect.getfile(module))
    if file.name != "__init__.py":
        return file.read_text("utf-8")
    return "\n".join(
        part.read_text("utf-8") for part in sorted(file.parent.glob("*.py"))
    )


class TestOneImplementationNotThree:
    """The steps every door performs are performed by the same code.

    Agreement tested by assertion is agreement maintained by luck: the suite
    above catches drift *after* someone writes it. These are the places where
    drift is no longer possible because there is only one implementation left.

    Not a rewrite. `interactions.py`, `live.py` and `plugin.py` are still three loops —
    an SSE generator, a websocket pump and a JSON-RPC handler, which is what
    their transports actually are. What they no longer each own is the work
    that has nothing to do with transport.
    """

    def test_the_panels_are_refreshed_by_one_function(self) -> None:
        import inspect

        from travel_a2ui.doors import interactions, live

        for module in (interactions, live):
            source = door_source(module)
            assert "panel_events(" in source, f"{module.__name__} does not use it"
            # The loop it replaced. Two copies is how the typed path grew a
            # per-turn surface id and a departure hint that voice did not.
            assert "for surface_id in STANDING_SURFACES:\n            updates" not in source

    def test_no_door_compiles_a_surface_itself(self) -> None:
        """`compile_surface` validates as well as compiles, and that is the point.

        A door that reaches past it to the parser gets Express turned into
        messages without the catalog's validator ever seeing them — and the
        validator is what catches a `Column([header, footer])` whose `footer`
        was never defined. That compiles cleanly and renders as a box with a
        hole in it.

        Two doors, two ways of getting there: `live` builds a whole surface and
        hands it to `compile_surface`; `interactions` streams, so it compiles
        block by block through `ExpressStream` and runs the same validator on
        each finished one. Neither may open-code the third way.
        """
        import inspect

        from travel_a2ui.doors import interactions, live

        assert "compile_surface(" in door_source(live)
        for module in (interactions, live):
            assert ".compile(surface.express" not in door_source(module), (
                f"{module.__name__} compiles a built surface without validating it"
            )

    def test_the_two_halves_of_drawing_stay_together(self) -> None:
        """`build_surface` validates; `compile_surface` emits. Both or neither.

        The validation that rejects an invented component went into
        `build_surface` and reached MCP and voice both — but only because they
        happened to share that call. Had either compiled from its own source,
        it would have kept the bug.
        """
        import inspect

        from travel_a2ui.brain import builders

        source = inspect.getsource(builders)
        assert "def compile_surface(" in source
        assert "def build_surface(" in source


class TestNothingIsPromisedThatCannotBeDrawn:
    """The model may only be told about components every renderer has.

    Pruning cuts the catalog from 30 to 24 before the model sees it, which is a
    large, cheap saving — and it is a *list*, maintained by hand, with no
    relationship to what the clients can actually draw. Those two drifted apart
    in both directions at once: pruning removed `Divider`, which Flutter draws
    perfectly well, and kept `Icon`, which Flutter did not implement at all.

    So the agent was being told to use `Icon`, did, and the Flutter client drew
    a placeholder box — a component that exists in the catalog, is recommended
    in a brief, compiles without complaint, and silently is not there. Nothing
    in the pipeline objected, because nothing in the pipeline knew.

    One named difference, in the spirit of this file's opening note. `GoogleMap`
    draws a real map in React, over the Maps JavaScript API's own `gmp-map-3d`,
    and in Flutter it draws the places and legs as a list. Both are registered
    and both render something a person can read, which is what these tests
    check; what Flutter cannot do is show geography. A real map there means a
    web view factory over the same element, and writing that without a Flutter
    SDK to compile it against would risk the image build for a client that is
    not where the map work is aimed.
    """

    @staticmethod
    def _told() -> set[str]:
        import json

        catalog = json.loads(
            (ROOT / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        skill = (ROOT / "skills" / "express-modular" / "a2ui-travel" / "SKILL.md").read_text("utf-8")
        return {name for name in catalog["components"] if name in skill}

    def test_the_flutter_client_draws_everything_it_is_told_about(self) -> None:
        """`a2ui_flutter` draws the basic components; `travelViews` the rest."""
        import re
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from a2ui.core.basic_catalog import BasicCatalog

        source = (ROOT / "renderers" / "flutter" / "lib" / "components.dart").read_text("utf-8")
        views = source[source.index("const Map<String, TravelView> travelViews"):]
        travel = set(re.findall(r"^\s*'([A-Za-z]+)':\s*_", views, re.M))
        drawn = set(BasicCatalog("1.0").to_json()["components"]) | travel
        missing = sorted(self._told() - drawn)
        assert not missing, f"the agent is told to use {missing}, which Flutter draws as a box"

    @staticmethod
    def _react_draws() -> set[str]:
        """The A2UI SDK's basic components, plus the travel views this app adds.

        The React client renders with `@a2ui/react`: the basic components are the
        SDK's own (the same v1.0 basic catalog the Python SDK bundles), and the
        travel ones are the `TRAVEL_VIEWS` map in `renderers/react`.
        """
        import re
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from a2ui.core.basic_catalog import BasicCatalog

        basic = set(BasicCatalog("1.0").to_json()["components"])
        source = (ROOT / "renderers" / "react" / "src" / "components" / "travel.tsx").read_text("utf-8")
        views = source[source.index("export const TRAVEL_VIEWS"):]
        travel = set(re.findall(r"^\s*([A-Z][A-Za-z]+),$", views, re.M))
        return basic | travel

    def test_the_react_client_draws_everything_it_is_told_about(self) -> None:
        drawn = self._react_draws()
        missing = sorted(self._told() - drawn)
        assert not missing, f"the agent is told to use {missing}, which React does not draw"

    def test_a_host_composing_for_itself_is_told_the_same_thing(self) -> None:
        """Claude reads the catalog through `get_a2ui_component_reference`.

        It is given all 30 rather than the pruned 24, and that is deliberate
        rather than an oversight: the MCP app renders in React, which draws all
        of them, and Claude's context is its own to spend. What would be a bug
        is a component *no* renderer has, so that is what this asserts.
        """
        import json

        catalog = json.loads(
            (ROOT / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        react = self._react_draws()
        undrawable = sorted(set(catalog["components"]) - react)
        assert not undrawable, f"the catalog offers {undrawable} and nothing renders them"




class TestARefusalCanBeActedOn:
    """A refusal that names a tool nobody has is a dead end with extra steps.

    `NeedsInput` is the message a door hands back when the model asked for a
    price without saying when — the whole point of it is to tell the model how
    to recover. It said "draw the controls … with render_a2ui_express", and that
    tool exists on no door: the typed path writes Express inline in an `<a2ui>`
    block and never had it, the spoken path calls `show_*` and lost it with MCP,
    and MCP is gone.

    Nothing caught it because nothing reads these strings. This does.
    """

    def tools_any_door_offers(self) -> set[str]:
        from travel_a2ui.brain.tools import gemini_tools
        from travel_a2ui.doors.live import voice_tools

        return {tool["name"] for tool in gemini_tools()} | {
            tool["name"] for tool in voice_tools()
        }

    def refusals(self) -> list[str]:
        """Every message the brain hands back instead of a surface.

        Both kinds, because the first version of this test only drove
        `NeedsInput` — and `build_surface`'s invented-component message was
        still telling the model to call `get_a2ui_component_reference`, which
        had gone with MCP. Same bug, same week, missed because the guard only
        looked where the last one had been.
        """
        import asyncio

        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.builders import build_surface

        provider = FixtureProvider()
        said: list[str] = []
        cases: list[tuple[str, dict]] = [
            ("show_flight_options", {"destination": "Madrid", "origin": "JFK"}),
            ("show_flight_options", {"destination": "Madrid", "date": "2027-04-12"}),
            ("show_flight_options", {"destination": "Madrid"}),
            # An invented component, which is the other way a turn is refused.
            (
                "render_a2ui_express",
                {"source": 'd = DateInput("When")\nroot = Column([d])'},
            ),
        ]
        for tool, args in cases:
            try:
                asyncio.run(build_surface(tool, args, provider, "2026-09-14"))
            except Exception as error:  # noqa: BLE001 - the message is the subject
                said.append(str(error))
        assert len(said) == len(cases), "every one of these is supposed to be refused"
        return said

    def test_no_refusal_names_a_tool_that_does_not_exist(self) -> None:
        import re

        offered = self.tools_any_door_offers()
        for message in self.refusals():
            # Anything shaped like one of our tool names: lower_snake_case with
            # a verb in front. Narrow enough not to catch ordinary prose.
            for word in re.findall(r"\b(?:show|render|search|get|save|release|share)_\w+", message):
                assert word in offered, f"refusal names {word!r}, which no door offers"

    def test_a_refusal_still_says_what_to_do(self) -> None:
        """Dropping the tool name must not drop the instruction with it."""
        for message in self.refusals():
            assert any(
                hint in message
                for hint in ("draw the", "use one of them", "write the block again")
            ), f"no recovery in: {message[:140]}"


class TestAFormComesUpFilledIn:
    """A path the surface merely mentions is not a value the model meant.

    `seed_surface_trip` fills in what a surface left unset, on the principle
    that a value the model deliberately wrote is a *proposal* and should beat
    the older fact. The test for "left unset" was `key in seeded` — and a bound
    control mentions every path it writes to, so a date picker bound to
    `$/trip/startDate` arrives carrying `startDate: null`.

    So the seed was skipped and the control rendered blank over a trip that knew
    the answer. Say "two weeks from next Friday" or "three of us", and the agent
    records it, draws the form to confirm it, and the form comes up empty — then
    asks you to type what you just said.

    The panel had it worse, because nobody fills a panel in by hand: its
    `createSurface` carried `legs: null` and landed on top of the `/trip/legs`
    sent moments before, wiping a hop's airline and times from the client's data
    model after the server had got them right.
    """

    TRIP = {
        "destination": "Madrid",
        "origin": "JFK",
        "startDate": "2027-04-12",
        "endDate": "2027-04-26",
        "travelers": 3,
        "legs": [
            {
                "origin": "MAD",
                "destination": "JFK",
                "travelers": 2,
                "selectedFlight": "IB6250",
                "airline": "Iberia",
                "departTime": "10:59",
            }
        ],
    }

    @staticmethod
    def _seeded(declared: dict) -> dict:
        from travel_a2ui.brain.finishing import seed_surface_trip

        messages = [
            {
                "version": "1.0",
                "createSurface": {
                    "surfaceId": "inline-1",
                    "components": [],
                    "dataModel": {"trip": declared},
                },
            }
        ]
        out = seed_surface_trip(messages, TestAFormComesUpFilledIn.TRIP)
        return out[0]["createSurface"]["dataModel"]["trip"]

    def test_a_control_that_names_a_path_still_gets_the_value(self) -> None:
        """What a bound DateRangePicker and a TravelerCounter look like on arrival."""
        seeded = self._seeded({"startDate": None, "endDate": None, "travelers": None})
        assert seeded["startDate"] == "2027-04-12", "the date picker came up empty"
        assert seeded["endDate"] == "2027-04-26"
        assert seeded["travelers"] == 3, "the party counter came up empty"

    def test_an_empty_string_is_also_unset(self) -> None:
        seeded = self._seeded({"destination": "", "origin": ""})
        assert seeded["destination"] == "Madrid"
        assert seeded["origin"] == "JFK"

    def test_but_a_value_the_model_wrote_still_wins(self) -> None:
        """A suggested date is a proposal, and beats the fact it proposes to replace."""
        seeded = self._seeded({"startDate": "2027-05-01", "travelers": 4})
        assert seeded["startDate"] == "2027-05-01", "the agent's proposal was overwritten"
        assert seeded["travelers"] == 4

    def test_and_a_panel_keeps_the_legs_the_server_just_sent(self) -> None:
        """The last layer of the return row drawing blank."""
        seeded = self._seeded({"legs": None})
        assert isinstance(seeded["legs"], list) and seeded["legs"], (
            "the panel wiped the route out of its own data model"
        )
        leg = seeded["legs"][0]
        assert leg["airline"] == "Iberia", "a hop's airline was wiped after the server had it"
        assert leg["departTime"] == "10:59"


class TestThePanelSaysWhenAHopGoesAndWhoIsOnIt:
    """Dates and party per hop, which the panel drew for nobody.

    It showed the route, the fare and the stay. A hop whose dates and party were
    settled several turns earlier showed neither, so "the right side does not
    show dates and travellers for each leg when confirmed" was exactly right.

    Bound, so the line follows the record — change the party on hop two and the
    panel moves with no model in the path — and only the parts this hop has, the
    same rule the fare and stay rows follow.
    """

    @staticmethod
    def _lines(trip: dict) -> list[str]:
        import json

        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        src = 'surface("sidebar")\npanel = Trip("Trip")\nroot = Column([panel])'
        drawn = finish(
            as_wire(expand(parser_for("sidebar").compile(src, is_final=True), trip)), trip
        )
        return [
            json.dumps(c.get("text"), ensure_ascii=False)
            for c in drawn[0]["createSurface"]["components"]
            if c.get("component") == "Text"
        ]

    FULL = {
        "origin": "CPH",
        "destination": "BER",
        "startDate": "2026-11-09",
        "endDate": "2026-11-12",
        "travelers": 2,
        "legs": [{"origin": "BER", "destination": "CPH", "startDate": "2026-11-12", "travelers": 1}],
    }

    def test_each_hop_says_when_it_goes_and_who_is_on_it(self) -> None:
        lines = " ".join(self._lines(self.FULL))
        assert "/trip/startDate" in lines and "/trip/endDate" in lines
        assert "/trip/travelers" in lines, "hop one does not say who is on it"
        assert "/trip/legs/0/startDate" in lines, "hop two does not say when it goes"
        assert "/trip/legs/0/travelers" in lines, "hop two does not say who is on it"

    def test_and_it_is_bound_rather_than_written_out(self) -> None:
        """A written date goes stale the moment somebody moves it."""
        lines = " ".join(self._lines(self.FULL))
        assert "@call" in lines and "formatString" in lines, (
            "the hop's facts were written as literal text"
        )
        assert "2026-11-09" not in lines, "a date was baked into the panel"

    def test_but_says_nothing_about_a_hop_that_has_not_settled_either(self) -> None:
        bare = {"origin": "CPH", "destination": "BER"}
        lines = " ".join(self._lines(bare))
        assert "travelling" not in lines, "the panel claimed a party nobody has given"
        assert "startDate" not in lines, "the panel claimed dates nobody has given"

    def test_and_says_only_the_half_it_has(self) -> None:
        """Dates settled, party not. One of the two, not a blank for the other."""
        half = {"origin": "CPH", "destination": "BER", "startDate": "2026-11-09", "endDate": "2026-11-12"}
        lines = " ".join(self._lines(half))
        assert "/trip/startDate" in lines
        assert "travelling" not in lines


class TestThePanelTotalsWhatHasBeenChosen:
    """A running total, and the budget beside it.

    Not `estimate_cost`, which projects a whole trip and fills in a plausible
    fare for a hop nobody has priced — a projection with a hole in it is no use.
    This counts only what has been chosen, so it starts at nothing and rises as
    each decision lands, and never claims a number nobody agreed to.
    """

    TRIP = {
        "origin": "CPH",
        "destination": "BER",
        "startDate": "2026-11-09",
        "endDate": "2026-11-12",
        "travelers": 2,
        "flightPrice": 74,
        "nightlyPrice": 112,
        "needsStay": True,
        "budget": 1500,
        "legs": [
            {
                "origin": "BER",
                "destination": "CPH",
                "startDate": "2026-11-12",
                "travelers": 1,
                "flightPrice": 71,
            }
        ],
    }

    def test_it_counts_each_hop_s_own_party_and_nights(self) -> None:
        """74 x 2 outbound, 112 x 3 nights, 71 x 1 home. One fare times one party
        size is how a trip where somebody joins halfway came out wrong."""
        from travel_a2ui.brain.finishing import money_rows

        assert money_rows(self.TRIP)["total"] == 74 * 2 + 112 * 3 + 71 * 1

    def test_and_says_what_is_left_of_the_budget(self) -> None:
        from travel_a2ui.brain.finishing import money_rows

        money = money_rows(self.TRIP)
        assert money["budget"] == 1500
        assert money["remaining"] == 1500 - money["total"]
        assert money["over"] is False

    def test_and_says_so_when_it_is_over(self) -> None:
        from travel_a2ui.brain.finishing import money_rows

        money = money_rows({**self.TRIP, "budget": 300})
        assert money["remaining"] < 0
        assert money["over"] is True, "the panel has to label it, not infer a minus sign"

    def test_it_claims_nothing_before_anything_is_priced(self) -> None:
        from travel_a2ui.brain.finishing import money_rows

        assert money_rows({"destination": "BER"}) == {}, (
            "a panel saying 'Total 0' is a claim about a trip nobody has priced"
        )

    def test_a_budget_with_nothing_spent_is_still_worth_saying(self) -> None:
        from travel_a2ui.brain.finishing import money_rows

        money = money_rows({"destination": "BER", "budget": 900})
        # The currency rides along with any figure, because the panel binds
        # `formatCurrency($/money/total, $/money/currency)` and the agent
        # drawing it has no way to know which currency a city prices in.
        assert money == {"budget": 900, "currency": "USD"}, f"got {money}"

    def test_the_panel_shows_the_money_when_it_is_asked_for(self) -> None:
        """`Trip("…", true)`, and the figures bound rather than written.

        The tiles were built unconditionally once — the host deciding a budget
        line belongs on the panel. Taking them out went too far: the panel is
        usually drawn as `draw: {macro: "Trip"}`, where the macro call is the
        whole block, so an agent that wanted a total had nowhere to put one.
        The flag is the opinion handed back: the host totals and knows the
        currency, the agent says whether to show it.
        """
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        src = 'surface("sidebar")\npanel = Trip("Trip", true)\nroot = Column([panel])'
        drawn = finish(
            as_wire(
                expand(
                    parser_for("sidebar").compile(src, is_final=True),
                    self.TRIP,
                    None,
                    "EUR",
                )
            ),
            self.TRIP,
        )
        tiles = [
            c
            for c in drawn[0]["createSurface"]["components"]
            if c.get("component") == "StatTile"
        ]
        assert [t["label"] for t in tiles] == [
            "Committed so far",
            "Budget",
            "Left to spend",
        ], tiles
        # Through `formatCurrency`, because the record keeps a number: bound
        # straight, a total draws as `584` beside a fare list saying `€292`.
        assert tiles[0]["value"]["@call"] == "formatCurrency"
        assert tiles[0]["value"]["args"]["value"] == {"@path": "/money/total"}

    def test_and_says_over_budget_rather_than_leaving_a_minus_sign(self) -> None:
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        broke = {**self.TRIP, "budget": 100}
        src = 'surface("sidebar")\npanel = Trip("Trip", true)\nroot = Column([panel])'
        drawn = finish(
            as_wire(
                expand(parser_for("sidebar").compile(src, is_final=True), broke, None, "EUR")
            ),
            broke,
        )
        labels = [
            c["label"]
            for c in drawn[0]["createSurface"]["components"]
            if c.get("component") == "StatTile"
        ]
        assert "Over budget by" in labels, labels
        assert "Left to spend" not in labels

    def test_the_draw_argument_carries_the_flag_as_a_flag(self) -> None:
        """`quoted(False)` is `""`, which the trailing trim then drops."""
        from travel_a2ui.brain.macros import closing_express

        asked = closing_express("save_trip", {"macro": "Trip", "heading": "T", "money": True}, "i")
        assert 'rows = Trip("T", true)' in asked, asked

        # And left off entirely when it was not asked for, rather than passed
        # as `false`: a trailing default only repeats what the macro already
        # does, and `Trip("T")` is what the brief's examples show.
        plain = closing_express("save_trip", {"macro": "Trip", "heading": "T"}, "i")
        assert 'rows = Trip("T")' in plain, plain

    def test_the_host_files_the_figures_and_draws_none_of_them(self) -> None:
        """The arithmetic is the host's. What to show of it is not.

        Three `StatTile`s used to be built inside the `Trip()` macro — a
        total, a budget, and what was left — and this test asserted all three.
        That was the host deciding that a budget line belongs on the panel,
        what it is called and in what order, off a request that was only "show
        a running total".

        So the figures are still filed at `/money`, bound and current every
        turn, and the macro draws nothing from them. An agent that wants a
        total writes one in its own `surface("sidebar")` block, against the
        same paths, and one that is drawing a trip nobody has priced leaves it
        off.
        """
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        src = 'surface("sidebar")\npanel = Trip("Trip")\nroot = Column([panel])'
        drawn = finish(
            as_wire(expand(parser_for("sidebar").compile(src, is_final=True), self.TRIP)),
            self.TRIP,
        )
        surface = drawn[0]["createSurface"]

        assert not [c for c in surface["components"] if c.get("component") == "StatTile"], (
            "the host composes no money tiles"
        )

        # But the numbers are there to bind to, which is the half that stays.
        money = surface.get("dataModel", {}).get("money", {})
        assert money.get("total") == 74 * 2 + 112 * 3 + 71 * 1
        assert money.get("budget") == 1500
        assert money.get("remaining") == 1500 - money["total"]
    def test_and_draws_no_tiles_before_there_is_anything_to_total(self) -> None:
        from travel_a2ui.brain.catalog import parser_for
        from travel_a2ui.brain.express import as_wire
        from travel_a2ui.brain.finishing import finish
        from travel_a2ui.brain.macros import expand

        bare = {"origin": "CPH", "destination": "BER"}
        src = 'surface("sidebar")\npanel = Trip("Trip")\nroot = Column([panel])'
        drawn = finish(
            as_wire(expand(parser_for("sidebar").compile(src, is_final=True), bare)), bare
        )
        tiles = [
            c for c in drawn[0]["createSurface"]["components"] if c.get("component") == "StatTile"
        ]
        assert tiles == []
