"""What a Gemini Live session is given.

Only the parts the rest of the server needs right now: the tool list, and the
schema cleaning the Live API requires. The relay itself — `client.aio.live` —
is the next piece, and it is deliberately separate, because what a session is
*set up with* is what the contract stamp is computed over, and that has to be
answerable without opening a socket.

The Live API takes a subset of JSON Schema and rejects the whole setup rather
than the offending key, so a schema that is perfectly good for the Interactions
API has to be cleaned before it can be sent here. That asymmetry is the reason
this function exists at all.
"""

from __future__ import annotations

from .. import ROOT

import json
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from ..brain.promises import SPOKEN_NUDGE as _NUDGE, promised as _promised
from ..brain.skills import _read
from ..brain.tools import gemini_tools

_ROOT = ROOT

#: The six layouts a session can ask for by name, with their argument schemas.
#:
#: These were written as MCP tool declarations and outlived MCP. A spoken
#: session cannot write Express — its replies are audio, so a notation in one is
#: read aloud rather than compiled — which leaves calling a tool as the only way
#: it can reach the screen at all. That is what these are for now, and the file
#: is named for that rather than for the protocol they were first written in.
SURFACE_TOOLS: list[dict[str, Any]] = json.loads(
    (_ROOT / "data" / "surface-tools.json").read_text("utf-8")
)["tools"]


#: The model a Live session runs on.
#:
#: Here rather than in `contract.py`, which fingerprints it: a module should not
#: import the module that fingerprints it. The cycle would work — both sides
#: only touch each other inside functions — right up until an unrelated edit
#: moves one of those calls to import time.
VOICE_MODEL = os.environ.get(
    "VOICE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
)
#: The 09-2025 build this used to name is gone — withdrawn, and no longer listed
#: among the models that serve `bidiGenerateContent`. That is the whole of why
#: voice stopped working: the connect was answered with NOT_FOUND, which reads
#: like a bug in this app rather than like a model that no longer exists.
#:
#: 12-2025 is its direct successor in the same family, so the setup config, the
#: tool schemas and the audio format all carry over unchanged. The other current
#: option is `gemini-3.1-flash-live-preview`, which is newer and lower-latency;
#: it is not the default only because this one is the smaller change from what
#: was here, and voice needs to be working before it is worth tuning.
#: Overridable because the default is a *preview* model, and previews are
#: withdrawn. When that happens the Live API answers a connect with NOT_FOUND
#: and voice stops working for a reason that has nothing to do with this code —
#: so the name is a setting, and a deployment can be corrected without one.
#: Every other model this app uses is on a stable channel; this one has no
#: stable equivalent to point at, which is why it is the one that can rot.


#: How to behave on a call rather than in a chat window.
#:
#: Appended to the ordinary system prompt rather than replacing it: the agent is
#: the same agent, with the same catalog and the same refusals, talking instead
#: of typing. Everything specific to *speaking* is here.
VOICE_BRIEF = _read("prompts", "live.md").strip()


def voice_tools() -> list[dict[str, Any]]:
    """Everything a Live session may call.

    The `show_*` surface tools first, then the data tools. The overlap between
    them — both can price a flight — was called intentional and cheap, and it is
    neither: given a tool that returns fares and a tool that draws them, the
    model takes the one that returns them and reads them out. The lookups stay,
    because a voice agent that can answer "is there a nonstop" without redrawing
    the screen is better at conversation, but their results no longer carry the
    rows. See `_without_the_list`.
    """
    surfaces = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["inputSchema"],
        }
        for tool in SURFACE_TOOLS
    ]
    data = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        for tool in gemini_tools()
    ]
    return [*surfaces, *data]


def live_schema(schema: Any) -> Any:
    """Strips JSON Schema keywords the Live API's function declarations reject.

    `additionalProperties`, `$schema` and `strict` are not in the subset it
    accepts, and it rejects the entire setup rather than the key — so a session
    fails to open with a message about the setup frame and nothing pointing at
    the schema that caused it.
    """
    if isinstance(schema, list):
        return [live_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: live_schema(value)
        for key, value in schema.items()
        if key not in ("additionalProperties", "$schema", "strict")
    }


