"""A voice call: the traveller's socket on one side, Gemini Live on the other.

A Live session answers in audio, so the model cannot put an `<a2ui>` block in
its reply: whatever it writes is spoken. It draws by calling one tool,
`render_a2ui_express`, with the same Express block a typed turn would write.
The block is read by the same A2UI processor against the same mirror of the
renderer (`brain/ui.py`), so a call and a typed turn draw the same surfaces
the same way. The data tools are the typed door's, and a lookup's rows land in
the data model of the cards this turn drew, exactly as they do there.

The Live API takes a subset of JSON Schema and rejects the whole setup over one
unsupported keyword, so tool schemas are cleaned (`live_schema`) before they
are sent.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .. import ROOT
from ..brain import data, inbound
from ..brain import trip as model
from ..brain.presses import describe_action, record_press
from ..brain.promises import SPOKEN_NUDGE as _NUDGE
from ..brain.promises import promised as _promised
from ..brain.skills import build_system_prompt
from ..brain.tools import ToolContext, gemini_tools, run_tool
from ..brain.ui import Canvas, Drawing
from .interactions.panels import draw_panel
from .interactions.turn import places_and_currency, ui_events
from .settings import _today

#: The model a Live session runs on.
#:
#: Here rather than in `contract.py`, which fingerprints it: a module should not
#: import the module that fingerprints it. The cycle would work — both sides
#: only touch each other inside functions — right up until an unrelated edit
#: moves one of those calls to import time.
VOICE_MODEL = os.environ.get("VOICE_MODEL", "gemini-3.8-live")
#: Gemini 3.8 Live is the first Live model on a stable channel. The name stays
#: a setting because a withdrawn Live model answers a connect with NOT_FOUND,
#: which reads like a bug in this app; a deployment can move off one without a
#: release. The audio format, the transcription config and the tool schemas all
#: carry over; what 3.8 changes is the *default* for function calling, which is
#: why `setup_config` names one. See there.
#:
#: The sibling `gemini-3.8-live-extended-thinking` reasons in the background and
#: fills the silence with spoken "checking that now"s. It is not the default
#: because it only accepts `NON_BLOCKING` tools and reports being finished
#: through `interaction_status` rather than `turn_complete` — both of which the
#: relay below would need to learn first.


#: How to behave on a call rather than in a chat window.
#:
#: Appended to the ordinary system prompt rather than replacing it: the agent is
#: the same agent, with the same catalog and the same refusals, talking instead
#: of typing. Everything specific to *speaking* is here.
VOICE_BRIEF = (ROOT / "prompts" / "live.md").read_text("utf-8").strip()

#: The one tool that draws.
RENDER_TOOL: dict[str, Any] = {
    "name": "render_a2ui_express",
    "description": (
        "Draws an interface on the traveller's screen. Pass one A2UI Express block, "
        "written exactly as the instructions describe, with or without the <a2ui> "
        "tags. A block with no surface(...) line becomes a new card in the "
        "conversation. The result says what was drawn, or what was wrong with the "
        "block so you can call again with it fixed."
    ),
    "parameters": {
        "type": "object",
        "properties": {"express": {"type": "string", "description": "The A2UI Express block."}},
        "required": ["express"],
    },
}


#: How long a stored instantiation is good for, stamp unchanged.
INSTANTIATION_MAX_AGE_MS = 24 * 60 * 60 * 1000


def contract_stamp() -> str:
    """A fingerprint of what a Live session is set up with right now.

    The Live API has no agent object on the server: a session is set up from
    what is sent at connect time. A client keeps the stamp it instantiated
    under, and when the catalog, the A2UI instructions, the tools or the model
    change, the stamp moves and the client instantiates again.
    """
    import hashlib
    import json

    from ..brain.catalog import CATALOG_JSON, PROCESSOR

    parts = [
        json.dumps(CATALOG_JSON, sort_keys=True, ensure_ascii=False),
        PROCESSOR.prompt_snippet,
        json.dumps(voice_tools(), sort_keys=True, ensure_ascii=False),
        VOICE_MODEL,
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def voice_tools() -> list[dict[str, Any]]:
    """Everything a Live session may call: the drawing tool, then the data tools."""
    return [
        RENDER_TOOL,
        *(
            {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}
            for tool in gemini_tools()
        ),
    ]


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

#: How a tool call is scheduled against the model's speech. See `setup_config`.
TOOL_BEHAVIOR = "BLOCKING"


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

    Every tool is declared `BLOCKING`. Gemini 3.8 Live made asynchronous calls
    (`NON_BLOCKING`) the default: the model fires the call, keeps talking, ends
    its turn, and speaks again whenever the result lands. The relay's turn
    accounting — one promise-nudge per turn, "did this turn call anything", the
    panel refresh after a call — all assume the result arrives *inside* the turn
    that asked for it, and the tools answer in milliseconds from a fixture, so
    there is no silence for an async call to fill. Naming the old
    behaviour keeps the relay honest; the setting is what 3.8 offers for exactly
    this case.
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
                        "behavior": TOOL_BEHAVIOR,
                        "parameters": live_schema(tool["parameters"]),
                    }
                    for tool in voice_tools()
                ]
            }
        ],
        # Naming the language *is* how auto-detection is turned off: the SDK
        # documents detection as the default "when language_codes is omitted",
        # and the deprecated `language_auto` flag is a nested object rather than the boolean it reads like, so setting
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


def render(express: str, canvas: Canvas, surface_id: str, values: Any) -> tuple[list[tuple], list[str]]:
    """Draws one block through the processor; the events, and what went wrong."""
    text = express if "<a2ui>" in express else f"<a2ui>\n{express.strip()}\n</a2ui>"
    # The model names its own cards in a call; a block with no surface line
    # draws into `surface_id`, the next `voice-N`.
    drawing = Drawing(canvas, surface_id, values, creatable="any")
    events = [*drawing.feed(text), *drawing.close()]
    problems = [event[1] for event in events if event[0] in ("rejected", "advice")]
    return events, problems


#: How long a message for the model waits on a turn that never says it ended.
#:
#: A turn ends with `turn_complete`. If one never arrives, a queue that waited
#: for it forever would swallow everything the traveller said after it.
_WAIT_FOR_TURN_SECONDS = 20.0


def cards_drawn(surfaces: Any) -> int:
    """The highest `voice-N` in use, so the next card is `voice-{N + 1}`."""
    return max([0, *(int(s[6:]) for s in surfaces if s.startswith("voice-") and s[6:].isdigit())])


@dataclass
class VoiceSession:
    """One call. The transport is injected: `send` takes a dict, `incoming`
    yields dicts, so the relay does not know a WebSocket from a test."""

    api_key: str
    trip: dict[str, Any]
    provider: Any
    contract: str
    #: Called with the trip whenever it changes, so the typed conversation sees it.
    on_trip: Any = None
    model: str = ""
    voice: str | None = None
    #: What the browser knows about when the traveller is. See `_today`.
    client_hints: dict[str, Any] | None = None
    #: Where to pick the conversation up from: a handle from a previous
    #: connection, or None to start a new one.
    resume: str | None = None
    #: Called with each fresh handle, so the next connection has one to use.
    on_resume: Any = None
    #: The mirror of the renderer, shared with the typed door.
    canvas: Canvas = field(default_factory=Canvas)
    #: The surface ids the renderer said it holds when the call opened, so a
    #: new card never reuses one, even after the server lost the session.
    held: list[str] = field(default_factory=list)
    #: Injectable so a test can drive a whole call from a scripted session.
    client: Any = None


async def relay(
    session: VoiceSession,
    send: Any,
    incoming: Any,
) -> None:
    """Runs one call until either side hangs up.

    The browser sends microphone bytes, typed lines and presses, and receives
    audio, transcripts and A2UI. It could open the socket to Google itself;
    then every client would need the catalog, the processor, the tools and the
    trip.
    """
    import asyncio

    from google.genai import Client

    today = _today(session.client_hints)
    trip = dict(session.trip)
    canvas = session.canvas
    voice_model = session.model or VOICE_MODEL
    loop = asyncio.get_running_loop()
    places, currency = await places_and_currency(session.provider, trip)
    trip["currency"] = currency

    async def announce(message: dict[str, Any]) -> None:
        try:
            await send(message)
        except Exception:  # noqa: BLE001 - the caller went away; the loop ends
            pass

    def save(patch: dict[str, Any]) -> None:
        merged = model.merge(trip, patch)
        trip.clear()
        trip.update(merged)
        if session.on_trip:
            session.on_trip(dict(trip))

    context = ToolContext(trip=trip, provider=session.provider, save=save, today=today)

    #: The cards this turn drew, and the rows its lookups returned for them.
    this_turn: set[str] = set()
    lookups = canvas.lookups
    canvas.this_turn = set()

    def values(surface_id: str) -> dict[str, Any]:
        out = data.session_values(trip, places)
        # This turn's lookup rows go to the cards this turn draws or updates.
        if surface_id in canvas.this_turn or surface_id == next_card():
            out.update(data.turn_values(lookups, trip))
        return out

    #: How many cards this call has drawn, so each gets its own id.
    drawings = cards_drawn({*canvas.surfaces, *session.held})

    def next_card() -> str:
        return f"voice-{drawings + 1}"

    system = build_system_prompt(
        surface="inline",
        surface_id="voice",
        trip=trip,
        today=today,
        on_screen=canvas.surfaces,
        draws="tools",
    )

    genai = session.client or Client(api_key=session.api_key)
    #: Whether the turn in flight has already been handed back once. Outside
    #: the turn loop, because the turn that answers a nudge is a new receive().
    nudged = False
    #: Messages for the model that arrived while it was mid-turn: one message
    #: per turn, so a press during a turn is not answered twice.
    waiting: list[str] = []
    in_flight: float | None = None
    panel_lock = asyncio.Lock()

    async def keep_current() -> None:
        """The trip, and every surface's bound data, after anything changed."""
        nonlocal places, currency
        if trip.get("destination"):
            places, currency = await places_and_currency(session.provider, trip)
            trip["currency"] = currency
        await announce({"type": "trip", "trip": dict(trip)})
        for event in ui_events(canvas.provide(values), done=True):
            await announce(event)

    async def panel_if_missing() -> None:
        """The first panel, drawn through the Interactions API so it is not spoken."""
        if "sidebar" in canvas.surfaces or not trip.get("destination"):
            return
        async with panel_lock:
            if "sidebar" in canvas.surfaces:
                return
            async for event in draw_panel(session.api_key, session.client, canvas, trip, today, values):
                await announce(event)

    try:
        async with genai.aio.live.connect(
            model=voice_model,
            config=setup_config(system, session.voice, resume=session.resume),
        ) as live:
            # Sent once the session is really open, not when the setup frame
            # was written: a rejected key or model gets that far.
            await announce({"type": "ready", "model": voice_model, "contract": session.contract})

            async def tell_model(text: str) -> None:
                """One user turn for the model, now or once its turn is over."""
                nonlocal in_flight
                if in_flight is not None and loop.time() - in_flight < _WAIT_FOR_TURN_SECONDS:
                    waiting.append(text)
                    return
                in_flight = loop.time()
                await live.send_client_content(
                    turns={"role": "user", "parts": [{"text": text}]},
                    turn_complete=True,
                )

            async def turn_over() -> None:
                nonlocal in_flight
                in_flight = None
                this_turn.clear()
                canvas.this_turn.clear()
                await panel_if_missing()
                if waiting:
                    await tell_model(waiting.pop(0))

            async def handle_press(message: dict[str, Any]) -> None:
                """A press during the call, as v1.0 renderer messages: recorded, then told."""
                renderer = inbound.read(message)
                canvas.negotiate(renderer.capabilities)
                action = renderer.action
                edits = canvas.edits(renderer.data_model, action.surface_id if action else None)
                lines = [f"[renderer] {error.describe()}" for error in renderer.errors]
                if action is not None:
                    recorded = await record_press(action, trip, session.provider, today, edits)
                    trip.clear()
                    trip.update(recorded.trip)
                    lines.insert(0, describe_action(action, recorded.leg))
                    if recorded.notes:
                        lines.append("[interface] Recorded as set. Notes on it: " + " ".join(recorded.notes))
                elif edits:
                    save(model.screen_patch(trip, edits))
                if session.on_trip:
                    session.on_trip(dict(trip))
                await keep_current()
                if lines:
                    await tell_model("\n\n".join(lines))

            async def pump_client() -> None:
                """Microphone bytes, typed text and presses, upstream."""
                async for message in incoming:
                    kind = message.get("type")
                    if kind == "audio":
                        await live.send_realtime_input(
                            audio={"data": message["data"], "mime_type": "audio/pcm;rate=16000"}
                        )
                    elif kind == "audio_end":
                        # The microphone stopped. Without this the model waits
                        # for the silence after speech that never arrives.
                        await live.send_realtime_input(audio_stream_end=True)
                    elif kind == "text" and message.get("text"):
                        await tell_model(str(message["text"]))
                    elif kind == "press":
                        await handle_press(message)
                    elif kind == "end":
                        break

            async def pump_live() -> None:
                # `receive()` is one turn, not the session, so turns are the
                # outer loop. A turn that yields nothing is a closed session.
                while await _one_turn():
                    pass

            async def _one_turn() -> bool:
                nonlocal drawings, nudged, in_flight
                alive = False
                spoken_this_turn = ""
                called_this_turn = False
                cut_off = False
                async for frame in live.receive():
                    alive = True
                    content = getattr(frame, "server_content", None)
                    # Only the model's own output starts a turn. A setup or
                    # resumption frame is not one, and marking it would queue
                    # the traveller's first message behind a turn that never
                    # comes.
                    if in_flight is None and (content is not None or getattr(frame, "tool_call", None)):
                        in_flight = loop.time()
                    if content is not None:
                        turn = getattr(content, "model_turn", None)
                        for part in getattr(turn, "parts", None) or []:
                            audio = getattr(getattr(part, "inline_data", None), "data", None)
                            if audio:
                                await announce({"type": "audio", "data": _b64(audio)})
                        spoken = getattr(content, "output_transcription", None)
                        if getattr(spoken, "text", None):
                            said = _without_markup(spoken.text)
                            spoken_this_turn += said
                            if said:
                                await announce({"type": "transcript", "text": said, "who": "agent"})
                        heard = getattr(content, "input_transcription", None)
                        if getattr(heard, "text", None):
                            await announce({"type": "transcript", "text": heard.text, "who": "you"})
                        if getattr(content, "interrupted", False):
                            # They spoke over the answer: the browser drops its
                            # queued audio, and a cut-off turn is not nudged.
                            cut_off = True
                            await announce({"type": "interrupted"})
                        if getattr(content, "turn_complete", False):
                            # A turn that promised and did nothing is handed
                            # back once, with what it did.
                            if _promised(spoken_this_turn) and not called_this_turn and not cut_off:
                                if not nudged:
                                    nudged = True
                                    await live.send_client_content(
                                        turns={"role": "user", "parts": [{"text": _NUDGE}]},
                                        turn_complete=True,
                                    )
                                    continue
                            await announce({"type": "turn_end"})
                            spoken_this_turn = ""
                            called_this_turn = False
                            nudged = False
                            await turn_over()

                    calls = getattr(getattr(frame, "tool_call", None), "function_calls", None) or []
                    if calls:
                        called_this_turn = True
                        responses = []
                        changed = False
                        for function in calls:
                            args = dict(getattr(function, "args", None) or {})
                            await announce({"type": "tool", "name": function.name, "input": args})
                            if function.name == RENDER_TOOL["name"]:
                                card = next_card()
                                events, problems = render(str(args.get("express") or ""), canvas, card, values)
                                drew = sorted({event[1] for event in events if event[0] == "ui"})
                                if card in drew:
                                    drawings += 1
                                this_turn.update(drew)
                                for event in events:
                                    if event[0] == "ui":
                                        await announce(
                                            {"type": "ui", "surfaceId": event[1], "messages": event[2], "done": True}
                                        )
                                response: dict[str, Any] = {"shown": bool(drew), "surfaces": drew}
                                if problems:
                                    response["problems"] = problems
                            else:
                                before = dict(trip)
                                result, is_error = await run_tool(function.name, args, context)
                                landed = (
                                    data.file_rows(lookups, function.name, args, result, trip) if not is_error else None
                                )
                                changed = changed or landed is not None or trip != before
                                response = (
                                    {"error": result}
                                    if is_error
                                    else data.without_the_rows(
                                        function.name,
                                        result,
                                        next_card(),
                                        landed[1],
                                        shown=canvas.shows(landed[0]),
                                    )
                                    if landed
                                    else result
                                )
                                if not isinstance(response, dict):
                                    response = {"result": response}
                            responses.append(
                                {"id": getattr(function, "id", None), "name": function.name, "response": response}
                            )
                        # The turn is paused until these land, so they go in one frame.
                        await live.send_tool_response(function_responses=responses)
                        if changed:
                            if session.on_trip:
                                session.on_trip(dict(trip))
                            await keep_current()

                    # A fresh resumption handle, kept rather than announced.
                    update = getattr(frame, "session_resumption_update", None)
                    if update is not None and getattr(update, "resumable", False):
                        handle = getattr(update, "new_handle", None)
                        if handle and handle != session.resume:
                            session.resume = handle
                            if session.on_resume:
                                session.on_resume(handle)

                    if getattr(frame, "go_away", None):
                        # Google's session reached its time limit. With a
                        # handle, the next connection picks the conversation up.
                        if not session.resume:
                            await announce(
                                {
                                    "type": "error",
                                    "message": "The Live session is closing — start another when ready.",
                                }
                            )
                        return False
                return alive

            # Either side ending ends the call.
            await _race(asyncio, pump_client(), pump_live())

    except Exception as error:  # noqa: BLE001 - every failure reaches the caller
        await announce({"type": "error", "message": _describe_live_error(error)})
    finally:
        await announce({"type": "turn_end"})


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
    r"</?a2ui>|^\s*(?:surface\s*\(|\$/[\w/]+\s*=|\w+\s*=\s*[A-Z]\w*\s*\()"
    # …or a component tag.
    r"|<\s*[A-Z][A-Za-z0-9]*(?:\s|/?>)",
    re.MULTILINE,
)


