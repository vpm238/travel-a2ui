"""One turn of the conversation.

The shape of a turn, in order:

  1. Take what the traveller set on screen and put it in the trip — *before*
     asking the model anything, because a value they typed is a fact and should
     not depend on the model noticing and calling `save_trip`.
  2. Turn what they pressed into a sentence the model can read.
  3. Ask the model, streaming. Split prose from A2UI as it arrives, so the
     surface paints while the model is still typing.
  4. When it calls a tool: draw the shape of the answer first, run the tool,
     then fill the shape. The screen is busy for the whole wait rather than
     empty for it.
  5. Bring the standing panels up to date, and rebuild them if the decisions
     changed shape enough to need different controls.

Everything the browser used to decide for itself is in here now. It used to
hold a list of trip field names, watch them, and send a prose prompt asking for
a new panel — a private protocol composed in a client, which meant a Flutter or
second renderer that did not send it simply never got a panel.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import pathlib
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Sequence

warnings.filterwarnings("ignore")

from a2ui.inference_formats.experimental.express.parser import ExpressParser  # noqa: E402
from a2ui.schema.catalog import A2uiCatalog, CatalogConfig  # noqa: E402

from . import trip as model  # noqa: E402
from .express import ExpressStream, Failed, Text, Ui  # noqa: E402
from .gemini import describe_api_error, stream_interaction, supported_level  # noqa: E402
from .providers.fixture import FixtureProvider  # noqa: E402
from .providers.types import TravelProvider  # noqa: E402
from .skeleton import pending_surface_for  # noqa: E402
from .skills import build_prompt_parts, build_system_prompt  # noqa: E402
from .surface import STANDING_SURFACES, finish, panel_events, trip_updates  # noqa: E402
from .tools import ToolContext, gemini_tools, grounding_tools, run_tool  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[4]
CATALOG_PATH = _ROOT / "catalogs" / "a2ui-travel" / "catalog.json"
CATALOG_JSON: dict[str, Any] = json.loads(CATALOG_PATH.read_text("utf-8"))

#: What the wire calls this catalog.
#:
#: `$id` rather than `catalogId` because that is what the SDK puts on
#: `createSurface`, and the model has to be told the same string the wire
#: carries. They happen to be identical in this catalog; reading the one the
#: compiler uses means they stay that way if that ever stops being true.
CATALOG_ID = CATALOG_JSON["$id"]

PROTOCOL_VERSION = "v0.9.1"

#: Tool loops need a ceiling: a model that keeps calling tools should stop, not bill.
MAX_TOOL_ROUNDS = 6

#: Values a commit is not allowed to corrupt the trip with.
REFUSABLE = ("startDate", "endDate", "travelers", "legs")

#: What a panel redraw asks for.
#:
#: Short, because the surface brief in the skill already says what a panel is
#: and what it may contain. This only has to say *now*.
PANEL_REQUEST = "Redraw this surface for where the trip stands now. Only the surface — no prose."


def _catalog() -> A2uiCatalog:
    config = CatalogConfig.from_path("travel", str(CATALOG_PATH))
    return A2uiCatalog.from_config(config, version="0.9.1")


_CATALOG = _catalog()
COMPONENT_NAMES = frozenset(_CATALOG.catalog_schema["components"])


def _parser(surface_id: str) -> ExpressParser:
    return ExpressParser(catalog=_CATALOG, surface_id=surface_id, version=PROTOCOL_VERSION)


#: The model that answers when nobody picks one, and the panel's own model.
#:
#: This was Flash Lite, picked on latency: fastest to a first surface, and for a
#: turn that is mostly recall — the catalog is in the prompt, the job is to bind
#: three components — that looked like the right trade.
#:
#: It was the wrong trade, and the thing that showed it was the way home. A
#: round trip needs a ticket each way; the skills say so, the route facts say
#: the journey does not come back, and the `search_flights` result says it again
#: at the moment the fares arrive. Flash Lite read all three, answered "here are
#: the *outbound* flights" — so it had understood — and moved on to hotels, with
#: the traveller still in Madrid. Four attempts, at `minimal` and at `low`, all
#: four the same. On Flash 3.8, the same prompt and the same tools, first try:
#: it recorded the hop home as a leg, priced both hops, and had an opinion about
#: each.
#:
#: So the ceiling was never the instructions. A demo that is fast at being wrong
#: is not fast, and the seconds are worth an agent that finishes the journey.
#: Flash Lite is still one keystroke away in the header for anyone who wants to
#: watch the difference.
#:
#: The honest caveat, measured on the same eval, is availability. Of twelve
#: turns on Flash 3.8, four came back with no surface at all — every one of them
#: "currently experiencing high demand", a capacity spike rather than anything
#: the model got wrong. Of the eight that ran, eight drew the right thing; Flash
#: Lite, never once busy, drew it ten times in twelve. That is what
#: `FALLBACK_MODEL` is for: the turn degrades to the model that is up rather
#: than ending the conversation, and the traveller is told it happened.
#:
#: Lives here rather than in `main.py` because the voice relay redraws the
#: standing panel with its own model call, and a second opinion about the
#: default is how two doors quietly end up on two models.
DEFAULT_MODEL = "gemini-3.8-flash"

#: How hard that model thinks when nobody says. See `supported_level`, which
#: clamps this to what the chosen model accepts — Flash 3.8 rejects `minimal`
#: outright, where Flash Lite takes it.
DEFAULT_EFFORT = "low"

#: Who answers when the chosen model is busy. See `_open` in `gemini.py`.
#:
#: Measured on the eval that settled the default: twelve of thirty-six turns on
#: Flash 3.8 came back with no surface at all, every one of them "currently
#: experiencing high demand" — the model was not there, rather than wrong. A
#: capacity spike on Google's side is not something a traveller halfway through
#: planning a trip can do anything about, and "the model is busy" is a worse
#: answer than a smaller model's surface. So the turn degrades instead of dying,
#: and the client is told which model actually answered.
FALLBACK_MODEL = "gemini-3.5-flash-lite"


def _today(client: Any = None) -> str:
    """Today where the traveller is, not where the container is.

    The server runs in UTC, and a trip is planned in a calendar the traveller is
    holding. At 18:00 in Los Angeles the container has already turned the page:
    "tomorrow" comes back a day late, and "this Saturday" is the wrong Saturday.
    The browser is the only party that knows which day it is for them, so it
    says, and this reads it.

    Read sceptically, because it is untrusted input: a well-formed date within a
    day of the server's own is the only thing that can move this, which covers
    every real timezone and nothing else. A client that sends junk — or a clock
    set to 2019 — gets the server's date, which is what there was before.
    """
    here = _dt.date.today()
    said = client.get("today") if isinstance(client, dict) else None
    if isinstance(said, str):
        try:
            theirs = _dt.date.fromisoformat(said)
        except ValueError:
            return here.isoformat()
        if abs((theirs - here).days) <= 1:
            return theirs.isoformat()
    return here.isoformat()


@dataclass
class SurfaceAction:
    """An interaction on a surface, in A2UI's own shape.

    This is what a renderer produces when someone presses something — any
    renderer, on any platform, with nothing taught to it. It replaced a sentence
    the browser used to compose, which was a private protocol wearing the
    costume of a user message.

    `context` is the answer: the action's bound paths, resolved. `data_model` is
    the rest of the surface, opaque and optional — it keeps trip state exact
    without asking any client to know what a trip is, and a client that omits it
    still works.
    """

    name: str
    surface_id: str
    context: dict[str, Any] = field(default_factory=dict)
    data_model: dict[str, Any] | None = None
    source_component_id: str | None = None


@dataclass
class TurnRequest:
    api_key: str
    model: str
    #: What the traveller typed. Empty when `action` carries the turn instead.
    message: str = ""
    action: SurfaceAction | None = None
    #: The last interaction, or None to start a new conversation. The transcript
    #: lives on the server; this is the thread back to it.
    interaction_id: str | None = None
    trip: dict[str, Any] = field(default_factory=dict)
    surface: str = "inline"
    surface_id: str = "inline-1"
    skill: str = "express-modular"
    effort: str = DEFAULT_EFFORT
    #: What the browser knows about when the traveller is. See `_today`.
    client_hints: dict[str, Any] | None = None
    #: Which setup the conversation was started against, if it was started.
    #:
    #: A fingerprint of the stable half of the prompt. When it no longer matches
    #: — the traveller changed the skill variant, or the deployment shipped a new
    #: catalog — the conversation is not continued against rules nobody is
    #: reading any more: the chain is dropped and the new setup is sent.
    setup: str | None = None
    #: The decision shape the standing surfaces were last drawn for.
    shape: str | None = None
    provider: TravelProvider | None = None
    #: Injectable so a test can drive the loop from a scripted stream.
    client: Any | None = None


@dataclass
class TurnResult:
    interaction_id: str | None
    trip: dict[str, Any]
    stop_reason: str | None
    shape: str | None = None
    #: The setup this conversation is bound to. See `TurnRequest.setup`.
    setup: str | None = None


def _commit(saved: dict[str, Any], proposed: dict[str, Any], today: str) -> tuple[dict, list[str]]:
    """Applies what a surface sent, minus anything that would break the trip.

    `save_trip` has always validated, so a model that invented a return date
    before the departure was told so. A *commit* went nowhere near it: the
    traveller's own values were merged straight in, and a picker handing back
    20 April → 12 April priced four flights against a trip with negative nights.

    A refused field reverts to what was saved — deleting outright would lose a
    value they had already agreed to, which is a second wrong answer — and the
    model is told which and why, so the next surface re-asks instead of the
    traveller wondering why their dates did not stick.
    """
    def refusable(candidate: dict[str, Any]) -> list[dict[str, str]]:
        return [
            problem
            for problem in model.problems(candidate, today)
            if problem["field"] in REFUSABLE
        ]

    found = refusable(proposed)
    if not found:
        return proposed, []

    def revert(candidate: dict[str, Any], fields: Sequence[str]) -> dict[str, Any]:
        out = dict(candidate)
        for name in fields:
            if name in saved:
                out[name] = saved[name]
            else:
                out.pop(name, None)
        return out

    trip = revert(proposed, [problem["field"] for problem in found])

    # Reverting the field that *reported* the problem is not always enough, and
    # the date pair is the case that proves it. `problems` names `endDate` for a
    # range that runs backwards, so a commit of 20 Apr → 12 Apr over a saved
    # 1 Apr → 8 Apr reverts only the end and leaves 20 Apr → 8 Apr: still
    # backwards, still negative nights, and now a pair the traveller never
    # typed. A range is one decision, so when one end is refused and putting it
    # back does not settle it, the whole decision goes back.
    if refusable(trip):
        changed = [
            name
            for name in REFUSABLE
            if proposed.get(name) != saved.get(name)
        ]
        trip = revert(proposed, changed)

    return trip, [problem["message"] for problem in found]


def describe_action(action: SurfaceAction) -> str:
    """What the model is told when someone presses something.

    The wire carries an action, not a sentence. The model still needs a
    sentence, and this is the one place that decides what it says — which is
    where it belongs: how this agent interprets a tap on a read-only panel is a
    fact about this agent, not about the tap, and a client should not be in the
    business of explaining it.
    """
    said = json.dumps(action.context or {}, ensure_ascii=False)
    where = action.surface_id

    # A panel is a record, not a form. An interaction there is a request to
    # re-open a decision in the conversation, where there is one place to edit
    # a value and a history of when it changed.
    if where in STANDING_SURFACES:
        field_name = (action.context or {}).get("field")
        if field_name:
            return (
                f'[interface] The traveler pressed "{action.name}" on the {where} for '
                f"`{field_name}`. Release that decision and ask for it again inline, "
                "pre-filled with what was there, along with anything that depended on it."
            )
        return (
            f'[interface] The traveler pressed "{action.name}" on the {where} (context {said}). '
            "The panel is read-only — ask them that in the conversation instead, with the "
            "controls it needs."
        )

    return f"[interface] {action.name} on {where} — context {said}"


async def run_turn(request: TurnRequest) -> AsyncIterator[dict[str, Any]]:
    """Runs one turn, yielding events as they happen.

    An async generator rather than a callback, because the transport is SSE and
    a generator is what FastAPI's streaming response wants — and because it
    makes the whole loop testable by iterating it.
    """
    today = _today(request.client_hints)
    provider = request.provider or FixtureProvider()

    # Values the traveller set on screen are facts, and the host records them
    # rather than depending on the model to notice and call `save_trip`. That
    # dependency is what made a second card forget what the first one asked.
    #
    # The action's own context first, then the rest of the surface: the context
    # is what the button declared it was sending, so it wins where they
    # disagree, and the surrounding data model fills in anything the traveller
    # set that no binding named.
    from_surface = model.normalize((request.action.data_model or {}).get("trip") if request.action else None)
    from_context = model.normalize(request.action.context if request.action else None)
    trip, refused = _commit(
        request.trip, {**request.trip, **from_surface, **from_context}, today
    )

    # Pressing a button *is* saying so. Whatever the surface sent stops being a
    # guess, however it got into the control — the agent's suggestion, a value
    # carried over from an earlier turn, or something typed just now.
    said = [*from_surface.keys(), *from_context.keys()]
    if said:
        # Replaced, not merged. `confirm` returns a trip with the `assumed` key
        # *removed* once nothing is assumed any more, and merging a dict that
        # lacks a key cannot take that key off the target — so the mark
        # survived every press, the host kept the question open, and the agent
        # went on re-asking something the traveller had already pressed.
        confirmed = model.confirm(trip, said)
        trip.clear()
        trip.update(confirmed)

    def save(patch: dict[str, Any]) -> None:
        # `merge` rather than `update`, because one field does not simply
        # overwrite: a patch naming `assumed` is talking about its own fields,
        # and a later patch stating one of them for real has to clear that mark.
        nxt = model.merge(trip, patch)
        trip.clear()
        trip.update(nxt)

    tool_context = ToolContext(trip=trip, provider=provider, save=save, today=today)

    # Pressing something *is* the traveller's turn, so it enters the
    # conversation as one. Typing wins when both arrive: someone can type while
    # a surface is on screen, and then what they said is the turn — the
    # action's values still reached the trip above, which had to happen either
    # way.
    lines = [
        request.message
        or (describe_action(request.action) if request.action else PANEL_REQUEST)
    ]
    if refused:
        # Said in the turn rather than left for the model to discover, because
        # it will not: the trip it reads back is simply the old one, and nothing
        # in it says a value was turned away.
        lines.append(
            f"[interface] Refused, and not saved: {' '.join(refused)} "
            "Say so plainly and ask for it again, keeping everything else they set."
        )
    opening = "\n\n".join(line for line in lines if line)

    previous_interaction_id = request.interaction_id

    yield {
        "type": "start",
        "model": request.model,
        "skill": request.skill,
        "surfaceId": request.surface_id,
    }

    # What the turn spent its time on.
    #
    # "The interface does not appear quickly enough" was not answerable before
    # this: there was no number anywhere for how long anything took, so the only
    # way to discuss it was to describe the feeling. The marks below are the
    # three that decide that feeling — when the first word arrives, when the
    # first *pixel* of interface arrives, and how long each lookup took — and
    # they go out on the wire so a slow turn can be read off rather than
    # reproduced.
    #
    # `perf_counter` rather than wall-clock: this measures a duration, and a
    # clock that can be stepped by NTP mid-turn produces negative ones.
    began = time.perf_counter()
    marks: dict[str, float] = {}

    def mark(name: str) -> None:
        """Records the first time something happened, in milliseconds."""
        if name not in marks:
            marks[name] = round((time.perf_counter() - began) * 1000, 1)

    # The prompt in two halves, and only one of them goes on the wire.
    #
    # The Interactions API is stateful: `previous_interaction_id` carries the
    # whole prior context on Google's side. Measured on a 5,411-token system
    # instruction, a follow-up that omitted it cost 44 input tokens instead of
    # 5,411 — and `total_cached_tokens` was 0 throughout, so nothing was quietly
    # caching this for us. Re-sending the catalog, the rules and the component
    # signatures on every round of every turn was paying full price, repeatedly,
    # for thirteen thousand tokens the model was already looking at.
    #
    # So the stable half is the setup, sent once when a conversation starts, and
    # the volatile half — today, the surface to draw into, the trip so far —
    # rides in with the message, which it has to anyway: a model told ten turns
    # ago to draw into `inline-1` would still be drawing into `inline-1`.
    stable, volatile = build_prompt_parts(
        variant=request.skill,
        surface=request.surface,
        surface_id=request.surface_id,
        catalog_id=CATALOG_ID,
        trip=trip,
        today=today,
    )

    # A conversation is bound to the setup it started with. Change the skill
    # variant mid-conversation and the stable half is different — so the chain
    # is broken deliberately and the new setup is sent, rather than continuing
    # against rules nobody is reading any more. Same idea as the contract stamp
    # a Live session binds to.
    setup = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    if request.setup and request.setup != setup:
        previous_interaction_id = None
    system: str | None = stable if not previous_interaction_id else None

    turn_input: list[dict[str, Any]] = [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": f"{volatile}\n\n---\n\n{opening}"}],
        }
    ]

    stop_reason: str | None = None
    # A compile failure the model has not been told about yet. Until this
    # existed, Express that did not compile ended the turn with a broken
    # surface and the model none the wiser: it had written something wrong and
    # nothing ever said so.
    unreported: dict[str, str] | None = None
    retried_compile = False

    for round_index in range(MAX_TOOL_ROUNDS):
        # A fresh splitter per round: each round is its own stream of prose and
        # Express, and a block left open at the end of one is not continued by
        # the next.
        stream = ExpressStream(
            parser=_parser(request.surface_id),
            components=COMPONENT_NAMES,
            validator=_CATALOG.validator,
        )

        def rendered(events: Sequence[Any], source: str) -> list[dict[str, Any]]:
            """Splitter events, as events for the browser."""
            nonlocal unreported
            out: list[dict[str, Any]] = []
            for event in events:
                if isinstance(event, Text):
                    mark("firstWord")
                    out.append({"type": "text", "delta": event.delta, "round": round_index})
                elif isinstance(event, Ui):
                    # The number that matters. Everything before this is a blank
                    # space where an interface should be.
                    mark("firstSurface")
                    out.append(
                        {
                            "type": "ui",
                            "surfaceId": request.surface_id,
                            "messages": finish(event.messages, trip),
                            "done": event.done,
                        }
                    )
                elif isinstance(event, Failed):
                    unreported = {"message": event.message, "express": event.source}
                    out.append(
                        {
                            "type": "ui_error",
                            "message": event.message,
                            "source": source,
                            "express": event.source,
                        }
                    )
            return out

        result = None
        failure: Exception | None = None
        try:
            # Yielded straight through rather than collected: this generator
            # feeds an SSE response, so a delta that reaches here reaches the
            # browser. Buffering the round and emitting at the end would paint
            # the surface only once the model had stopped typing, which is the
            # thing the streaming exists to avoid.
            async for event in stream_interaction(
                api_key=request.api_key,
                model=request.model,
                input=turn_input,
                tools=[*gemini_tools(), *grounding_tools()],
                system_instruction=system,
                thinking_level=request.effort,
                previous_interaction_id=previous_interaction_id,
                fallback_model=FALLBACK_MODEL,
                client=request.client,
            ):
                if event["type"] == "text":
                    for out in rendered(stream.push(event["delta"]), "stream"):
                        yield out
                elif event["type"] == "served_by":
                    # Said rather than hidden. The traveller asked for one model
                    # and a different one is answering; a demo that quietly
                    # swaps the thing it is demonstrating is a demo that lies.
                    yield event
                elif event["type"] == "result":
                    result = event["result"]
        except Exception as error:  # noqa: BLE001 - every failure gets a sentence
            failure = error

        # Flushed even on failure: a block that compiled before the stream died
        # is a surface the traveller can still use, and throwing it away to
        # show an error banner is a worse turn than showing both.
        for out in rendered(stream.end(), "final"):
            yield out

        if failure is not None:
            yield describe_api_error(failure)
            break
        if result is None:
            yield {
                "type": "error",
                "message": "The model stream ended without a result.",
                "retryable": True,
            }
            break

        previous_interaction_id = result.interaction_id or previous_interaction_id
        stop_reason = result.status

        yield {"type": "usage", **result.usage.as_dict()}

        # Nothing left to do but a surface that did not compile: hand the error
        # back and let it write the block again. Once — a model that cannot fix
        # it on the second attempt will not fix it on the fifth, and the
        # traveller is waiting.
        if not result.tool_calls and unreported and not retried_compile:
            retried_compile = True
            failure = unreported
            unreported = None
            yield {"type": "retry", "reason": failure["message"]}
            turn_input = [
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "That A2UI block did not compile, so nothing was drawn and "
                                "the traveler is looking at prose with a gap in it.\n\n"
                                f"{failure['message']}\n\nThe block was:\n\n"
                                f"{failure['express'][:4000]}\n\n"
                                "Write the whole block again, corrected. Do not repeat the "
                                "prose — only the <a2ui> block."
                            ),
                        }
                    ],
                }
            ]
            continue

        if not result.tool_calls:
            break

        # Every call this round answered in one go: the next request carries all
        # of their results, which is what keeps the model calling tools in
        # parallel rather than learning to ask one at a time.
        results: list[dict[str, Any]] = []
        for call in result.tool_calls:
            yield {"type": "tool", "name": call.name, "input": call.args, "status": "running"}

            # Draw the shape of the answer before going to look for it. Only on
            # the surface this turn is answering: a standing panel is not what
            # the traveller just asked a question about.
            pending = (
                pending_surface_for(
                    call.name, request.surface_id, _parser(request.surface_id), PROTOCOL_VERSION
                )
                if request.surface == "inline"
                else None
            )
            if pending:
                # The skeleton counts. It is a real interface on screen — the
                # whole point of drawing it — and leaving it out of the mark
                # measured the *model's* surface instead, which arrives a
                # tool-round later and made the app look far slower than it is.
                mark("firstSurface")
                yield {
                    "type": "ui",
                    "surfaceId": request.surface_id,
                    "messages": pending.opening,
                    "done": False,
                }

            tool_began = time.perf_counter()
            output, is_error = await run_tool(call.name, call.args, tool_context)
            marks[f"tool:{call.name}"] = round((time.perf_counter() - tool_began) * 1000, 1)
            yield {
                "type": "tool_result",
                "name": call.name,
                "result": output,
                "isError": is_error,
            }

            # The same components, now with something in them. No recompile and
            # no second component send: the data model is the only thing that
            # moved.
            drawn: dict[str, Any] | None = None
            if pending and not is_error:
                filled = pending.fill(output)
                if filled:
                    yield {
                        "type": "ui",
                        "surfaceId": request.surface_id,
                        "messages": filled,
                        "done": False,
                    }
                    # And the model is told, because it could not otherwise know.
                    #
                    # The host draws these results the moment the lookup starts
                    # and fills them when it lands — that is the whole point of
                    # the skeleton. The model knew nothing about it, so it
                    # composed its own tree over the top of the same surface,
                    # bound to its own paths. The renderer merges components by
                    # id, so the filled list stayed in the data model with
                    # nothing pointing at it: the card appeared with real
                    # flights, the model's block landed, and the flights
                    # vanished while the traveller was looking at them.
                    drawn = {
                        "surfaceId": request.surface_id,
                        "path": pending.path,
                        "rows": len(pending.rows(output)),
                    }

            payload: dict[str, Any] = dict(output) if isinstance(output, dict) else {"result": output}
            if drawn:
                payload["alreadyOnScreen"] = {
                    **drawn,
                    "note": (
                        "The host has already drawn these on surface "
                        f"{drawn['surfaceId']} and bound them to {drawn['path']}. "
                        "Do not draw this surface again — say one line about what "
                        "came back and let them press. Drawing over it replaces "
                        "the cards they are looking at with an empty one."
                    ),
                }

            results.append(
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                }
            )

        # A block that did not compile, in a round that also called tools.
        #
        # The repair branch above only runs when the model has stopped calling
        # tools, so a round that drew something broken *and* looked something up
        # — the common shape of a first turn — went back to the model with the
        # tool results and not a word about the surface. The traveller got a
        # turn with a gap in it and the model never found out.
        #
        # The compiler's own message goes back as another result, which is the
        # same channel the lookups came home on: the model is already reading
        # this list to decide what to do next.
        if unreported and not retried_compile:
            retried_compile = True
            yield {"type": "retry", "reason": unreported["message"]}
            results.append(
                {
                    "type": "function_result",
                    "name": "render_a2ui_express",
                    "call_id": f"compile-{round_index}",
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "ok": False,
                                    "error": unreported["message"],
                                    "block": unreported["express"][:4000],
                                    "next": (
                                        "Nothing was drawn. Write the whole A2UI block "
                                        "again, corrected, in your next reply. Do not "
                                        "repeat the prose."
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            )
            unreported = None

        turn_input = results
        yield {"type": "trip", "trip": dict(trip)}

        if round_index == MAX_TOOL_ROUNDS - 1:
            yield {
                "type": "error",
                "message": f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.",
                "retryable": True,
            }

    yield {"type": "trip", "trip": dict(trip)}

    # The panels outlive the turn that drew them, so the trip reaches them as
    # ordinary A2UI rather than as something the client works out for itself.
    # Shared with the voice relay, which does the same thing at the end of its
    # own turns — see `panel_events`.
    for event in panel_events(trip):
        yield event

    # The traveller's answer is finished here. What follows is the panels, and
    # they are not what was asked for.
    mark("answered")
    yield {"type": "done", "stopReason": stop_reason}

    shape = request.shape
    if request.surface == "inline":
        # A second model call, and it was inside the turn: `done` waited for the
        # panel to be rebuilt, so a turn whose inline card was on screen at 2.3s
        # went on saying "thinking" until 9.3s while a model redrew a sidebar
        # nobody was looking at. Measured across a flights turn, that second
        # call was most of the wall clock.
        #
        # It still happens, and still only when the panel needs *different*
        # controls — values reach it live, without a model — but it happens
        # after the turn is answered. The events are ordinary `ui` messages
        # addressed to `sidebar` and `home`, which a client applies whenever
        # they arrive.
        async for event in _rebuild_panels(request, trip, today):
            if event["type"] == "__shape__":
                shape = event["shape"]
            else:
                yield event

    mark("done")
    # Sent before `done` so a client can attach it to the turn it describes
    # rather than to whatever comes next.
    yield {"type": "timing", "ms": dict(marks)}
    print(f"turn timing {json.dumps(marks)}", flush=True)

    yield {
        "type": "__result__",
        "result": TurnResult(
            interaction_id=previous_interaction_id,
            trip=trip,
            stop_reason=stop_reason,
            shape=shape,
            setup=setup,
        ),
    }


async def _rebuild_panels(
    request: TurnRequest, trip: dict[str, Any], today: str
) -> AsyncIterator[dict[str, Any]]:
    """Redraws the standing surfaces, if the trip's decisions changed shape.

    One extra model turn, and only when the shape moved — which is the same
    budget the browser was spending, now spent by the thing that knows when it
    is warranted. What counts as a decision is a fact about a trip, not about a
    panel, which is why `decision_shape` lives in the trip model.

    A failure here is silent on purpose: the traveller's answer already arrived
    and painted. A panel that is one turn stale is a much smaller problem than
    an error banner over a conversation that went fine.
    """
    shape = model.decision_shape(trip)
    if shape == request.shape:
        yield {"type": "__shape__", "shape": shape}
        return
    # Nothing to draw a panel *of* yet. The first turn usually ends with a
    # question, and a panel saying "no trip" is a panel nobody wants.
    if not trip.get("destination"):
        yield {"type": "__shape__", "shape": shape}
        return

    async def one(surface_id: str) -> list[dict[str, Any]]:
        """One panel, drawn whole, or nothing if drawing it failed."""
        system = build_system_prompt(
            variant=request.skill,
            surface=surface_id,
            surface_id=surface_id,
            catalog_id=CATALOG_ID,
            trip=trip,
            today=today,
        )
        stream = ExpressStream(
            parser=_parser(surface_id), components=COMPONENT_NAMES, validator=_CATALOG.validator
        )

        def drawn(events: Sequence[Any]) -> list[dict[str, Any]]:
            return [
                {
                    "type": "ui",
                    "surfaceId": surface_id,
                    "messages": finish(event.messages, trip),
                    "done": event.done,
                }
                for event in events
                if isinstance(event, Ui)
            ]

        panel: list[dict[str, Any]] = []
        try:
            async for event in stream_interaction(
                api_key=request.api_key,
                # The fast model, deliberately, whatever is answering the
                # conversation. The panel is the one surface in this app that
                # is not a judgement call: it draws the record — these
                # decisions, this route, a Change button on each — from rows the
                # host has already composed. That is the work Flash Lite is good
                # at and quick at, and the thing it was measurably *not* good at
                # is deciding what comes next, which is not asked of it here.
                model=FALLBACK_MODEL,
                # Not chained to the conversation: a panel redraw is not
                # something the traveller said, and threading it through
                # `previous_interaction_id` would put "rebuild the panel" in the
                # transcript as a user turn.
                input=[
                    {"type": "user_input", "content": [{"type": "text", "text": PANEL_REQUEST}]}
                ],
                system_instruction=system,
                thinking_level=supported_level(FALLBACK_MODEL, "minimal"),
                fallback_model=request.model,
                client=request.client,
            ):
                if event["type"] == "text":
                    panel.extend(drawn(stream.push(event["delta"])))
            panel.extend(drawn(stream.end()))
        except Exception:  # noqa: BLE001 - a stale panel beats an error banner
            return []

        # Collected rather than streamed, unlike the main loop: a panel is one
        # surface replaced whole, and a half-drawn record on screen beside a
        # finished answer reads as a bug rather than as progress.
        return panel

    # Both panels at once. They are two independent model calls with nothing to
    # say to each other, and doing them in sequence meant the sidebar waited for
    # the home summary — measured at about four and a half seconds for the pair,
    # which is most of what is left of a turn once the answer has been sent.
    #
    # `request.client` is a single scripted fake in tests, and two coroutines
    # pulling from one script would interleave into nonsense — so tests, which
    # pass a client, keep the sequential path.
    if request.client is not None:
        drawn_panels = [await one(surface_id) for surface_id in STANDING_SURFACES]
    else:
        drawn_panels = list(
            await asyncio.gather(*(one(surface_id) for surface_id in STANDING_SURFACES))
        )

    for panel in drawn_panels:
        for event in panel:
            yield event

    yield {"type": "__shape__", "shape": shape}


async def run_turn_collected(request: TurnRequest) -> dict[str, Any]:
    """Every event of a turn, gathered. Used by MCP, which has no stream."""
    text: list[str] = []
    ui: list[dict[str, Any]] = []
    result: TurnResult | None = None
    errors: list[str] = []

    async for event in run_turn(request):
        kind = event["type"]
        if kind == "text":
            text.append(event["delta"])
        elif kind == "ui":
            ui.extend(event["messages"])
        elif kind == "error":
            errors.append(event["message"])
        elif kind == "__result__":
            result = event["result"]

    return {
        "text": "".join(text).strip(),
        "ui": ui,
        "trip": result.trip if result else dict(request.trip),
        "interactionId": result.interaction_id if result else request.interaction_id,
        "shape": result.shape if result else request.shape,
        "setup": result.setup if result else request.setup,
        "errors": errors,
    }
