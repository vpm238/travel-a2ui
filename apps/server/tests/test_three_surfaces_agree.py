"""The three ways in have to behave like one agent.

There are three front doors — the Interactions API for typed turns, the Live API
for calls, and MCP for Claude — and one agent behind them. Keeping that true has
been done by remembering, and remembering does not work. In a single afternoon
the same class of bug was fixed three separate times:

  * Inline surfaces collided, so a new card overwrote the last. Fixed for typed
    turns; found again weeks later in voice, where surfaces were keyed by *what*
    they showed rather than *when*, so a second flight search replaced the first
    mid-call.
  * The departure-airport hint was computed for typed turns and simply never
    passed to a call, so voice asked people to say an airport code out loud —
    the exact question the hint exists to avoid.
  * Invented component names were caught by the streaming compiler and not by
    the tool, and the tool is what MCP hosts and voice calls both go through, so
    a typo became a grey box and a success reported to the model.

None of those looked like a bug from inside the path that had it. Each was a
thing one door did and another did not, and the only way to see it was to put
them side by side — which is what this file does.

It asserts *agreement*, not implementation. Where the three genuinely differ —
Live takes a different tool shape, MCP has no conversation to hold state in —
the difference is named here as a fact, so that changing it has to be deliberate
rather than accidental.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "parity"))


class TestOneVocabulary:
    """All three compose from the same catalog and the same skills."""

    def test_the_same_catalog_id_everywhere(self) -> None:
        from travel_a2ui.agent import CATALOG_ID, CATALOG_JSON

        assert CATALOG_ID == CATALOG_JSON["$id"]

    def test_every_door_offers_the_same_surface_tools(self) -> None:
        """A tool Claude can call and a call cannot is a different agent."""
        from travel_a2ui.voice import MCP_TOOLS, voice_tools

        plugin = {tool["name"] for tool in MCP_TOOLS if tool["name"].startswith("show_")}
        spoken = {tool["name"] for tool in voice_tools() if tool["name"].startswith("show_")}
        assert plugin == spoken, f"only one door has {plugin ^ spoken}"

    def test_every_door_can_reach_the_data(self) -> None:
        """The thesis, asserted on the door where it used to be false.

        `tools.py` opens by saying tools return data and the skill turns data
        into UI, "because a tool returning pre-rendered cards moves that
        decision into this file, where it would be frozen and wrong half the
        time". MCP exposed six pre-rendered cards and no way to reach a flight,
        so Claude was the one caller for whom that paragraph was untrue — it
        could pick from six layouts or write Express blind.
        """
        from travel_a2ui.tools import gemini_tools, mcp_data_tools

        typed = {tool["name"] for tool in gemini_tools()}
        plugin = {tool["name"] for tool in mcp_data_tools()}
        assert typed == plugin, f"Claude cannot {sorted(typed - plugin)}"

    def test_the_typed_path_and_a_call_share_the_data_tools(self) -> None:
        from travel_a2ui.tools import gemini_tools
        from travel_a2ui.voice import voice_tools

        typed = {tool["name"] for tool in gemini_tools()}
        spoken = {tool["name"] for tool in voice_tools()}
        assert typed <= spoken, f"a call cannot {sorted(typed - spoken)}"


class TestOneSetOfRules:
    """The prompt is assembled once; every door gets the same rules."""

    def test_a_call_is_given_the_same_inventory(self) -> None:
        """Voice used to be handed a prompt with no idea what data existed."""
        from travel_a2ui.providers.fixture import _DESTINATIONS
        from travel_a2ui.skills import build_system_prompt

        said = build_system_prompt(
            variant="express-monolithic",
            surface="inline",
            surface_id="voice-1",
            catalog_id="travel",
            trip={},
            today="2027-03-01",
        )
        for entry in _DESTINATIONS:
            assert entry["city"] in said

    def test_a_call_can_be_told_where_they_are_flying_from(self) -> None:
        """The gap that made voice ask for an airport code out loud.

        The session has to be able to carry the hint; that it is passed is
        asserted where the socket is opened. This is the narrower claim that the
        seam exists at all, which is the part that was missing.
        """
        import dataclasses

        from travel_a2ui.voice import VoiceSession

        fields = {field.name for field in dataclasses.fields(VoiceSession)}
        assert "origin_hint" in fields


class TestOneSurfacePerDrawing:
    """A card is a thing that was asked, on every door that has a feed."""

    def test_a_call_gives_each_drawing_its_own_id(self) -> None:
        from travel_a2ui.surfaces import _surface_id_for

        first = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-1"})
        second = _surface_id_for("inline", "mcp-flights", {"surfaceId": "voice-2"})
        assert first != second

    def test_a_panel_is_still_singular(self) -> None:
        """The opposite case, and the reason this is not a blanket rule."""
        from travel_a2ui.surfaces import _surface_id_for

        assert _surface_id_for("sidebar", "mcp-flights", {"surfaceId": "voice-9"}) == "mcp-sidebar"


class TestOneIdeaOfBroken:
    """An invented component is an error on every door, not just the streamed one."""

    def test_the_tool_rejects_what_the_stream_rejects(self) -> None:
        import asyncio

        from travel_a2ui.agent import COMPONENT_NAMES
        from travel_a2ui.express import unknown_components
        from travel_a2ui.providers.fixture import FixtureProvider
        from travel_a2ui.surfaces import build_surface

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
    `voice.py`, and the exception is exactly where behaviour drifted: it is the
    door that was missing the inventory, missing the origin hint, and keyed its
    surfaces differently. Prose living somewhere nobody edits is prose nobody
    keeps in step.
    """

    def test_every_brief_is_a_file(self) -> None:
        briefs = sorted(path.name for path in (ROOT / "prompts").glob("*.md"))
        assert briefs == [
            "role.md",
            "surface-home.md",
            "surface-inline.md",
            "surface-sidebar.md",
            "voice.md",
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
        from travel_a2ui.voice import VOICE_BRIEF

        assert VOICE_BRIEF == (ROOT / "prompts" / "voice.md").read_text("utf-8").strip()


class TestOneImplementationNotThree:
    """The steps every door performs are performed by the same code.

    Agreement tested by assertion is agreement maintained by luck: the suite
    above catches drift *after* someone writes it. These are the places where
    drift is no longer possible because there is only one implementation left.

    Not a rewrite. `agent.py`, `voice.py` and `mcp.py` are still three loops —
    an SSE generator, a websocket pump and a JSON-RPC handler, which is what
    their transports actually are. What they no longer each own is the work
    that has nothing to do with transport.
    """

    def test_the_panels_are_refreshed_by_one_function(self) -> None:
        import inspect

        from travel_a2ui import agent, voice

        for module in (agent, voice):
            source = inspect.getsource(module)
            assert "panel_events(" in source, f"{module.__name__} does not use it"
            # The loop it replaced. Two copies is how the typed path grew a
            # per-turn surface id and a departure hint that voice did not.
            assert "for surface_id in STANDING_SURFACES:\n            updates" not in source

    def test_a_surface_is_compiled_by_one_function(self) -> None:
        import inspect

        from travel_a2ui import mcp, voice

        for module in (mcp, voice):
            source = inspect.getsource(module)
            assert "compile_surface(" in source, f"{module.__name__} compiles its own"
            assert ".compile(surface.express" not in source

    def test_the_two_halves_of_drawing_stay_together(self) -> None:
        """`build_surface` validates; `compile_surface` emits. Both or neither.

        The validation that rejects an invented component went into
        `build_surface` and reached MCP and voice both — but only because they
        happened to share that call. Had either compiled from its own source,
        it would have kept the bug.
        """
        import inspect

        from travel_a2ui import surfaces

        source = inspect.getsource(surfaces)
        assert "def compile_surface(" in source
        assert "def build_surface(" in source
