"""Compiling A2UI Express, including while the model is still typing.

The compile itself is the SDK's — `ExpressParser.compile`, the reference
implementation, no port. What the SDK does not have is *streaming*:

    >>> ExpressParser(...).supports_streaming
    False
    >>> ExpressParser(...).process_chunk("root = Column([a])")
    NotImplementedError: Streaming is not supported by ExpressParser

So this module is the gap, and only the gap. When upstream ships a streaming
parser this becomes a thin adapter and then nothing at all.

Why it matters enough to write: the point of Express over raw A2UI JSON is that
a partial program is still a program. `root = Column([a, b])` compiles the
moment those three lines exist and recompiles when a fourth arrives, so the
surface paints while the model is typing rather than after it stops. Without
that the model's output is dead weight until the last token.

Recompiling the open block from scratch on every chunk is deliberate. It is
microseconds at these sizes, and it means a late line can revise a component
written earlier instead of being stuck with whatever was already emitted.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

warnings.filterwarnings("ignore")

from a2ui.inference_formats.experimental.express.parser import (  # noqa: E402
    A2UI_INFERENCE_CLOSE_TAG,
    A2UI_INFERENCE_OPEN_TAG,
    ExpressParser,
)

A2uiMessage = dict[str, Any]

# A capitalised name applied like a function: `FlightOption(...)`. Functions in
# the catalog are lower-camel (`formatCurrency`), so the case distinction alone
# separates the two without needing to know either list.
_CONSTRUCTOR = re.compile(r"\b([A-Z][A-Za-z0-9]*)\s*\(")

# Express's own constructs, which are not catalog components.
_NOT_COMPONENTS = frozenset({"Event"})

# A quoted string, single or double, with backslash escapes honoured.
_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", re.S)


def _without_strings(source: str) -> str:
    """The source with every string literal blanked out.

    Because a component name is found by pattern, and the pattern — a capital
    letter followed by a bracket — occurs in ordinary English. A picker offering

        {label: "San Francisco (SFO)", value: "SFO"}

    was read as a call to a component named `Francisco`, and "New York (JFK)" as
    one named `York`. The block was correct; this check rejected it, the model
    was told to write it again, and the traveller paid a whole extra round for a
    label with an airport code in it — which is every label this app draws.

    Newlines are preserved so a line number computed later still means what it
    says.
    """
    return _STRING.sub(lambda match: '"' + " " * max(0, len(match.group(0)) - 2) + '"', source)


class WrongControl(Exception):
    """A control bound to a decision it cannot express.

    Separate from a compile error because nothing is malformed: the block is
    valid Express and valid A2UI, and it draws. It just asks the question in a
    way that lets the answer be wrong, which nothing downstream can fix.
    """


class UnknownComponent(Exception):
    """The source names a component the catalog does not have.

    This exists because the SDK's compiler does not raise for it. Every other
    mistake it catches and explains well — a property that is not on the
    component, a static property given a binding, a syntax error — but an
    invented component name is *silently dropped*, and a surface made only of
    invented components compiles to `components: []`.

    Which is the worst possible outcome: a blank surface, no error, no repair
    turn, and nothing anywhere saying what happened. The traveller sees an empty
    box under a heading, exactly as if the tool had returned nothing.

    So the names are checked against the catalog before compiling, and the
    message names what is available — because the reader of this error is a
    model about to try again.
    """


def unknown_components(source: str, component_names: Iterable[str]) -> list[str]:
    """Component names in `source` that the catalog does not define."""
    known = set(component_names) | _NOT_COMPONENTS
    seen: list[str] = []
    for name in _CONSTRUCTOR.findall(_without_strings(source)):
        if name not in known and name not in seen:
            seen.append(name)
    return seen


@dataclass(frozen=True)
class Text:
    """Prose, outside any block."""

    delta: str
    type: Literal["text"] = "text"


@dataclass(frozen=True)
class Ui:
    """A block that compiled. `done` is False while it is still being written."""

    block_index: int
    messages: list[A2uiMessage]
    done: bool
    type: Literal["ui"] = "ui"


@dataclass(frozen=True)
class Failed:
    """A finished block that would not compile.

    `source` is the Express that failed, and it is not optional in practice: a
    compile error is otherwise a line and column into text nobody kept, which
    the host cannot show and the model cannot be told to fix.
    """

    block_index: int
    message: str
    source: str
    type: Literal["error"] = "error"


StreamEvent = Text | Ui | Failed


def _dangling_prefix(text: str, token: str) -> int:
    """Length of the tail of `text` that could still become `token`.

    The sentinel tags arrive split across chunks — `<a2` then `ui>` — and a
    naive `find` emits the first half as prose and then never recognises the
    tag. Holding back any tail that is a proper prefix of the token costs at
    most a few characters of latency and removes the whole class of bug.
    """
    for length in range(min(len(text), len(token) - 1), 0, -1):
        if text.endswith(token[:length]):
            return length
    return 0


@dataclass
class ExpressStream:
    """Splits a model's token stream into prose and compiled A2UI."""

    parser: ExpressParser
    #: Component names the catalog defines, for the check the SDK does not do.
    components: frozenset[str] = frozenset()
    #: The catalog's own validator, for the checks the *compiler* does not do.
    #:
    #: Compiling answers "is this Express?". It does not answer "is this a
    #: surface?" — a `Column([header, footer])` whose `footer` was never defined
    #: compiles happily and renders as a box with a hole in it. The SDK ships a
    #: validator that walks the compiled messages and says so, and running it is
    #: the difference between the model finding out and the traveller finding
    #: out.
    validator: Any = None
    _buffer: str = ""
    _inside: bool = False
    _block_source: str = ""
    _block_index: int = -1
    _last_emitted: str = ""
    _events: list[StreamEvent] = field(default_factory=list)

    def push(self, chunk: str) -> list[StreamEvent]:
        """Feeds a chunk and returns the events it produced."""
        self._buffer += chunk
        events: list[StreamEvent] = []

        while True:
            if not self._inside:
                open_at = self._buffer.find(A2UI_INFERENCE_OPEN_TAG)
                if open_at == -1:
                    hold = _dangling_prefix(self._buffer, A2UI_INFERENCE_OPEN_TAG)
                    emit = self._buffer[: len(self._buffer) - hold]
                    if emit:
                        events.append(Text(delta=emit))
                    self._buffer = self._buffer[len(self._buffer) - hold :]
                    return events

                prose = self._buffer[:open_at]
                if prose:
                    events.append(Text(delta=prose))
                self._buffer = self._buffer[open_at + len(A2UI_INFERENCE_OPEN_TAG) :]
                self._inside = True
                self._block_index += 1
                self._block_source = ""
                self._last_emitted = ""
                continue

            close_at = self._buffer.find(A2UI_INFERENCE_CLOSE_TAG)
            if close_at == -1:
                hold = _dangling_prefix(self._buffer, A2UI_INFERENCE_CLOSE_TAG)
                self._block_source += self._buffer[: len(self._buffer) - hold]
                self._buffer = self._buffer[len(self._buffer) - hold :]
                event = self._compile(done=False)
                if event:
                    events.append(event)
                return events

            self._block_source += self._buffer[:close_at]
            self._buffer = self._buffer[close_at + len(A2UI_INFERENCE_CLOSE_TAG) :]
            self._inside = False
            event = self._compile(done=True)
            if event:
                events.append(event)

    def end(self) -> list[StreamEvent]:
        """Flushes whatever is buffered when the model stops."""
        events: list[StreamEvent] = []
        if self._inside:
            # Stopped mid-block. Compile what there is: an unterminated block
            # usually still describes a complete tree, and half a surface beats
            # none.
            self._block_source += self._buffer
            self._buffer = ""
            self._inside = False
            event = self._compile(done=True)
            if event:
                events.append(event)
        elif self._buffer:
            events.append(Text(delta=self._buffer))
            self._buffer = ""
        return events

    def feed(self, chunks: Iterable[str]) -> list[StreamEvent]:
        """Every event from a whole stream. Convenience for tests and batches."""
        events: list[StreamEvent] = []
        for chunk in chunks:
            events.extend(self.push(chunk))
        events.extend(self.end())
        return events

    def _compile(self, *, done: bool) -> StreamEvent | None:
        source = self._block_source
        if not source.strip():
            return None
        # Nothing new to say if the block has not changed since the last emit.
        if not done and source == self._last_emitted:
            return None
        self._last_emitted = source

        try:
            # Before the SDK, because the SDK will not object: an invented
            # component compiles to nothing at all rather than to an error.
            if self.components:
                invented = unknown_components(source, self.components)
                if invented:
                    raise UnknownComponent(
                        f"No such component: {', '.join(invented)}. "
                        f"The catalog has {len(self.components)} components; "
                        f"use one of them or compose from Row, Column and Text."
                    )
            messages = self.parser.compile(source, is_final=done)
            # Only on a finished block. A tree still being written legitimately
            # refers to components a few tokens away from existing, and calling
            # that an error would reject every surface mid-stream.
            if done and self.validator is not None:
                self.validator.validate(messages)
            if done:
                # And the question has to be askable. A date in a text box is a
                # date the traveller can get wrong — see `controls.py`.
                from .controls import wrong_controls

                wrong = wrong_controls(messages)
                if wrong:
                    raise WrongControl(" ".join(wrong))
        except Exception as error:  # noqa: BLE001 - any parse failure, same handling
            # Mid-stream failures are the normal case: half a constructor is not
            # valid Express. Only a failure on a finished block is news.
            if not done:
                return None
            return Failed(block_index=self._block_index, message=str(error), source=source)

        return Ui(block_index=self._block_index, messages=messages, done=done)
