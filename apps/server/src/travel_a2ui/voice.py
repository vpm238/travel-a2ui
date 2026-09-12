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

import json
import os
import pathlib
from dataclasses import dataclass
from typing import Any

from .skills import _read
from .tools import gemini_tools

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_MCP = json.loads((_ROOT / "data" / "mcp-tools.json").read_text("utf-8"))

MCP_TOOLS: list[dict[str, Any]] = _MCP["tools"]
A2UI_MIME: str = _MCP["a2uiMimeType"]


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
VOICE_BRIEF = _read("prompts", "voice.md").strip()


def voice_tools() -> list[dict[str, Any]]:
    """Everything a Live session may call.

    The `show_*` surface tools first, then the data tools. `get_destination`
    and the pricing tools stay in the list even though the surface tools
    already price: the overlap is intentional and cheap, and a voice agent
    that can look something up without drawing it is better at conversation.
    """
    surfaces = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["inputSchema"],
        }
        for tool in MCP_TOOLS
        if tool["name"].startswith("show_")
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


def setup_config(system_instruction: str, voice: str | None = None) -> dict[str, Any]:
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
        "input_audio_transcription": {},
        "output_audio_transcription": {},
    }
    if voice:
        config["speech_config"] = {
            "voice_config": {"prebuilt_voice_config": {"voice_name": voice}}
        }
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
    from .surfaces import build_surface, compile_surface
    from .tools import run_tool

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
    return {"response": {"error": result} if is_error else result}


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
    #: Where they might be flying from, as the typed path computes it.
    origin_hint: dict[str, Any] | None = None
    skill: str = "express-monolithic"
    #: Injectable so a test can drive a whole call from a scripted session.
    client: Any = None


async def relay(
    session: VoiceSession,
    send: Any,
    incoming: Any,
) -> None:
    """Runs one call until either side hangs up.

    The browser sends microphone bytes and receives audio plus A2UI — exactly
    what a Swift or Flutter client would send and receive. It could open the
    socket to Google itself; then every client would need the catalog, the
    compiler, the tools and the trip, and "thin client" would stop being true.
    """
    import asyncio

    from google.genai import Client

    from . import trip as model
    from .agent import CATALOG_ID, _parser, _today
    from .skills import build_system_prompt
    from .surface import STANDING_SURFACES, finish, panel_events, trip_updates
    from .tools import ToolContext

    today = _today()
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
        # A call had no idea where the traveller was. The typed path has offered
        # a departure airport since there was one to offer — from the timezone,
        # and now from coordinates when they share them — and voice was simply
        # never passed it, so it asked people to say an airport code out loud.
        origin_hint=session.origin_hint,
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
            model=voice_model, config=setup_config(system, session.voice)
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
                    elif kind == "text" and message.get("text"):
                        await live.send_client_content(
                            turns={"role": "user", "parts": [{"text": message["text"]}]},
                            turn_complete=True,
                        )
                    elif kind == "end":
                        break

            async def pump_live() -> None:
                nonlocal drawings
                """Audio, transcripts, tool calls and surfaces, downstream."""
                nonlocal shape
                async for frame in live.receive():
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
                            await announce(
                                {"type": "transcript", "text": spoken.text, "who": "agent"}
                            )
                        heard = getattr(content, "input_transcription", None)
                        if getattr(heard, "text", None):
                            await announce(
                                {"type": "transcript", "text": heard.text, "who": "you"}
                            )
                        if getattr(content, "turn_complete", False):
                            await announce({"type": "turn_end"})

                    call = getattr(frame, "tool_call", None)
                    calls = getattr(call, "function_calls", None) or []
                    if calls:
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

                    if getattr(frame, "go_away", None):
                        await announce(
                            {
                                "type": "error",
                                "message": "The Live session is closing — start "
                                "another when ready.",
                            }
                        )

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
    from .agent import CATALOG_ID, PANEL_REQUEST, COMPONENT_NAMES, _parser
    from .express import ExpressStream, Ui
    from .gemini import stream_interaction
    from .skills import build_system_prompt
    from .surface import STANDING_SURFACES, finish

    for surface_id in STANDING_SURFACES:
        system = build_system_prompt(
            variant=session.skill,
            surface=surface_id,
            surface_id=surface_id,
            catalog_id=CATALOG_ID,
            trip=trip,
            today=today,
        )
        stream = ExpressStream(parser=_parser(surface_id), components=COMPONENT_NAMES)
        drawn: list[dict[str, Any]] = []
        try:
            async for event in stream_interaction(
                api_key=session.api_key,
                model="gemini-3.8-flash",
                input=[
                    {"type": "user_input", "content": [{"type": "text", "text": PANEL_REQUEST}]}
                ],
                system_instruction=system,
                thinking_level="low",
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
