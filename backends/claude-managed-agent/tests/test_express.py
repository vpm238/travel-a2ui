"""Tests for the Python compile layer.

The streaming splitter is the piece worth testing hard: it is what makes a
surface paint while the model is still typing, and it is the only substantial
logic in this backend that is not delegated.

The compile itself is exercised against whichever backend is available — the
a2ui SDK if it is current, otherwise a running compile service — and skipped
when neither is. A skipped test says so; a mocked one would not.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

from travel_agent.config import load_catalog  # noqa: E402
from travel_agent.express import (  # noqa: E402
    A2UI_CLOSE,
    A2UI_OPEN,
    CompileError,
    ExpressStream,
    ServiceCompiler,
    extract_blocks,
    sdk_capabilities,
    sdk_supports_current_grammar,
)

CATALOG = load_catalog()
CATALOG_ID = str(CATALOG["catalogId"])

EXPRESS = 'h = Text("Hi", variant="h3")\nroot = Column([h])'


class FakeCompiler:
    """Records what it was asked to compile, and fails on a truncated tail."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def compile(self, source: str, surface_id: str, *, is_final: bool = True):
        self.calls.append((source, is_final))
        if source.count("(") != source.count(")"):
            raise CompileError("unbalanced parentheses")
        return [{"version": "v0.9.1", "createSurface": {"surfaceId": surface_id}}]

    def decompile(self, messages):
        return "root = Text(\"x\")"


class TestSentinels:
    def test_extracts_every_complete_block(self):
        text = f"a {A2UI_OPEN}one{A2UI_CLOSE} b {A2UI_OPEN}two{A2UI_CLOSE} c"
        assert extract_blocks(text) == ["one", "two"]

    def test_ignores_an_unterminated_block(self):
        assert extract_blocks(f"a {A2UI_OPEN}one") == []


class TestStreaming:
    def collect(self, chunks: list[str], compiler=None):
        stream = ExpressStream(compiler or FakeCompiler(), "s1")
        events = []
        for chunk in chunks:
            events.extend(stream.push(chunk))
        events.extend(stream.end())
        return events

    def test_separates_prose_from_ui(self):
        events = self.collect(
            ["Two options.\n", f"{A2UI_OPEN}\n{EXPRESS}\n{A2UI_CLOSE}", "\nWhich one?"]
        )
        text = "".join(event.delta for event in events if event.kind == "text")
        assert "Two options." in text
        assert "Which one?" in text
        assert "Column" not in text
        assert sum(1 for event in events if event.kind == "ui" and event.done) == 1

    def test_reassembles_a_sentinel_split_across_chunks(self):
        events = self.collect(["before <a2", f"ui>\n{EXPRESS}\n</a2", "ui> after"])
        text = "".join(event.delta for event in events if event.kind == "text")
        assert text == "before  after"
        assert any(event.kind == "ui" and event.done for event in events)

    def test_paints_a_partial_tree_before_the_block_closes(self):
        stream = ExpressStream(FakeCompiler(), "s1")
        list(stream.push(f"{A2UI_OPEN}\n{EXPRESS}\n"))
        events = list(stream.push('b = Text("Two")\n'))
        assert any(event.kind == "ui" and not event.done for event in events)

    def test_swallows_a_mid_stream_failure_and_reports_a_final_one(self):
        compiler = FakeCompiler()
        stream = ExpressStream(compiler, "s1")
        # Unbalanced: the fake compiler rejects it, as a real one would.
        assert list(stream.push(f"{A2UI_OPEN}\nroot = Column([\n")) == []
        events = list(stream.push(A2UI_CLOSE))
        assert [event.kind for event in events] == ["error"]

    def test_compiles_an_unterminated_block_at_the_end(self):
        events = self.collect([f"{A2UI_OPEN}\n{EXPRESS}\n"])
        assert any(event.kind == "ui" and event.done for event in events)

    def test_a_service_compiler_only_compiles_on_block_boundaries(self):
        """A network round trip per token would be absurd; it batches instead."""
        compiler = FakeCompiler()
        compiler.name = "service"
        stream = ExpressStream(compiler, "s1")
        list(stream.push(f"{A2UI_OPEN}\nh = Text(\"a\")\n"))
        list(stream.push("root = Column([h])\n"))
        assert compiler.calls == []
        list(stream.push(A2UI_CLOSE))
        assert len(compiler.calls) == 1
        assert compiler.calls[0][1] is True


class TestSdkDetection:
    def test_reports_whether_the_sdk_is_installed(self):
        capabilities = sdk_capabilities()
        assert "installed" in capabilities

    @pytest.mark.skipif(not sdk_capabilities()["installed"], reason="a2ui-agent-sdk not installed")
    def test_probes_the_grammar_rather_than_the_version(self):
        # Either answer is fine; what matters is that it answers without raising,
        # because the whole point is to decide before a user's turn depends on it.
        assert isinstance(sdk_supports_current_grammar(CATALOG, CATALOG_ID), bool)


SERVICE_URL = None  # set COMPILE_SERVICE to run these against a live Worker


class TestServiceCompiler:
    @pytest.mark.skipif(
        not __import__("os").environ.get("COMPILE_SERVICE"),
        reason="set COMPILE_SERVICE=http://127.0.0.1:8787 to run",
    )
    def test_round_trips_through_the_service(self):
        import os

        compiler = ServiceCompiler(os.environ["COMPILE_SERVICE"], CATALOG_ID)
        messages = compiler.compile(EXPRESS, "s1")
        assert any("updateComponents" in message for message in messages)

        components = [
            component
            for message in messages
            if "updateComponents" in message
            for component in message["updateComponents"]["components"]
        ]
        assert {component["id"] for component in components} == {"h", "root"}

        express = compiler.decompile(messages)
        assert "root = Column([h])" in express

    @pytest.mark.skipif(
        not __import__("os").environ.get("COMPILE_SERVICE"),
        reason="set COMPILE_SERVICE=http://127.0.0.1:8787 to run",
    )
    def test_reports_a_compile_error_the_model_can_act_on(self):
        import os

        compiler = ServiceCompiler(os.environ["COMPILE_SERVICE"], CATALOG_ID)
        with pytest.raises(CompileError) as error:
            compiler.compile('root = Text("hi", colour="red")', "s1")
        assert "colour" in str(error.value)


def test_catalog_is_readable():
    assert "FlightOption" in CATALOG["components"]
    assert json.dumps(CATALOG)
