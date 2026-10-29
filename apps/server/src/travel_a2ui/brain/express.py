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

from a2ui.inference_formats.express.parser import (  # noqa: E402
    A2UI_INFERENCE_CLOSE_TAG,
    A2UI_INFERENCE_OPEN_TAG,
    ExpressParser,
)

from .macros import expand as expand_macros  # noqa: E402
from .wire import components_of  # noqa: E402

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


class MissingProperty(Exception):
    """A component was written without a property the catalog requires.

    Separate from a compile error because the compiler does not raise for it —
    it emits the component with the property absent, and the catalog validator
    refuses the whole message at the end of the turn. Separate from
    `UnknownComponent` because the component is real and the mistake is in how
    it was called, which is a different sentence to write back.
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


def nearest_components(invented: Iterable[str], known: Iterable[str]) -> str:
    """"No such component: DateInput" is true and not much use on its own.

    The reader of that message is a model about to write the block again, and
    the names it reaches for are near-misses rather than nonsense: `DateInput`
    for `DateTimeInput`, `DateRangeField` for `DateRangePicker`, `NumberField`
    for `TextField`. Naming the closest real one turns a round spent guessing
    into a round spent fixing — and the traveller is watching a spinner for
    every one of them.
    """
    import difflib

    names = sorted(known)
    said = []
    for name in invented:
        close = difflib.get_close_matches(name, names, n=2, cutoff=0.6)
        if close:
            said.append(f"`{name}` → did you mean {' or '.join(f'`{c}`' for c in close)}?")
    return " ".join(said)


def as_wire(messages: Any) -> list[A2uiMessage]:
    """Compiled messages as the plain dictionaries the rest of this app passes around.

    The SDK changed what `compile` hands back: through agent-sdk 0.7 it was
    already-plain dicts, and from 0.9 it is a list of typed pydantic models.
    Everything downstream of here — the surface passes, the SSE encoder, the
    goldens, the tests — reads messages with `.get("createSurface")`, and a
    model answers that with an AttributeError at the one moment a traveller is
    waiting for a surface.

    `by_alias` matters and is easy to miss: 1.0 renamed the data-binding key to
    `@path`, which is not a legal Python attribute name, so the models carry it
    under an alias. Dumping without it produces `path` — a 0.9 payload wearing
    a 1.0 version number, which every renderer then ignores.
    """
    out: list[A2uiMessage] = []
    for message in messages:
        if isinstance(message, dict):
            out.append(message)
        elif hasattr(message, "model_dump"):
            out.append(message.model_dump(exclude_none=True, by_alias=True))
        else:  # pragma: no cover - no SDK has returned anything else
            raise TypeError(f"not an A2UI message: {type(message).__name__}")
    return out


def required_properties(catalog_schema: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Per component, the properties the catalog will not validate without.

    Pulled out of the schema once at import rather than read per turn, and kept
    beside `nearest_components` because it exists for the same reason: to answer
    a compile failure in the words the model needs to fix it.
    """
    #: Not properties anyone passes: `component` is the discriminator and `id`
    #: is the name the block gave it, both supplied by the compiler.
    supplied = ("component", "id")

    out: dict[str, tuple[str, ...]] = {}
    for name, component in (catalog_schema.get("components") or {}).items():
        needed: list[str] = []
        # Two shapes, because the SDK changed which one a loaded catalog has.
        # Through agent-sdk 0.7 a component was an `allOf` of its own schema
        # and the shared ones, and `required` sat inside the first branch. 0.9
        # flattens that before handing it over, so `required` is on the
        # component itself. Reading only the old shape found nothing at all —
        # and "nothing" is indistinguishable here from "this component
        # requires nothing", so every missing-property complaint quietly became
        # the compiler's own, without the order to pass them in.
        branches = [component, *(b for b in component.get("allOf", []) if isinstance(b, dict))]
        for branch in branches:
            for prop in branch.get("required") or ():
                if prop not in supplied and prop not in needed:
                    needed.append(prop)
        if needed:
            out[name] = tuple(needed)
    return out