def _without_markup(text: str) -> str:
    """What is left of a spoken line once interface code is taken out of it.

    A Live session answers in audio, so the model's text *is* its speech. A turn
    that writes Express writes it into the transcript and says it out loud —
    "less than a2ui greater than, surface, open paren, quote, voice dash one" —
    which is the worst thing this app can do to somebody who is listening.

    The prompt is what stops it (see `SPOKEN_DRAWING`); this keeps the written
    record clean when it does not. Nothing found here is drawn: a half-spoken
    fragment is not a block.
    """
    found = _MARKUP.search(text)
    if not found:
        return text
    # Truncated at the first tag: nothing after it is speech.
    return text[: found.start()].strip()


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
    # Over the project's spending cap, the Live API closes with "1011 None.
    # Your project has exceeded its monthly spending cap...": Google's sentence
    # says where to raise it, and waiting will not help.
    if "spend" in lowered:
        return text[text.lower().find("your project") :].strip() if "your project" in lowered else text
    if "quota" in lowered or "429" in text:
        return "That key has hit its Live API quota. Try again shortly."
    # A model this key cannot see is the failure the raw message explains
    # worst: the SDK says NOT_FOUND, which reads as a bug in this app rather
    # than as a name that is wrong for this key — an override pointing at a
    # withdrawn preview, or a key on a plan the model has not reached. Naming
    # the model and where to change it turns an outage into a setting.
    if "not_found" in lowered or "404" in text or "was not found" in lowered:
        return (
            f"The Live model “{VOICE_MODEL}” is not available to that key — set "
            "VOICE_MODEL on the server to one that serves the Live API."
        )
    if "not supported" in lowered or "unsupported" in lowered:
        return (
            f"The Live API refused “{VOICE_MODEL}”: {text}. Set VOICE_MODEL on the "
            "server to a model that supports the Live API."
        )
    return text or "The Live session failed to open."
