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

from travel_a2ui.brain.express import (  # noqa: E402
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

    def test_does_not_read_english_inside_a_string_as_a_component(self, components):
        """The bug this check was costing a round to every turn.

        A component name is found by pattern — a capital letter followed by a
        bracket — and that pattern occurs in ordinary English. Every picker this
        app draws labels an airport the way a person writes it:

            {label: "San Francisco (SFO)", value: "SFO"}

        which was read as a call to a component named `Francisco`, and "New York
        (JFK)" as one named `York`. The block was correct. The model was told it
        was wrong, wrote it again, and the traveller waited through an extra
        model round for a label with an airport code in it.
        """
        source = (
            't = Text("Plan your trip from San Francisco to New York")\n'
            'p = ChoicePicker("From", [{label: "San Francisco (SFO)", value: "SFO"}])'
        )
        assert unknown_components(source, components) == []

    def test_a_child_that_was_never_defined_is_caught(self, components):
        """Compiling is not validating, and the difference is visible.

        `Column([header, footer])` where `footer` was never defined is valid
        Express: it compiles, it emits, and it renders as a box with a hole in
        it. The SDK ships a validator that walks the compiled messages and says
        so — which is the difference between the model finding out, in the same
        turn, and the traveller finding out.
        """
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"),
            components=components,
            validator=_CATALOG.validator,
        )
        source = 'head = Text("Madrid")\nroot = Column([head, footer])'
        events = stream.feed([OPEN + source + CLOSE])
        failures = [event for event in events if isinstance(event, Failed)]
        assert failures, "this compiles; only the validator objects"
        assert "footer" in failures[0].message

    def test_a_whole_surface_still_passes(self, components):
        """The check has to let real work through, or it is just an outage."""
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"),
            components=components,
            validator=_CATALOG.validator,
        )
        source = 'head = Text("Madrid", variant="h3")\nroot = Column([head])'
        events = stream.feed([OPEN + source + CLOSE])
        assert not [event for event in events if isinstance(event, Failed)]
        assert [event for event in events if isinstance(event, Ui)]

    def test_still_finds_an_invented_component_beside_one(self, components):
        """Blanking the strings must not blank the check."""
        source = 'p = ChoicePicker("New York (JFK)")\nx = Nonesuch("San Jose (SJC)")'
        assert unknown_components(source, components) == ["Nonesuch"]


class TestTheQuestionIsAskable:
    """A date in a text box is a date the traveller can get wrong.

    The model reaches for `TextField` whenever it is not thinking about it,
    because a text box is the thing that always works — and the result accepts
    "next tuesday", "12/4" and "April 12ish" and then prices the wrong week.
    Nothing downstream can fix a question asked badly, so the surface is
    rejected before it is drawn and the model is told what to use instead.
    """

    def test_a_date_in_a_text_box_is_refused(self, components):
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"), components=components, validator=_CATALOG.validator
        )
        source = 'when = TextField("When", $/trip/startDate)\nroot = Column([when])'
        failures = [
            event
            for event in stream.feed([OPEN + source + CLOSE])
            if isinstance(event, Failed)
        ]
        assert failures
        assert "DateRangePicker" in failures[0].message

    def test_an_airport_in_a_text_box_is_refused(self, components):
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"), components=components, validator=_CATALOG.validator
        )
        source = 'from = TextField("From", $/trip/origin)\nroot = Column([from])'
        failures = [
            event
            for event in stream.feed([OPEN + source + CLOSE])
            if isinstance(event, Failed)
        ]
        assert failures
        assert "ChoicePicker" in failures[0].message

    def test_the_right_controls_pass(self, components):
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"), components=components, validator=_CATALOG.validator
        )
        source = (
            'from = ChoicePicker("From", "mutuallyExclusive", '
            '[{label: "New York (JFK)", value: "JFK"}], $/trip/origin)\n'
            'when = DateRangePicker("Dates", $/trip/startDate, $/trip/endDate)\n'
            'who = TravelerCounter("Travelers", $/trip/travelers)\n'
            "root = Column([from, when, who])"
        )
        events = stream.feed([OPEN + source + CLOSE])
        assert not [event for event in events if isinstance(event, Failed)]

    def test_a_text_field_is_still_right_for_prose(self, components):
        """The check is about decisions, not about text boxes."""
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("inline-1"), components=components, validator=_CATALOG.validator
        )
        source = 'why = TextField("What is the trip for?", $/trip/notes)\nroot = Column([why])'
        events = stream.feed([OPEN + source + CLOSE])
        assert not [event for event in events if isinstance(event, Failed)]

    def test_reading_a_decision_back_is_not_asking_for_one(self, components):
        """A panel that says "12-19 April" as text is correct."""
        from travel_a2ui.doors.interactions import _CATALOG, _parser

        stream = ExpressStream(
            parser=_parser("sidebar"), components=components, validator=_CATALOG.validator
        )
        source = 'when = Text($/trip/startDate)\nroot = Column([when])'
        events = stream.feed([OPEN + source + CLOSE])
        assert not [event for event in events if isinstance(event, Failed)]
