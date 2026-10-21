"""One turn of the conversation: ask the model, draw what it answers.

The loop, in order:

  1. Ask the model, streaming. Split prose from A2UI as it arrives, so the
     surface paints while the model is still typing.
  2. When it calls a tool: draw the shape of the answer first, run the tool,
     then fill the shape. The screen is busy for the whole wait rather than
     empty for it.
  3. Hand back the receipt — the interaction to resume from, and the trip as it
     now stands — before the panels are redrawn, because a traveller who
     presses something cancels everything after this point.
  4. Bring the standing panels up to date.

What the traveller did before any of this is `press.py`; the panels are
`panels.py`. This is the part that talks to the model.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, AsyncIterator, Sequence

from ...brain import trip as model
from ...brain.catalog import (
    CATALOG_ID,
    COMPONENT_NAMES,
    PROTOCOL_VERSION,
    REQUIRED_PROPERTIES,
    VALIDATOR,
    parser_for,
)
from ...brain.express import ExpressStream, Failed, FenceGate, Text, Ui
from ...brain.promises import TYPED_NUDGE, promised
from ...brain.providers.fixture import FixtureProvider
from ...brain.skeleton import pending_surface_for
from ...brain.skills import build_prompt_parts
from ...brain.finishing import finish, on_its_own_surface, panel_events, stack_blocks
from ...brain.tools import ToolContext, gemini_tools, grounding_tools, run_tool
from ...gemini import describe_api_error, stream_interaction
from ..settings import FALLBACK_MODEL, MAX_TOOL_ROUNDS, PANEL_REQUEST, _today
from .panels import _rebuild_panels
from .press import (
    TurnRequest,
    TurnResult,
    _commit,
    _leg_pressed,
    _party_paths,
    describe_action,
)


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

    # Which hop was pressed, when the press says so.
    #
    # A fare for the second hop carries its leg, because the second hop keeps
    # its own ticket and the trip's flat `selectedFlight` is the first hop's.
    # Without this the return landed on the trip and overwrote the outbound —
    # see `onto_leg`. Read off the raw context rather than the normalised trip,
    # because `leg` is not a trip field and normalising drops it.
    leg_index = _leg_pressed(request.action.context if request.action else None)

    proposed = {**request.trip, **from_surface, **from_context}
    if leg_index is not None:
        proposed = model.onto_leg(
            {**request.trip, **from_surface}, dict(from_context), leg_index
        )
    trip, refused = _commit(request.trip, proposed, today)

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
    # The prompt is still split in two, and the split still earns its keep: the
    # volatile half — the surface to draw into, the trip so far — has to ride in
    # with the message anyway, because a model told ten turns ago to draw into
    # `inline-1` would still be drawing into `inline-1`.
    #
    # What changed is that the stable half is now sent every turn, resumed or
    # not. It used to be sent only when a conversation started, on the reasoning
    # that `previous_interaction_id` carries the prior context on Google's side
    # — measured at the time as 44 input tokens for a follow-up instead of
    # 5,411, with `total_cached_tokens` at 0 throughout.
    #
    # That measured the bill and not the behaviour, and the behaviour was that
    # the model stopped drawing. Measured on the opening turn, four warmed turns
    # in four drew no surface at all — four and five rounds of tool calls and
    # nothing on screen — against four cold turns in four that drew. Re-send the
    # stable half and the same warmed turn draws three times in three. Whatever
    # the chain carries, it is not the rules: a resumed turn had no catalog, no
    # component signatures and no instruction to answer in a surface, so it did
    # the only thing left and called tools.
    #
    # The saving it was after has since arrived for free. The same turns now
    # report 32,184 cached of 40,135 input — implicit caching covers the stable
    # half, so correctness costs nothing here. Warming is still worth doing; it
    # starts the conversation, not the rulebook.
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
    system: str | None = stable

    # This turn's own history, and why the turn carries it rather than the API.
    #
    # The Interactions API is stateful: answer a round by posting the function
    # results with `previous_interaction_id` set to the interaction that asked
    # for them, and the server supplies everything before it. That is what this
    # loop used to do, and measured over fourteen continuation rounds it did
    # not hold. An interaction's id has two halves — the conversation it
    # belongs to and its own — and in six of those fourteen the reply came back
    # rooted at *itself*: a brand-new conversation, the previous one silently
    # dropped. Two things follow from that, and both were reported as bugs in
    # this app. The model answers the next round having forgotten the trip, so
    # it draws the opening form again at a traveller who settled their dates
    # three rounds ago — "it asks me things I already told it". And a later
    # round, answering a call the server no longer believes it made, dies on
    # "please ensure that function response turn comes immediately after a
    # function call turn", which is the 400 that ended one stays turn in three.
    #
    # It is not a race: a 350ms settle before each continuation round made it
    # worse, not better (eight breaks in thirteen). It is not the system
    # instruction either — sending that only on the first round took the drawn
    # surfaces from five in eight to three.
    #
    # So the turn stops depending on it. Every round sends the whole turn so
    # far — the traveller's message, each call the model made, each result that
    # came back — and `previous_interaction_id` is left pointing at the *last
    # turn*, the one place server-side state is still worth having and the one
    # place a break costs only prior context rather than the turn in hand.
    # A replayed call has to carry its signature, which is why `ToolCall` keeps
    # one.
    history: list[dict[str, Any]] = [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": f"{volatile}\n\n---\n\n{opening}"}],
        }
    ]
    turn_input: list[dict[str, Any]] = list(history)
    #: The interaction to resume this conversation from, next turn.
    last_interaction_id: str | None = previous_interaction_id

    stop_reason: str | None = None
    # A compile failure the model has not been told about yet. Until this
    # existed, Express that did not compile ended the turn with a broken
    # surface and the model none the wiser: it had written something wrong and
    # nothing ever said so.
    unreported: dict[str, str] | None = None
    retried_compile = False
    #: A fenced block the model wrote instead of an `<a2ui>` one.
    #:
    #: Same failure as a compile error, one step earlier: the model meant to
    #: draw and reached for a notation that does not exist. The difference is
    #: that a compile error was caught and this reached the screen — two hundred
    #: lines of JSON where an interface should have been.
    misdrawn: str | None = None
    retried_notation = False
    #: Everything this turn has said, and whether it has done anything.
    #:
    #: A turn that announces an intention and then ends is the failure both
    #: doors share and neither brief stops. Measured on the typed one: a
    #: multi-city opening answered "Let me record your multi-city route and get
    #: your travel dates" with nothing drawn in four runs of five.
    spoken = ""
    did_something = False
    #: A surface actually reached the screen this turn.
    #:
    #: Distinct from `did_something`, which is also true when a tool ran.
    #: Told apart because a message that says "what it drew is below" has to
    #: be about something that is, in fact, below: a turn that called
    #: `save_trip` and then lost the stream set `did_something` and drew
    #: nothing, and said so to a traveller looking at an empty space.
    drew_surface = False
    #: A tool has actually run this turn, so the model owes the API a response.
    #:
    #: Separate from `result.tool_calls`, which is only what the model *asked*
    #: for and is discarded harmlessly when a stream drops. This is the effect:
    #: once `run_tool` has been called, the conversation on Google's side holds
    #: a function call waiting on its response, and restarting the round sends
    #: a fresh turn instead — which the API refuses with "please ensure that
    #: function response turn comes immediately after a function call turn".
    #: Seen exactly that way: search_hotels, save_trip, restart, 400.
    dispatched_a_tool = False
    retried_promise = False
    #: A surface that drew but left the traveller nothing to answer.
    thin: str | None = None
    retried_thin = False

    for round_index in range(MAX_TOOL_ROUNDS):
        # A fresh splitter per round: each round is its own stream of prose and
        # Express, and a block left open at the end of one is not continued by
        # the next.
        # What the trip is waiting on, so a surface that asks for none of it is
        # caught before the traveller is left looking at one.
        #
        # `priceFlights` is the goal because it is the first thing every trip is
        # blocked on and its requirements are the boundaries — route, dates,
        # party. Once those are set this is empty and the check does not run,
        # which is right: a flight list answers a question rather than posing
        # one.
        stream = ExpressStream(
            parser=parser_for(request.surface_id),
            components=COMPONENT_NAMES,
            validator=VALIDATOR,
            required=REQUIRED_PROPERTIES,
            # And a party asked per hop has to be asked of every hop: a route
            # of three asked about twice is a hop flying home with a party
            # nobody confirmed. See `half_asked`.
            hops=_party_paths(trip),
        )

        # Fenced blocks never reach the transcript. This agent answers in
        # interfaces and in a sentence or two of prose; a code fence is neither,
        # so it is always a mistake, and the only question is whether it is one
        # worth telling the model about.
        gate = FenceGate()
        #: This turn's blocks on the answering surface, and the paths they ask
        #: about. Both span the turn rather than the block, because a turn that
        #: writes two blocks still owes the traveller one surface and one
        #: button that sends all of it. See `stack_blocks`.
        blocks: dict[str, Any] = {}
        carried: dict[str, dict[str, None]] = {}

        def rendered(events: Sequence[Any], source: str) -> list[dict[str, Any]]:
            """Splitter events, as events for the browser."""
            nonlocal unreported, misdrawn, spoken, did_something, thin, drew_surface
            out: list[dict[str, Any]] = []
            for event in events:
                if isinstance(event, Text):
                    said, fenced = gate.feed(event.delta)
                    for block in fenced:
                        if block.looks_like_a_surface and misdrawn is None:
                            misdrawn = block.source
                    if not said:
                        continue
                    spoken += said
                    mark("firstWord")
                    out.append({"type": "text", "delta": said, "round": round_index})
                elif isinstance(event, Ui):
                    did_something = True
                    drew_surface = True
                    # Drawn either way. A surface that asks for none of what the
                    # trip is waiting on is unhelpful, not invalid, and putting
                    # nothing on screen instead is worse for the traveller than
                    # putting the wrong thing there.
                    if event.incomplete and thin is None:
                        thin = event.incomplete
                    # The number that matters. Everything before this is a blank
                    # space where an interface should be.
                    mark("firstSurface")
                    out.append(
                        {
                            "type": "ui",
                            "surfaceId": request.surface_id,
                            # A block that names another surface is readdressed
                            # to this turn's card before anything else looks at
                            # it — a turn draws its own card and never over a
                            # spent one. See `on_its_own_surface`.
                            #
                            # Then two blocks in one turn compose onto that one
                            # surface instead of the second replacing the first,
                            # and `carried` makes the one button carry what both
                            # asked. See `stack_blocks`.
                            "messages": finish(
                                stack_blocks(
                                    on_its_own_surface(
                                        event.messages, request.surface_id
                                    ),
                                    request.surface_id,
                                    event.block_index,
                                    blocks,
                                ),
                                trip,
                                carried=carried,
                            ),
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
                # So a dropped stream can be restarted while the screen is
                # still empty. `drew_surface` and not `did_something`: the
                # latter is also true once a tool has run, and the opening
                # turn calls `save_trip` before it draws anything — so on the
                # commonest turn in the app, the restart was refused every
                # time, by a flag that was never about the screen. Replaying
                # a tool is still guarded, by `result.tool_calls` in
                # `_standby`, which is about *this* round rather than the
                # whole turn.
                # Not only "is there a surface": "would starting this round
                # again break something". A drawn surface would be drawn twice;
                # a dispatched tool has left the API waiting for a response that
                # a restarted round never sends. Neither is recoverable, and
                # neither is `result.tool_calls`, which is a request the drop
                # threw away with the rest of the turn.
                has_drawn=lambda: drew_surface or dispatched_a_tool,
                client=request.client,
            ):
                if event["type"] == "text":
                    for out in rendered(stream.push(event["delta"]), "stream"):
                        yield out
                elif event["type"] == "restart":
                    # The model dropped the stream mid-sentence and the turn is
                    # starting again on the standby. What it said belongs to the
                    # abandoned attempt: the client drops it, and so do we — a
                    # splitter still holding half a sentence would glue it to
                    # the front of the new one.
                    stream = ExpressStream(
                        parser=parser_for(request.surface_id),
                        components=COMPONENT_NAMES,
                        validator=VALIDATOR,
                        required=REQUIRED_PROPERTIES,
                                )
                    gate = FenceGate()
                    spoken = ""
                    yield event
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
            reported = describe_api_error(failure)
            # Two very different turns end here, and they were reported
            # identically. One drew nothing: the screen is empty and the model
            # being busy is the whole story. The other drew a surface and then
            # lost the stream — the form is on screen, filled in and usable,
            # and "gemini is experiencing high demand" over the top of it reads
            # as though the form is broken. It is not, and the traveller's next
            # move is to use it.
            if drew_surface and reported.get("retryable"):
                reported = {
                    **reported,
                    "message": (
                        "The model dropped out part-way through this turn — "
                        "what it had already drawn is below and still works. "
                        f"Answer it to carry on. ({reported.get('message', '')})"
                    ),
                }
            yield reported
            break
        if result is None:
            yield {
                "type": "error",
                "message": "The model stream ended without a result.",
                "retryable": True,
            }
            break

        # Deliberately *not* `previous_interaction_id = result.interaction_id`.
        # The chain this turn walks is carried in `history` instead; see the
        # note on it. What the round's id is good for is the resume point the
        # client gets at the end, because the last round's interaction holds
        # the whole turn.
        last_interaction_id = result.interaction_id or last_interaction_id
        stop_reason = result.status

        yield {"type": "usage", **result.usage.as_dict()}

        # Nothing left to do but a surface that did not compile: hand the error
        # back and let it write the block again. Once — a model that cannot fix
        # it on the second attempt will not fix it on the fifth, and the
        # traveller is waiting.
        # An unclosed fence is still a fence: a turn that stopped mid-block
        # should not spill the half of it that arrived.
        tail, trailing = gate.flush()
        if tail:
            yield {"type": "text", "delta": tail, "round": round_index}
        for block in trailing:
            if block.looks_like_a_surface and misdrawn is None:
                misdrawn = block.source

        # A surface written in a notation that does not exist. The model is
        # told once, the same way a compile error tells it, because a model
        # that reaches for the wrong notation twice will reach for it a third
        # time and the traveller is waiting.
        if not result.tool_calls and misdrawn and not retried_notation:
            retried_notation = True
            block, misdrawn = misdrawn, None
            yield {"type": "retry", "reason": "the surface was not written in Express"}
            history.append(
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "That was a fenced code block, so nothing was drawn and "
                                "the traveler saw nothing.\n\nThere is one way to draw "
                                "here and it is an `<a2ui>` block of A2UI Express — named "
                                "lines, one component each, ending in `root = ...`, using "
                                "only components this catalog defines. JSON is not it: no "
                                "`call`, no `props`, no component types you invented.\n\n"
                                "What you wrote was:\n\n"
                                f"{block[:2000]}\n\n"
                                "Write it again as Express. Do not repeat the prose — only "
                                "the <a2ui> block."
                            ),
                        }
                    ],
                }
            )
            turn_input = list(history)
            continue

        if not result.tool_calls and unreported and not retried_compile:
            retried_compile = True
            failure = unreported
            unreported = None
            yield {"type": "retry", "reason": failure["message"]}
            history.append(
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
            )
            turn_input = list(history)
            continue

        # Drew, but left nothing to answer. Ask for the controls, once.
        #
        # The surface is already on screen, so this is a replacement rather than
        # a rescue, and it is worth exactly one round: a second dashboard is a
        # traveller watching the same nothing twice.
        if not result.tool_calls and thin and not retried_thin:
            retried_thin = True
            complaint, thin = thin, None
            yield {"type": "retry", "reason": "the surface asks for nothing"}
            history.append(
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"{complaint}\n\nDraw it again into the same surface, "
                                "with those controls on it. Only the <a2ui> block."
                            ),
                        }
                    ],
                }
            )
            turn_input = list(history)
            continue

        # A turn that said what it was about to do, and did not do it.
        #
        # Last of the three retries, deliberately: a compile failure and a
        # fenced block are both *attempts* at a surface and worth correcting
        # first. This one fires when there was no attempt at all — no tool ran,
        # nothing drew, and the traveller has a sentence and an empty space.
        #
        # Once. A model that answers the nudge with another promise will answer
        # the third one the same way, and the traveller is waiting.
        if (
            not result.tool_calls
            and not did_something
            and promised(spoken)
            and not retried_promise
        ):
            retried_promise = True
            yield {"type": "retry", "reason": "the turn promised and drew nothing"}
            history.append(
                {"type": "user_input", "content": [{"type": "text", "text": TYPED_NUDGE}]}
            )
            turn_input = list(history)
            continue

        if not result.tool_calls:
            break

        did_something = True

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
                    call.name, request.surface_id, parser_for(request.surface_id), PROTOCOL_VERSION
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
            dispatched_a_tool = True
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
        # — the common shape of a first turn, which saves the trip before it
        # draws — went back to the model with the tool results and not a word
        # about the surface. The traveller got a turn with a gap in it and the
        # model never found out.
        #
        # This used to be smuggled in as another `function_result`, named
        # `render_a2ui_express` with a `call_id` of `compile-<round>`. Both were
        # fictions: the model never made that call, and no door has offered that
        # tool since the MCP handler was removed. A result answering a call that
        # was never placed is not a channel, it is a message in a bottle, and
        # "the retries are weak" is what that looks like from the outside.
        #
        # It goes as a user turn instead, after the results, which is the same
        # way every other correction in this file reaches the model.
        repair: list[dict[str, Any]] = []
        if unreported and not retried_compile:
            retried_compile = True
            yield {"type": "retry", "reason": unreported["message"]}
            repair = [
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Your A2UI block did not compile, so nothing was drawn "
                                "and the traveler is looking at a gap.\n\n"
                                f"{unreported['message']}\n\nThe block was:\n\n"
                                f"{unreported['express'][:4000]}\n\n"
                                "Answer the lookups above, then write the whole block "
                                "again, corrected. Do not repeat the prose — only the "
                                "<a2ui> block."
                            ),
                        }
                    ],
                }
            ]
            unreported = None

        # The round, both halves of it: what the model asked for and what came
        # back. The calls have to go in — a result on its own is what the API
        # refuses once it has lost the interaction that asked. The model's own
        # prose does not: a replayed `model_output` step is rejected outright,
        # so what it said this turn is on screen and not in the history.
        history.extend(call.replayable() for call in result.tool_calls)
        history.extend(results)
        history.extend(repair)
        turn_input = list(history)
        yield {"type": "trip", "trip": dict(trip), "shape": model.decision_shape(trip)}

        if round_index == MAX_TOOL_ROUNDS - 1:
            yield {
                "type": "error",
                "message": f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.",
                "retryable": True,
            }

    # The decisions' shape travels with the trip.
    #
    # The panel is redrawn when the trip's *decisions* change — a new control is
    # needed, not just a new value — and that judgement is the trip model's, so
    # it has to reach the client as a fact rather than as a rule the client
    # reimplements. It rides the trip event because that event arrives while the
    # turn is still streaming: the rebuild below happens in the tail, after the
    # answer, and a traveller who presses a fare the moment it appears cancels
    # the stream and the rebuild with it. The client compares this against the
    # shape its panel was drawn for and asks for a redraw on a request of its
    # own — which no press can cancel. Without it the panel was permanently one
    # press behind: nothing until a flight was chosen, then nothing again until
    # a hotel was.
    yield {"type": "trip", "trip": dict(trip), "shape": model.decision_shape(trip)}

    # The panels outlive the turn that drew them, so the trip reaches them as
    # ordinary A2UI rather than as something the client works out for itself.
    # Shared with the voice relay, which does the same thing at the end of its
    # own turns — see `panel_events`.
    for event in panel_events(trip):
        yield event

    # The receipt, handed over *before* the panels rather than after them.
    #
    # It used to be yielded once, at the very end of this generator — after the
    # second model call that rebuilds the sidebar. Everything that remembers the
    # trip hangs off it: the client keeps it and sends it back, and the door
    # writes the session from it. So a traveller who pressed a fare the moment
    # it appeared — which is the entire point of drawing the fares the moment
    # they land — aborted the stream before either copy was written, and the
    # next turn began with an empty trip. The agent then asked for the route,
    # the dates and the party again, which is exactly what it should do when it
    # has been handed a trip with nothing in it.
    #
    # Measured on the real client: pressing the first fare six seconds after it
    # drew sent `resume.trip: null`, and the turn after it was a boundaries
    # form. The answer is settled here; the panels are decoration that follows.
    yield {
        "type": "__result__",
        "result": TurnResult(
            interaction_id=last_interaction_id,
            trip=trip,
            stop_reason=stop_reason,
            shape=request.shape,
            setup=setup,
        ),
    }

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
            interaction_id=last_interaction_id,
            trip=trip,
            stop_reason=stop_reason,
            shape=shape,
            setup=setup,
        ),
    }


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