# --------------------------------------------------------------------------
# One voice call
# --------------------------------------------------------------------------


#: What the session speaks and, more to the point, what it transcribes as.
#:
#: Left unset, the transcriber detects the language per utterance — and English
#: spoken in an accent it is unsure of comes back transliterated into whatever
#: script it landed on. A traveller saying "plan me a trip from San Francisco to
#: New York" watched their own words appear as
#: "प्लांट मी अ ट्रिप फ्रॉम सन फ्रांसिस्को टू न्यूयॉर्क सिटी": not a translation,
#: the same English sounds in Devanagari. The model still understood it, which
#: is why nothing downstream complained, but the transcript is the only proof a
#: caller has that they were heard — and that one says they were not.
#:
#: So the language is pinned rather than guessed. An override belongs here when
#: this app is offered in a second language; until it is, guessing buys nothing
#: and costs the transcript.
DEFAULT_LANGUAGE = "en-US"


def setup_config(
    system_instruction: str,
    voice: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    resume: str | None = None,
) -> dict[str, Any]:
    """What a Live session is opened with.

    The schemas go through `live_schema` because the Live API takes a subset of
    JSON Schema and rejects the *entire* setup over one unsupported keyword,
    with a message about the setup frame and nothing pointing at the schema
    that caused it. Ordinary Gemini tool schemas all carry
    `additionalProperties`, so every one of them has to be cleaned.

    Both transcripts are on, so the conversation has a readable record: what
    they said is the only way to show a caller they were heard correctly.
    """
    config: dict[str, Any] = {
        "response_modalities": ["AUDIO"],
        "system_instruction": f"{system_instruction}\n\n---\n\n{VOICE_BRIEF}",
        "tools": [
            {
                "function_declarations": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": live_schema(tool["parameters"]),
                    }
                    for tool in voice_tools()
                ]
            }
        ],
        # Naming the language *is* how auto-detection is turned off: the SDK
        # documents detection as the default "when language_codes is omitted",
        # and the `language_auto` flag that used to say so is deprecated — and
        # is a nested object rather than the boolean it reads like, so setting
        # it to False is rejected outright by the setup frame.
        "input_audio_transcription": {"language_codes": [language]},
        "output_audio_transcription": {},
    }
    speech: dict[str, Any] = {"language_code": language}
    if voice:
        speech["voice_config"] = {"prebuilt_voice_config": {"voice_name": voice}}
    config["speech_config"] = speech

    # Declared on every connection, with or without a handle.
    #
    # Without this the API sends no `session_resumption_update` at all, so
    # there is never a handle to reconnect with — and a session that reaches
    # its own time limit takes the conversation with it. `handle=None` is a new
    # conversation that *can* be resumed later; a handle is one being picked up.
    config["session_resumption"] = {"handle": resume} if resume else {}
    return config