def _with_the_order(refused: Exception, required: dict[str, tuple[str, ...]]) -> Exception:
    """The compiler's complaint, plus the order the properties go in.

    "missing required property 'value'" is true and not actionable in a
    positional DSL: the model has to know that `DateTimeInput` takes its label
    first. The component is named in the compiler's own message, so this finds
    it there rather than re-deriving it from the source.
    """
    said = str(refused)
    for name, properties in required.items():
        if f"'{name}'" in said or f'"{name}"' in said:
            return MissingProperty(
                f"{said} `{name}` takes {', '.join(properties)}, in that order."
            )
    return refused


def missing_properties(
    messages: list[dict[str, Any]], required: dict[str, tuple[str, ...]]
) -> list[str]:
    """Components in `messages` that lack a property the catalog requires.

    The validator already refuses these. What it does not do is say which
    component or which property: a failure arrives as the whole message dumped
    back with "is not valid under any of the given schemas", followed by the
    schema alternatives it was not valid under. There is nothing in it to act
    on, and the reader is a model with one repair turn to spend.

    Worse, the validator runs over the finished message list, so the surface
    fails *entire*. One date field written without its label, and the traveller
    gets an empty screen — no error, no partial surface, nothing.

    So when validation fails, this says what a person reading the source would
    have said: which component, which property, what to pass.
    """
    said: list[str] = []
    for message in messages:
        for component in components_of(message):
            name = component.get("component")
            absent = [p for p in required.get(name, ()) if p not in component]
            if absent:
                said.append(
                    f"`{name}` is missing required {'properties' if len(absent) > 1 else 'property'} "
                    f"{', '.join(f'`{p}`' for p in absent)}. "
                    f"It takes {', '.join(required[name])} — pass them in that order, "
                    "or by name."
                )
    return said


def unknown_components(source: str, component_names: Iterable[str]) -> list[str]:
    """Component names in `source` that the catalog does not define."""
    known = set(component_names) | _NOT_COMPONENTS
    seen: list[str] = []
    for name in _CONSTRUCTOR.findall(_without_strings(source)):
        if name not in known and name not in seen:
            seen.append(name)
    return seen


#: The opening sentinel, as written rather than as specified.
#:
#: The contract says `<a2ui>` and the model writes `<a2ui surface="inline-1">`
#: often enough to matter. Matched literally, that tag is not found at all — so
#: the block is not a block, and every line of Express inside it goes to the
#: traveller as prose. Measured on the reported turn: fourteen and a half
#: seconds, no surface, and a wall of `departure = DateInput label: …` on screen.
#:
#: The attributes are ignored rather than honoured. `surface("inline-1")` inside
#: the block is the mechanism, and a tag attribute saying something different
#: would be a second way to say it that nothing else reads.
_OPEN = re.compile(r"<a2ui\b[^>]*>", re.IGNORECASE)
_CLOSE = re.compile(r"</\s*a2ui\s*>", re.IGNORECASE)


def _first_tag(text: str, pattern: re.Pattern[str], stem: str) -> tuple[int, int] | None:
    """Where the next tag starts and ends, or None if it has not arrived yet.

    Returns None both when there is no tag and when one has *started* and not
    finished — `<a2ui surf` with the rest still in flight. The caller holds the
    tail either way, which is what `_dangling_prefix` did for a fixed token and
    cannot do for one whose length is not known in advance.
    """
    match = pattern.search(text)
    if match:
        return match.start(), match.end()
    # An unterminated tag: the stem is present with no `>` after it.
    at = text.lower().rfind(stem)
    if at != -1 and ">" not in text[at:]:
        return None
    return None


