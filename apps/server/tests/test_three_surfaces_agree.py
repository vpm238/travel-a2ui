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
        from travel_a2ui.brain.surfaces import _surface_id_for

        first = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-1"})
        second = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-2"})
        assert first != second

    def test_a_panel_is_still_singular(self) -> None:
        """The opposite case, and the reason this is not a blanket rule."""
        from travel_a2ui.brain.surfaces import _surface_id_for

        assert _surface_id_for("sidebar", "mcp-flights", {"surfaceId": "voice-9"}) == "mcp-sidebar"


class TestOneIdeaOfBroken:
    """An invented component is an error on every door, not just the streamed one."""

    def test_the_tool_rejects_what_the_stream_rejects(self) -> None:
        import asyncio

        from travel_a2ui.doors.interactions import COMPONENT_NAMES
        from travel_a2ui.brain.express import unknown_components
        from travel_a2ui.brain.providers.fixture import FixtureProvider
        from travel_a2ui.brain.surfaces import build_surface

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
            source = inspect.getsource(module)
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

        assert "compile_surface(" in inspect.getsource(live)
        for module in (interactions, live):
            assert ".compile(surface.express" not in inspect.getsource(module), (
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

        from travel_a2ui.brain import surfaces

        source = inspect.getsource(surfaces)
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
        import re

        source = (ROOT / "renderers" / "flutter" / "lib" / "components.dart").read_text("utf-8")
        drawn = set(re.findall(r"^\s*'([A-Za-z]+)':\s*_", source, re.M))
        missing = sorted(self._told() - drawn)
        assert not missing, f"the agent is told to use {missing}, which Flutter draws as a box"

    def test_the_react_client_draws_everything_it_is_told_about(self) -> None:
        import re

        source = (ROOT / "renderers" / "react" / "src" / "Surface.tsx").read_text("utf-8")
        drawn = set(re.findall(r"^\s*([A-Z][A-Za-z]+):\s*(?:basic|travel)\.", source, re.M))
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
        import re

        catalog = json.loads(
            (ROOT / "catalogs" / "a2ui-travel" / "catalog.json").read_text("utf-8")
        )
        react = set(
            re.findall(
                r"^\s*([A-Z][A-Za-z]+):\s*(?:basic|travel)\.",
                (ROOT / "renderers" / "react" / "src" / "Surface.tsx").read_text("utf-8"),
                re.M,
            )
        )
        undrawable = sorted(set(catalog["components"]) - react)
        assert not undrawable, f"the catalog offers {undrawable} and nothing renders them"