async def run_voice_tool(
    name: str,
    args: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """Runs one function call and says what to do with the result.

    A surface tool produces two things — a summary for the model to *say* and
    A2UI for the browser to draw — and the split is the point. Sending the whole
    surface back to the model would put a flight list in its context and invite
    it to read the list out, which is the one thing this mode is for not doing.
    """
    from ..brain.surfaces import build_surface, compile_surface
    from ..brain.tools import run_tool

    if name.startswith("show_") or name == "render_a2ui_express":
        try:
            # The tools take the trip as arguments; the session holds it, so it
            # is merged under whatever the model chose to pass.
            surface = await build_surface(
                name, {**context.trip, **args}, context.provider, context.day()
            )
            messages = compile_surface(surface)
            return {
                "response": {"shown": True, "summary": surface.summary},
                "ui": {"surfaceId": surface.surface_id, "messages": messages},
            }
        except Exception as error:  # noqa: BLE001 - the model gets the sentence
            return {"response": {"shown": False, "error": str(error)}}

    result, is_error = await run_tool(name, args, context)
    if is_error:
        return {"response": {"error": result}}
    return {"response": _without_the_list(name, result)}


#: Lookups whose answer is a list, and the tool that puts that list on screen.
#:
#: Both are offered in a call and the overlap was called intentional and cheap.
#: It is neither. Given a tool that returns fares and a tool that draws them,
#: the model takes the one that returns them — it is one call and it answers the
#: question — and then does the only thing you can do with a list you are
#: holding out loud, which is read it.
#:
#: That is not a hypothesis. A traveller asked for San Francisco to New York and
#: got "options range from $249 to $306… the return starts at $460 and goes up
#: to $632. You can see the options here for both legs", with nothing on screen
#: at all. Four fares recited down a phone line, and a sentence that was not
#: true.
_DRAWN_BY = {
    "search_flights": "show_flight_options",
    "search_hotels": "show_hotel_options",
}


def _without_the_list(name: str, result: Any) -> Any:
    """The same answer, minus the part that can be read aloud.

    The model still learns what it needs to *speak* one sentence — how many
    there are and what the cheapest is — and is told, in the result itself,
    which tool puts them where the traveller can see them. What it does not get
    is twelve rows of fares, because a list in context is a list read out.

    This is not composition moving to the server: the model still chooses the
    tool, the surface and the layout. It just cannot narrate a table it was
    never handed.
    """
    drawer = _DRAWN_BY.get(name)
    if not drawer or not isinstance(result, dict):
        return result

    items = result.get("items")
    if not isinstance(items, list) or not items:
        return result

    cheapest = min(
        (item for item in items if isinstance(item, dict) and item.get("price")),
        key=lambda item: item.get("priceValue") or float("inf"),
        default=None,
    )
    kept = {key: value for key, value in result.items() if key != "items"}
    kept["found"] = len(items)
    if cheapest:
        kept["cheapest"] = cheapest.get("price")
    kept["note"] = (
        f"The {len(items)} results are deliberately not in this response — reading "
        f"them aloud is what this mode exists to avoid. Call `{drawer}` to put them "
        "on screen, then say one sentence about what is there."
    )
    return kept


@dataclass
class VoiceSession:
    """One call: the traveller's socket on one side, Gemini Live on the other.

    The transport is injected rather than assumed — `send` is a coroutine taking
    a dict, and `incoming` is an async iterator of dicts — so the relay does not
    know whether it is talking to a FastAPI WebSocket or a test. That is not
    only for testing: it is what stopped the Worker version being written around
    one runtime's socket, which is where three of its bugs came from.
    """

    api_key: str
    trip: dict[str, Any]
    provider: Any
    contract: str
    #: Called with the trip whenever a tool changes it, so the typed
    #: conversation and the panels see the same trip this call is changing.
    on_trip: Any = None
    model: str = ""
    voice: str | None = None
    #: What the browser knows about when the traveller is. See `agent._today`.
    client_hints: dict[str, Any] | None = None
    skill: str = "express-modular"
    #: Where to pick the conversation up from, if there is one to pick up.
    #:
    #: `None` starts a new one. Anything else is a handle the API gave us on a
    #: previous connection, and opening with it means the model still knows what
    #: was said before the microphone was last released.
    resume: str | None = None
    #: Called with each fresh handle, so the next connection has one to use.
    on_resume: Any = None
    #: Injectable so a test can drive a whole call from a scripted session.
    client: Any = None


async def relay(
    session: VoiceSession,
    send: Any,
    incoming: Any,
) -> None:
    """Runs one call until either side hangs up.

    The browser sends microphone bytes and receives audio plus A2UI — exactly
    what the Flutter client sends and receives. It could open the
    socket to Google itself; then every client would need the catalog, the
    compiler, the tools and the trip, and "thin client" would stop being true.
    """
    import asyncio

    from google.genai import Client

    from ..brain import trip as model
    from .interactions import CATALOG_ID, _parser, _today
    from ..brain.skills import build_system_prompt
    from ..brain.surface import (
    REBUILT_IN_A_TURN,
    STANDING_SURFACES,
    finish,
    panel_events,
    trip_updates,
)
    from ..brain.tools import ToolContext

    today = _today(session.client_hints)
    trip = dict(session.trip)
    voice_model = session.model or VOICE_MODEL

    async def announce(message: dict[str, Any]) -> None:
        try:
            await send(message)
        except Exception:  # noqa: BLE001 - the caller went away; the loop ends
            pass

    def save(patch: dict[str, Any]) -> None:
        nxt = model.merge(trip, patch)
        trip.clear()
        trip.update(nxt)
        if session.on_trip:
            session.on_trip(dict(trip))

    context = ToolContext(trip=trip, provider=session.provider, save=save, today=today)

    system = build_system_prompt(
        variant=session.skill,
        surface="inline",
        surface_id="voice-1",
        catalog_id=CATALOG_ID,
        trip=trip,
        today=today,
        # Tools, not Express. This session answers in audio, so anything the
        # model writes is *spoken* — and `voice_tools()` carries no compiler to
        # send a notation to. Teaching it Express here made it emit
        # `<a2ui> surface("voice-1") …` into its reply about one turn in three:
        # read aloud, never drawn, and invisible in every log.
        draws="tools",
    )

    genai = session.client or Client(api_key=session.api_key)
    # The decision shape when the panels were last drawn. A voice call changes
    # the trip like any other turn, and the panel beside it went on showing the
    # trip as it was when the call started — which is the gap this closes.
    shape = model.decision_shape(trip)
    #: How many surfaces this call has drawn, so each gets its own id.
    drawings = 0

    try:
        async with genai.aio.live.connect(
            model=voice_model,
            config=setup_config(system, session.voice, resume=session.resume),
        ) as live:
            # `ready` is sent here and not a moment earlier. The Worker sent it
            # as soon as the setup frame had been *written*, which is a
            # different claim: a rejected key, a model that does not exist and a
            # tool schema the API will not accept all get as far as the write.
            # The client then believed it had a session and found out otherwise
            # when somebody spoke — survivable while `ready` only unlocked a
            # microphone, not survivable now that instantiating is recorded.
            await announce(
                {"type": "ready", "model": voice_model, "contract": session.contract}
            )

            async def pump_client() -> None:
                """Microphone bytes and typed text, upstream."""
                async for message in incoming:
                    kind = message.get("type")
                    if kind == "audio":
                        await live.send_realtime_input(
                            audio={
                                "data": message["data"],
                                "mime_type": "audio/pcm;rate=16000",
                            }
                        )
                    elif kind == "audio_end":
                        # The microphone stopped; let the model take its turn.
                        #
                        # This is the frame the whole feature was missing. The
                        # model answers on voice activity detection, and VAD
                        # decides somebody has stopped talking by *hearing* the
                        # silence after them. A browser that stops sending the
                        # moment the traveller stops speaking never sends that
                        # silence, so the model waits for audio that is not
                        # coming and nothing happens — which is exactly what it
                        # looked like.
                        #
                        # Ending the audio stream says it explicitly. The
                        # session stays open: this is not a hang-up, it is the
                        # end of one thing said.
                        await live.send_realtime_input(audio_stream_end=True)
                    elif kind == "text" and message.get("text"):
                        await live.send_client_content(
                            turns={"role": "user", "parts": [{"text": message["text"]}]},
                            turn_complete=True,
                        )
                    elif kind == "end":
                        break

            async def pump_live() -> None:
                nonlocal drawings
                """Audio, transcripts, tool calls and surfaces, downstream.

                `receive()` is **one turn**, not the session. The SDK's own loop
                is `while result := await self._receive(): ... if complete:
                break` — so an `async for` over it ends the moment the model
                stops talking, and this function returned. `_race` then saw a
                pump finish and tore the call down.

                Every Live conversation in this app was therefore exactly one
                turn long: the first answer arrived, the traveller replied, and
                nothing ever came back. It looked like the model ignoring them,
                which is why it read as "voice does not work" rather than as a
                loop that had quietly ended.

                So the turns are the outer loop and `receive()` is the inner
                one, which is how the SDK's own examples read once you notice
                they call it per turn.
                """
                nonlocal shape
                # A turn that yielded nothing is a closed session, not a quiet
                # one: that is how this ends when the socket goes away, rather
                # than spinning on an exhausted stream.
                while await _one_turn():
                    pass

            async def _one_turn() -> bool:
                """One model turn. False when the session has nothing left."""
                nonlocal drawings
                nonlocal shape
                alive = False
                # Per turn, not per session: what this turn said and whether it
                # did anything. Reset on every `turn_complete` below, because a
                # turn that already earned its nudge must not spend the next
                # turn's one too.
                spoken_this_turn = ""
                called_this_turn = False
                nudged = False
                async for frame in live.receive():
                    alive = True
                    content = getattr(frame, "server_content", None)
                    if content is not None:
                        turn = getattr(content, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            inline = getattr(part, "inline_data", None)
                            data = getattr(inline, "data", None)
                            if data:
                                # Already 24 kHz PCM. Straight through: decoding
                                # it here would only be to re-encode it.
                                await announce({"type": "audio", "data": _b64(data)})
                        spoken = getattr(content, "output_transcription", None)
                        if getattr(spoken, "text", None):
                            # Belt and braces over the prompt. The instruction
                            # says not to write interface code on this channel;
                            # if a turn does it anyway, the traveller should not
                            # have to *hear* it. Dropping it from the transcript
                            # cannot unsay the audio, but it keeps the written
                            # record readable and makes the mistake obvious in
                            # a way that a wall of Express does not.
                            said = _without_markup(spoken.text)
                            spoken_this_turn += said
                            if said:
                                await announce(
                                    {"type": "transcript", "text": said, "who": "agent"}
                                )
                        heard = getattr(content, "input_transcription", None)
                        if getattr(heard, "text", None):
                            await announce(
                                {"type": "transcript", "text": heard.text, "who": "you"}
                            )
                        if getattr(content, "turn_complete", False):
                            # A turn that promised and did nothing is not over.
                            #
                            # Measured, not guessed: asked for flights six
                            # times, this said "Let me find some flights for
                            # you" and ended the turn five times — the exact
                            # sentence the brief forbids by name, in a brief
                            # that says drawing is not optional in bold. The
                            # traveller hears a promise, watches an unchanged
                            # screen, and concludes the app is broken.
                            #
                            # No amount of further wording fixes a 5-in-6
                            # instruction-following gap, so the turn is handed
                            # back once with what it actually did. Once, and
                            # only when nothing was called and nothing drawn:
                            # a nudge that can itself be ignored must not be
                            # able to loop.
                            if _promised(spoken_this_turn) and not called_this_turn:
                                if not nudged:
                                    nudged = True
                                    await live.send_client_content(
                                        turns={
                                            "role": "user",
                                            "parts": [{"text": _NUDGE}],
                                        },
                                        turn_complete=True,
                                    )
                                    continue
                            await announce({"type": "turn_end"})
                            spoken_this_turn = ""
                            called_this_turn = False
                            nudged = False

                    call = getattr(frame, "tool_call", None)
                    calls = getattr(call, "function_calls", None) or []
                    if calls:
                        called_this_turn = True
                        responses = []
                        for function in calls:
                            args = dict(getattr(function, "args", None) or {})
                            await announce(
                                {"type": "tool", "name": function.name, "input": args}
                            )
                            # One surface per drawing, not one per tool.
                            #
                            # Surfaces were keyed by what they showed, so every
                            # flight search in a call wrote to `mcp-flights`:
                            # "flights to Madrid", then "what about Lisbon", and
                            # the second replaced the first while the traveller
                            # was still looking at it. The typed side had the
                            # same bug under a different name and the same fix —
                            # a call is a conversation, and a conversation is a
                            # list of things asked, not one card rewritten.
                            #
                            # Only set when the model did not choose one itself,
                            # so it can still redraw a surface on purpose.
                            if function.name.startswith("show_") and not args.get("surfaceId"):
                                drawings += 1
                                args["surfaceId"] = f"voice-{drawings}"
                            outcome = await run_voice_tool(function.name, args, context)
                            drawn = outcome.get("ui")
                            if drawn:
                                await announce(
                                    {
                                        "type": "ui",
                                        "surfaceId": drawn["surfaceId"],
                                        "messages": finish(drawn["messages"], trip),
                                        "done": True,
                                    }
                                )
                            responses.append(
                                {
                                    "id": getattr(function, "id", None),
                                    "name": function.name,
                                    "response": outcome["response"],
                                }
                            )
                        # The turn is paused until this lands, so it goes back in
                        # one frame rather than one per call.
                        await live.send_tool_response(function_responses=responses)

                        # The panels, which a voice call used to leave stale.
                        # Saying "make it three of us" out loud changed the trip
                        # and the record beside it went on saying two, which
                        # reads as the app not having heard — the exact
                        # impression the transcripts exist to prevent.
                        await announce({"type": "trip", "trip": dict(trip)})
                        # The same refresh the typed turn does, from the same
                        # function — see `panel_events`.
                        for event in panel_events(trip):
                            await announce(event)

                        # And a real redraw when the decisions changed shape
                        # enough to need different controls — the same rule the
                        # typed turn uses, and the same one model turn, spent
                        # only when it is warranted.
                        moved = model.decision_shape(trip)
                        if moved != shape and trip.get("destination"):
                            shape = moved
                            await _redraw_panels(
                                session, trip, today, announce, genai
                            )

                    # A fresh handle, as the API issues them.
                    #
                    # Kept rather than announced: this is the server's business,
                    # and a client that had to carry it would be a client that
                    # could lose it. `resumable` is false while a turn is in
                    # flight — a handle taken then would resume to a half-spoken
                    # answer — so only a resumable one is worth keeping.
                    update = getattr(frame, "session_resumption_update", None)
                    if update is not None and getattr(update, "resumable", False):
                        handle = getattr(update, "new_handle", None)
                        if handle and handle != session.resume:
                            session.resume = handle
                            if session.on_resume:
                                session.on_resume(handle)

                    if getattr(frame, "go_away", None):
                        # Google's session reached its own time limit. That is
                        # not the traveller's conversation ending — it is a
                        # connection ending — and the difference is the whole
                        # reason the handle above is kept.
                        #
                        # Ending the turn loop here closes the browser's socket,
                        # and the next microphone press opens a new session. With
                        # a handle, that new session is the same conversation
                        # picked up where it stopped; without one it is a
                        # stranger who has never heard of the trip, which is
                        # what made releasing the microphone feel like a reset.
                        if not session.resume:
                            await announce(
                                {
                                    "type": "error",
                                    "message": "The Live session is closing — start "
                                    "another when ready.",
                                }
                            )
                        return False

                return alive

            # Both directions at once, and either ending ends the call: a
            # browser that closed should not leave a Live session running, and a
            # Live session that closed has nothing left to send.
            await _race(asyncio, pump_client(), pump_live())

    except Exception as error:  # noqa: BLE001 - every failure reaches the caller
        await announce({"type": "error", "message": _describe_live_error(error)})
    finally:
        await announce({"type": "turn_end"})


async def _redraw_panels(
    session: VoiceSession,
    trip: dict[str, Any],
    today: str,
    announce: Any,
    genai: Any,
) -> None:
    """A model-composed panel, for a trip a voice call changed.

    Drawn through the Interactions API rather than the Live session, because
    asking the Live model for a panel would make it *say* the panel. The same
    server, the same catalog, the same skill; a different mouth.

    Failures are silent on purpose: the traveller is mid-conversation and their
    answer already arrived. A panel one turn stale is a much smaller problem
    than an error over a call that is going fine.
    """
    from .interactions import (
        CATALOG_ID,
        COMPONENT_NAMES,
        PANEL_EFFORT,
        PANEL_MODEL,
        PANEL_REQUEST,
        _parser,
    )
    from ..brain.express import ExpressStream, Ui
    from ..gemini import stream_interaction
    from ..brain.skills import build_system_prompt
    from ..brain.surface import REBUILT_IN_A_TURN, finish

    for surface_id in REBUILT_IN_A_TURN:
        system = build_system_prompt(
            variant=session.skill,
            surface=surface_id,
            surface_id=surface_id,
            catalog_id=CATALOG_ID,
            trip=trip,
            today=today,
        )
        from .interactions import _CATALOG, REQUIRED_PROPERTIES

        stream = ExpressStream(
            parser=_parser(surface_id),
            components=COMPONENT_NAMES,
            validator=_CATALOG.validator,
            required=REQUIRED_PROPERTIES,
        )
        drawn: list[dict[str, Any]] = []
        try:
            async for event in stream_interaction(
                api_key=session.api_key,
                # The same model and effort the typed door uses, from the same
                # constants. These were `DEFAULT_MODEL`/`low` here and
                # `FALLBACK_MODEL`/`minimal` there, off byte-identical prompts —
                # so the sidebar changed character when you switched runtime,
                # for no reason anybody chose.
                model=PANEL_MODEL,
                input=[
                    {"type": "user_input", "content": [{"type": "text", "text": PANEL_REQUEST}]}
                ],
                system_instruction=system,
                thinking_level=PANEL_EFFORT,
                client=session.client,
            ):
                if event["type"] == "text":
                    drawn.extend(
                        {
                            "type": "ui",
                            "surfaceId": surface_id,
                            "messages": finish(item.messages, trip),
                            "done": item.done,
                        }
                        for item in stream.push(event["delta"])
                        if isinstance(item, Ui)
                    )
            drawn.extend(
                {
                    "type": "ui",
                    "surfaceId": surface_id,
                    "messages": finish(item.messages, trip),
                    "done": item.done,
                }
                for item in stream.end()
                if isinstance(item, Ui)
            )
        except Exception:  # noqa: BLE001 - a stale panel beats an error on a call
            return
        for event in drawn:
            await announce(event)


async def _race(asyncio_module: Any, *coroutines: Any) -> None:
    """Runs both pumps; the first to finish ends the other."""
    tasks = [asyncio_module.ensure_future(item) for item in coroutines]
    try:
        await asyncio_module.wait(tasks, return_when=asyncio_module.FIRST_COMPLETED)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio_module.gather(*tasks, return_exceptions=True)


#: An `<a2ui>` block, opened or closed, and the Express lines inside one.
#:
#: Matched loosely because a transcript arrives in fragments: " surface(", then
#: "\"voice-1\")", then the next line. There is no point waiting for a
#: well-formed block that will never be delivered in one piece.
_MARKUP = re.compile(
    r"</?a2ui>|^\s*(?:surface\s*\(|\$/[\w/]+\s*=|\w+\s*=\s*[A-Z]\w*\s*\()",
    re.MULTILINE,
)


def _without_markup(text: str) -> str:
    """What is left of a spoken line once interface code is taken out of it.

    A Live session answers in audio, so the model's text *is* its speech. A turn
    that writes Express writes it into the transcript and says it out loud —
    "less than a2ui greater than, surface, open paren, quote, voice dash one" —
    which is the worst thing this app can do to somebody who is listening.

    The prompt is what stops it (see `SPOKEN_DRAWING`); this is what keeps the
    written record clean when the prompt is not enough. It cannot unsay the
    audio, and it deliberately does not try to *compile* what it finds: there is
    no surface id to trust, no guarantee the fragment is whole, and drawing
    something half-said is worse than drawing nothing.
    """
    if not _MARKUP.search(text):
        return text
    kept = [line for line in text.split("\n") if not _MARKUP.search(line)]
    return "\n".join(kept).strip()


def _b64(data: Any) -> str:
    """Audio as base64, whichever shape the SDK hands it over in."""
    import base64

    if isinstance(data, str):
        return data
    return base64.b64encode(bytes(data)).decode("ascii")


def _describe_live_error(error: Exception) -> str:
    text = str(error)
    lowered = text.lower()
    if "api key" in lowered or "401" in text or "403" in text:
        return "That API key was rejected for the Live API."
    if "quota" in lowered or "429" in text:
        return "That key has hit its Live API quota. Try again shortly."
    # A withdrawn preview is the failure this is most likely to be, and the one
    # the raw message explains worst: the SDK says NOT_FOUND, which reads as a
    # bug in this app rather than as a model that no longer exists. Naming the
    # model and where to change it turns an outage into a setting.
    if "not_found" in lowered or "404" in text or "was not found" in lowered:
        return (
            f"The Live model “{VOICE_MODEL}” is not available to that key. It is a "
            "preview model, and previews get withdrawn — set VOICE_MODEL on the "
            "server to a current one."
        )
    if "not supported" in lowered or "unsupported" in lowered:
        return (
            f"The Live API refused “{VOICE_MODEL}”: {text}. Set VOICE_MODEL on the "
            "server to a model that supports the Live API."
        )
    return text or "The Live session failed to open."