def _held_for_tag(text: str, pattern: re.Pattern[str], stem: str) -> int:
    """Length of the tail to hold because it could still become a tag.

    Case-insensitive throughout, and `_dangling_prefix` is not — which is not a
    detail: fed one character at a time, `<A` is not a prefix of `<a2ui` by that
    comparison, so it was emitted as prose and the tag could never be recognised
    afterwards. The stream is the one place where being nearly right has to
    still work.
    """
    lowered = text.lower()
    at = lowered.rfind(stem)
    if at != -1 and ">" not in text[at:]:
        return len(text) - at
    return _dangling_prefix(lowered, stem)


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
    #: A complaint about a surface that is nonetheless valid.
    #:
    #: A compile error produces no surface, so rejecting it costs nothing. A
    #: surface that asks for none of what the trip is waiting on is different:
    #: it compiles, it renders, and it is merely unhelpful. Rejecting *that*
    #: turned a useless dashboard into an empty screen whenever the retry did
    #: not recover — measured over 36 openings, drawing fell from 60% to 47%
    #: when the check was added, which is the check making the product worse.
    #:
    #: So it is drawn, and the complaint rides along for the door to act on. A
    #: correction must never leave the screen emptier than it found it.
    incomplete: str | None = None
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
    #: Anything exposing `validate(messages)`, for the checks the *compiler*
    #: does not do.
    #:
    #: Compiling answers "is this Express?". It does not answer "is this a
    #: surface?" — a `Column([header, footer])` whose `footer` was never defined
    #: compiles happily and renders as a box with a hole in it. The SDK walks
    #: the compiled messages and says so, and running it is the difference
    #: between the model finding out and the traveller finding out.
    #:
    #: Typed by the call it makes rather than by the class it expects, because
    #: the class moved: through agent-sdk 0.6 this was `catalog.validator`, and
    #: in 0.7 `validator` became a bare `PayloadValidator` (per-component and
    #: per-function only) while `validate(messages)` moved up onto the catalog
    #: itself. Callers now pass the catalog. Nothing here had to change, which
    #: is the argument for describing the contract instead of the type.
    validator: Any = None
    #: Every path a per-hop party counter would bind to, in route order.
    #:
    #: Lets a finished block be checked for asking *some* of the hops who is on
    #: them — see `half_asked`. Empty, or a single hop, and the check does not
    #: run.
    hops: tuple[str, ...] = ()
    #: Per component, what the catalog requires — for explaining a validator no.
    required: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: The trip this turn's macros expand against. See `brain/macros.py`.
    trip: dict[str, Any] = field(default_factory=dict)
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
                found = _first_tag(self._buffer, _OPEN, "<a2ui")
                if found is None:
                    hold = _held_for_tag(self._buffer, _OPEN, "<a2ui")
                    emit = self._buffer[: len(self._buffer) - hold]
                    if emit:
                        events.append(Text(delta=emit))
                    self._buffer = self._buffer[len(self._buffer) - hold :]
                    return events

                open_at, open_end = found
                prose = self._buffer[:open_at]
                if prose:
                    events.append(Text(delta=prose))
                self._buffer = self._buffer[open_end:]
                self._inside = True
                self._block_index += 1
                self._block_source = ""
                self._last_emitted = ""
                continue

            closing = _first_tag(self._buffer, _CLOSE, "</a2ui")
            if closing is None:
                hold = _held_for_tag(self._buffer, _CLOSE, "</a2ui")
                self._block_source += self._buffer[: len(self._buffer) - hold]
                self._buffer = self._buffer[len(self._buffer) - hold :]
                event = self._compile(done=False)
                if event:
                    events.append(event)
                return events

            close_at, close_end = closing
            self._block_source += self._buffer[:close_at]
            self._buffer = self._buffer[close_end:]
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

        incomplete: str | None = None
        try:
            # Before the SDK, because the SDK will not object: an invented
            # component compiles to nothing at all rather than to an error.
            if self.components:
                invented = unknown_components(source, self.components)
                if invented:
                    hint = nearest_components(invented, self.components)
                    raise UnknownComponent(
                        f"No such component: {', '.join(invented)}. "
                        + (f"{hint} " if hint else "")
                        + f"The catalog has {len(self.components)} components; "
                        "use one of them or compose from Row, Column and Text."
                    )
            try:
                compiled = self.parser.compile(source, is_final=done)
            except Exception as refused:
                # The compiler checks required properties itself since
                # agent-sdk 0.9, which it did not before — so this failure now
                # happens *here* rather than in the validator below, and the
                # explanation this class adds had quietly stopped being
                # reached. What it adds is the order: the compiler says which
                # property is missing, and the model's next attempt needs to
                # know where it goes, because Express is positional.
                raise _with_the_order(refused, self.required) from refused

            # A macro is a component the catalog advertises and no renderer
            # ever sees. Expanded here, before the checks below and before
            # anything else reads this tree, so every pass sees the real
            # components and none of them has to know macros exist.
            messages = as_wire(expand_macros(compiled, self.trip))
            # Only on a finished block. A tree still being written legitimately
            # refers to components a few tokens away from existing, and calling
            # that an error would reject every surface mid-stream.
            if done and self.validator is not None:
                try:
                    self.validator.validate(messages)
                except Exception as invalid:
                    # The validator is right that this is broken and unhelpful
                    # about why. If the reason is a property the catalog
                    # requires, say so in those terms; otherwise its message is
                    # still the best available.
                    absent = missing_properties(messages, self.required)
                    if absent:
                        raise MissingProperty(" ".join(absent)) from invalid
                    raise
            if done:
                # And the question has to be askable. A date in a text box is a
                # date the traveller can get wrong — see `controls.py`.
                from .controls import half_asked, wrong_controls

                wrong = wrong_controls(messages)
                if wrong:
                    raise WrongControl(" ".join(wrong))

                # And a question asked per hop has to be asked of every hop.
                # Not raised. See `Ui.incomplete`.
                incomplete = half_asked(messages, self.hops)
        except Exception as error:  # noqa: BLE001 - any parse failure, same handling
            # Mid-stream failures are the normal case: half a constructor is not
            # valid Express. Only a failure on a finished block is news.
            if not done:
                return None
            return Failed(block_index=self._block_index, message=str(error), source=source)

        return Ui(
            block_index=self._block_index,
            messages=messages,
            done=done,
            incomplete=incomplete if done else None,
        )


