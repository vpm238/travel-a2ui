"""The streaming splitter: the one thing the SDK does not do.

These are written against the behaviour rather than the implementation, because
the implementation is meant to be temporary — when upstream ships a streaming
parser this module becomes an adapter and then disappears, and the tests should
survive that.

The cases that matter are the ones a real token stream produces and a naive
`find` gets wrong: a sentinel tag split across two chunks, a block that is still
being written, and a block the model never closed.
"""

from __future__ import annotations

import json
import pathlib
import warnings

import pytest

warnings.filterwarnings("ignore")

from a2ui.inference_formats.experimental.express.parser import (  # noqa: E402
    A2UI_INFERENCE_CLOSE_TAG,
    A2UI_INFERENCE_OPEN_TAG,
    ExpressParser,
)
from a2ui.schema.catalog import A2uiCatalog, CatalogConfig  # noqa: E402

from travel_a2ui.express import (  # noqa: E402
    ExpressStream,
    Failed,
    Text,
    Ui,
    unknown_components,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
CATALOG = ROOT / "catalogs" / "a2ui-travel" / "catalog.json"

OPEN = A2UI_INFERENCE_OPEN_TAG
CLOSE = A2UI_INFERENCE_CLOSE_TAG

SURFACE = 'surface("inline-1")\nhead = Text("Madrid", variant="h2")\nroot = Column([head])'


@pytest.fixture(scope="module")
def catalog() -> A2uiCatalog:
    config = CatalogConfig.from_path("travel", str(CATALOG))
    return A2uiCatalog.from_config(config, version="0.9.1")


@pytest.fixture(scope="module")
def parser(catalog: A2uiCatalog) -> ExpressParser:
    return ExpressParser(catalog=catalog, surface_id="inline-1", version="v0.9.1")


@pytest.fixture(scope="module")
def components(catalog: A2uiCatalog) -> frozenset[str]:
    return frozenset(catalog.catalog_schema["components"])


def stream(parser: ExpressParser, components: frozenset[str] = frozenset()) -> ExpressStream:
    return ExpressStream(parser=parser, components=components)


def kinds(events) -> list[str]:
    return [event.type for event in events]


def texts(events) -> str:
    return "".join(event.delta for event in events if isinstance(event, Text))


def surfaces(events) -> list[Ui]:
    return [event for event in events if isinstance(event, Ui)]


class TestProse:
    def test_passes_text_outside_a_block_straight_through(self, parser):
        events = stream(parser).feed(["Here are ", "four options."])
        assert texts(events) == "Here are four options."
        assert not surfaces(events)

    def test_keeps_prose_before_and_after_a_block(self, parser):
        events = stream(parser).feed([f"Before {OPEN}{SURFACE}{CLOSE} after"])
        assert texts(events) == "Before  after"
        assert len(surfaces(events)) == 1


class TestSplitSentinels:
    """A tag arriving in pieces is the normal case, not an edge case."""

    def test_recognises_an_open_tag_split_across_chunks(self, parser):
        # `<a2` / `ui>` — a naive find emits the first half as prose and then
        # never sees a tag at all.
        half = len(OPEN) // 2
        events = stream(parser).feed([OPEN[:half], OPEN[half:], SURFACE, CLOSE])
        assert len(surfaces(events)) >= 1
        assert OPEN[:half] not in texts(events)

    def test_recognises_a_close_tag_split_across_chunks(self, parser):
        half = len(CLOSE) // 2
        events = stream(parser).feed([OPEN, SURFACE, CLOSE[:half], CLOSE[half:], " done"])
        assert texts(events).strip() == "done"

    def test_holds_back_a_tail_that_could_still_become_a_tag(self, parser):
        chunk = stream(parser)
        # A lone `<` might be the start of a tag, so it is not prose yet.
        produced = chunk.push("cost is 400 <")
        assert texts(produced) == "cost is 400 "
        # …and when it turns out not to be, it arrives.
        assert texts(chunk.end()) == "<"


class TestPartialBlocks:
    def test_compiles_a_block_before_it_is_closed(self, parser):
        """The whole reason this exists: paint while the model is typing."""
        chunk = stream(parser)
        chunk.push(OPEN + 'surface("inline-1")\nhead = Text("Madrid", variant="h2")\n')
        produced = chunk.push("root = Column([head])")

        drawn = surfaces(produced)
        assert drawn, "a complete tree should compile before the closing tag"
        assert drawn[-1].done is False

    def test_says_nothing_while_the_block_is_not_yet_a_tree(self, parser):
        chunk = stream(parser)
        chunk.push(OPEN + 'surface("inline-1")\n')
        # Half a constructor is not valid Express, and mid-stream that is
        # expected rather than an error.
        assert kinds(chunk.push("head = Text(")) == []

    def test_does_not_reemit_an_unchanged_block(self, parser):
        chunk = stream(parser)
        chunk.push(OPEN + SURFACE)
        assert kinds(chunk.push("")) == []

    def test_marks_the_block_done_when_it_closes(self, parser):
        events = stream(parser).feed([OPEN + SURFACE + CLOSE])
        assert surfaces(events)[-1].done is True


class TestEnding:
    def test_compiles_a_block_the_model_never_closed(self, parser):
        # Stopping mid-block is common when a turn is cut short; an
        # unterminated block usually still describes a complete tree.
        events = stream(parser).feed([OPEN + SURFACE])
        drawn = surfaces(events)
        assert drawn and drawn[-1].done is True

    def test_reports_a_finished_block_that_will_not_compile(self, parser):
        events = stream(parser).feed([OPEN + 'h = Text("x", nonsense="y")' + CLOSE])
        failures = [event for event in events if isinstance(event, Failed)]
        assert failures, "a closed block that fails should be reported"
        # The source has to come back: a line and column into text nobody kept
        # is not something a host can show or a model can repair.
        assert "nonsense" in failures[0].source

    def test_emits_prose_as_it_arrives_rather_than_holding_it(self, parser):
        # Latency: text that cannot become a sentinel goes out on the chunk it
        # arrived in, and `end()` then has nothing left to flush.
        chunk = stream(parser)
        assert texts(chunk.push("nearly")) == "nearly"
        assert chunk.end() == []


class TestAgreementWithTheReference:
    """A streamed block compiles to what the SDK compiles in one go."""

    def test_streamed_and_whole_produce_the_same_messages(self, parser):
        whole = parser.compile(SURFACE, is_final=True)

        chunk = stream(parser)
        events = []
        for piece in [OPEN] + [SURFACE[i : i + 7] for i in range(0, len(SURFACE), 7)] + [CLOSE]:
            events.extend(chunk.push(piece))
        events.extend(chunk.end())

        assert json.dumps(surfaces(events)[-1].messages) == json.dumps(whole)


class TestTheGapTheSdkLeaves:
    """An invented component name, which the SDK compiles to silence.

    Every other mistake the reference compiler catches and explains: a property
    that is not on the component, a static property handed a binding, a syntax
    error. An unknown *component* it drops — so a surface made of invented
    components compiles to `components: []` and the traveller gets a blank box
    with no error anywhere. That is the one check this server adds.
    """

    def test_the_sdk_really_does_compile_an_invented_component_to_nothing(self, parser):
        # Asserted rather than asserted-about, because the moment upstream fixes
        # this the extra check here should be deleted, and this test is what
        # will say so.
        messages = parser.compile("root = NoSuchComponent()", is_final=True)
        assert messages[-1]["updateComponents"]["components"] == []

    def test_reports_an_invented_component_instead(self, parser, components):
        events = stream(parser, components).feed([OPEN + "root = NoSuchComponent()" + CLOSE])
        failures = [event for event in events if isinstance(event, Failed)]
        assert failures
        assert "NoSuchComponent" in failures[0].message

    def test_leaves_real_components_alone(self, components):
        assert unknown_components("root = Column([a])\nh = FlightOption()", components) == []

    def test_does_not_mistake_a_function_for_a_component(self, components):
        # Catalog functions are lower-camel, so case alone separates them.
        assert unknown_components('t = Text(formatCurrency(value: 4))', components) == []

    def test_does_not_mistake_express_own_constructs_for_components(self, components):
        assert unknown_components('b = Button("Go", Event("go", {}))', components) == []