# --------------------------------------------------------------------------
# Prose that is trying to be a surface
# --------------------------------------------------------------------------


#: What a surface written in a notation that does not exist looks like.
#:
#: The model is given one way to draw — an `<a2ui>` block of Express — and a
#: catalog that says what may go in it. Sometimes it ignores both and emits a
#: fenced JSON document instead, in a shape nobody defined:
#:
#:     ```json
#:     [{"call": "host:render", "surface": "inline-1",
#:       "components": [{"id": "…", "type": "Form", "props": {…}}]}]
#:
#: `Form`, `DateRangeField` and `NumberField` are not components this catalog
#: has, `type`/`props` is not how A2UI names them, and `host:render` is not a
#: call anything answers. None of that matters as much as what happened next:
#: the splitter looks for `<a2ui>` and found none, so the whole thing went to
#: the traveller as prose. Two hundred lines of JSON where an interface should
#: have been.
#:
#: A compile error is already handled — the model is told and writes the block
#: again. This is the same failure one step earlier, and it was the one case
#: that reached the screen instead.
_SURFACE_SHAPED = re.compile(
    r'"(?:components|call|surfaceId|surface)"\s*:|"(?:root|catalog|catalogId)"\s*:'
    # …or the same mistake wearing JSX. This reached a traveller as text on
    # screen:
    #
    #     <DateRangePicker
    #       label="Travel Dates"
    #       startDate="$/trip/startDate"
    #       endDate="$/trip/endDate" />
    #
    # Note `startDate`/`endDate`, which are not even this component's property
    # names — they are `start` and `end`. The model was not writing a surface
    # in a notation we could read; it was writing React from memory. The JSON
    # alternation above could not see it, so `looks_like_a_surface` was false,
    # the "write it as Express" retry never fired, and the markup went to the
    # transcript as prose.
    r"|<\s*[A-Z][A-Za-z0-9]*(?:\s|/?>)",
)

#: The opening of a component tag, for the gate below.
#:
#: Deliberately just `<` and a capital: by the time those two characters are on
#: the wire the turn has already gone wrong, and waiting to see which component
#: it is only decides how much markup reaches the screen first.
_MARKUP_OPENS = re.compile(r"<\s*[A-Z]")


class _PerComponentValidator:
    """A whole-payload check composed out of a per-component one.

    Every caller here asks one question — "is this list of messages a surface a
    renderer will accept?" — and the SDK has answered it in three different
    shapes across three releases:

      agent-sdk ≤0.6   `catalog.validator.validate(messages)`
      agent-sdk 0.7    `catalog.validate(messages)`
      agent-sdk 0.9    neither: `PayloadValidator.validate_component(one)`

    The third is not a rename, it is a narrowing — the whole-payload entry
    point is gone, and what is left checks one component at a time. So this
    walks the messages and puts every component through it, which is the same
    question asked the way the SDK now answers it.

    Worth keeping as an adapter rather than inlining at the call sites: the
    move from 0.6 to 0.7 reached users as "'PayloadValidator' object has no
    attribute 'validate'" and an app that drew nothing at all, because the call
    sites each had their own spelling of it.
    """

    def __init__(self, validator: Any, catalog: Any) -> None:
        self._validator = validator
        self._catalog = catalog

    def validate(self, messages: Iterable[A2uiMessage]) -> None:
        for message in messages:
            nodes = [node for node in components_of(message) if isinstance(node, dict)]
            if not nodes:
                continue
            for node in nodes:
                self._validator.validate_component(node)
            self._whole(nodes)

    def _whole(self, nodes: list[dict[str, Any]]) -> None:
        """The checks that are about the surface rather than one component.

        A child that was never defined is the one that matters, because it is
        the one that does not look like an error: `Column([title, missing])`
        validates component by component and renders as a box with a hole in
        it. The old whole-payload validator caught it; the per-component API
        cannot see it, by construction.

        Skipped rather than failed when a surface updates components without
        carrying its root — an `updateComponents` that replaces one card in a
        list is not a surface missing its root, and refusing it would be worse
        than the hole.
        """
        from a2ui.core.state.component_model import ComponentModel
        from a2ui.core.validation import ValidationConfig, validate_component_integrity

        built: dict[str, Any] = {}
        for node in nodes:
            component_id = node.get("id")
            component_type = node.get("component")
            if not isinstance(component_id, str) or not isinstance(component_type, str):
                continue
            properties = {k: v for k, v in node.items() if k not in ("id", "component")}
            built[component_id] = ComponentModel(
                component_id=component_id,
                component_type=component_type,
                catalog=self._catalog,
                properties=properties,
            )
        if not built:
            return
        validate_component_integrity(
            built, config=ValidationConfig(allow_missing_root="root" not in built)
        )


def whole_payload_validator(catalog: Any) -> Any:
    """Whatever, in this SDK version, checks a whole list of messages.

    Resolved by the method rather than the attribute, in one place, so that
    every caller — the doors, the surface builders and the tests — asks the
    same question and a future move breaks all of them at once rather than
    production alone. See `_PerComponentValidator` for the three shapes this
    has had.
    """
    if callable(getattr(catalog, "validate", None)):
        return catalog
    validator = getattr(catalog, "validator", None)
    if callable(getattr(validator, "validate", None)):
        return validator

    try:  # agent-sdk 0.9: per component, and nothing above it
        from a2ui.core.validation import PayloadValidator
    except ImportError:  # pragma: no cover - older SDKs never get here
        PayloadValidator = None  # type: ignore[assignment]
    if PayloadValidator is not None:
        return _PerComponentValidator(PayloadValidator(catalog), catalog)

    raise RuntimeError(
        "This a2ui-agent-sdk exposes no way to validate a surface; surfaces "
        "would reach the traveller unchecked. See tests/test_upstream_contract.py."
    )


@dataclass(frozen=True)
class Fenced:
    """A fenced code block, held back rather than spoken.

    This agent answers in interfaces and in one or two sentences of prose.
    Neither is a code fence, so a fence is always one of two mistakes: a surface
    in the wrong notation, or the model showing its working. The traveller wants
    neither, and `looks_like_a_surface` decides whether the model is worth
    telling.
    """

    source: str
    type: Literal["fenced"] = "fenced"

    @property
    def looks_like_a_surface(self) -> bool:
        return bool(_SURFACE_SHAPED.search(self.source))


class FenceGate:
    """Keeps fenced blocks out of the transcript.

    Streaming makes this less trivial than it sounds: the three backticks that
    open a fence can arrive split across two deltas, so a gate that tested each
    delta on its own would pass the first two characters through and hold the
    third. Hence the carry — up to two characters are kept back whenever the
    tail of what arrived could still be the start of a fence.
    """

    def __init__(self) -> None:
        self._inside = False
        self._carry = ""
        self._block: list[str] = []
        #: Latched the moment prose turns into markup, never unlatched.
        #:
        #: A fence has a closing delimiter; a component tag written into prose
        #: has nothing reliable to close on — the leak that prompted this ran
        #: across several lines and trailed off in the middle of a function
        #: call. Rather than parse JSX to find its end, the gate takes the
        #: view that a round which has started writing components has stopped
        #: writing prose: everything after the tag is held back too.
        #:
        #: The cost of being wrong is the tail of one sentence. The cost of the
        #: alternative is markup on screen, which is what happened.
        self._markup = False
        self._markup_src: list[str] = []
        #: A lone trailing `<`, held in case the next delta brings the capital.
        self._edge = ""

    def feed(self, delta: str) -> tuple[str, list[Fenced]]:
        """Returns the prose to emit, and any fences that closed."""
        if self._markup:
            # Nothing more from this round is prose.
            self._markup_src.append(delta)
            return "", []

        buffer = self._carry + delta
        self._carry = ""
        out: list[str] = []
        closed: list[Fenced] = []

        while buffer:
            marker = buffer.find("```")
            if marker == -1:
                # Nothing certain. Hold back a tail that could still become one.
                keep = 0
                for size in (2, 1):
                    if buffer.endswith("`" * size):
                        keep = size
                        break
                body, self._carry = (buffer[: len(buffer) - keep], buffer[len(buffer) - keep :])
                (self._block if self._inside else out).append(body)
                break

            before, buffer = buffer[:marker], buffer[marker + 3 :]
            (self._block if self._inside else out).append(before)
            if self._inside:
                closed.append(Fenced(source="".join(self._block)))
                self._block = []
            self._inside = not self._inside

        return self._without_markup("".join(out)), closed

    def _without_markup(self, said: str) -> str:
        """Prose up to the point it became a component tag.

        The `<` is held back on its own when it lands at the end of a delta,
        because `<` and `Date` arriving separately is the ordinary case on a
        streamed response and a gate that tested each delta alone would put the
        bracket on screen and catch only the rest.
        """
        said = self._edge + said
        self._edge = ""
        if not said:
            return ""

        found = _MARKUP_OPENS.search(said)
        if found:
            self._markup = True
            self._markup_src.append(said[found.start() :])
            return said[: found.start()]

        # `<` last, or `<` then whitespace: either could still become a tag.
        stripped = said.rstrip()
        if stripped.endswith("<"):
            keep = len(said) - said.rindex("<")
            self._edge = said[-keep:]
            return said[:-keep]
        return said

    def flush(self) -> tuple[str, list[Fenced]]:
        """End of the round. An unclosed fence still counts as one."""
        if self._markup:
            block = Fenced(source="".join(self._markup_src))
            self._markup_src = []
            self._markup = False
            self._carry = ""
            self._edge = ""
            return "", [block]

        tail, self._carry = self._carry, ""
        # A `<` that never became a tag is just a character the traveller typed
        # their way into, and it belongs in the sentence it came from.
        tail, self._edge = self._edge + tail, ""
        if self._inside:
            self._block.append(tail)
            block = Fenced(source="".join(self._block))
            self._block = []
            self._inside = False
            return "", [block]
        return tail, []
