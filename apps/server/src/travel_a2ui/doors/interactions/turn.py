"""One turn of the conversation: ask the model, send what it draws.

In order:

  1. Record what the traveller did: the press, and whatever they changed on
     screen (`Canvas.edits`). Both are facts, recorded before the model hears
     of them.
  2. Send the surfaces the new data they bind (`Canvas.provide`), so the panel
     moves the moment a decision lands.
  3. Ask the model, streaming. Its prose and its `<a2ui>` blocks are read by
     the A2UI SDK processor (`brain/ui.py`): each block is validated against
     what the renderer already holds, its macros expanded, and sent.
  4. When it calls a tool, run it. A lookup's rows go into the data model of
     this turn's surface, where a macro the model drew is already bound.
  5. Tell the model, once each, about a block that was refused, a surface that
     cannot be answered as drawn, or a promise with nothing drawn.
  6. Hand back the receipt, then, if there is no panel yet, ask for one.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, AsyncIterator, Iterable

from ...brain import data
from ...brain import trip as model
from ...brain.promises import TYPED_NUDGE, promised
from ...brain.providers.fixture import FixtureProvider
from ...brain.skills import build_prompt_parts
from ...brain.tools import ToolContext, gemini_tools, grounding_tools, run_tool
from ...brain.ui import Canvas, Drawing, surface_of
from ...gemini import describe_api_error, stream_interaction
from ..settings import FALLBACK_MODEL, MAX_TOOL_ROUNDS, _today
from .panels import draw_panel
from .press import TurnRequest, TurnResult, describe_action, record_press


def ui_events(messages: Iterable[dict[str, Any]], done: bool = False) -> list[dict[str, Any]]:
    """A2UI messages as transport events, one per surface, in order."""
    out: list[dict[str, Any]] = []
    for message in messages:
        surface_id = surface_of(message)
        if out and out[-1]["surfaceId"] == surface_id:
            out[-1]["messages"].append(message)
        else:
            out.append({"type": "ui", "surfaceId": surface_id, "messages": [message], "done": done})
    return out


async def places_and_currency(provider: Any, trip: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The airports this deployment flies, and the trip's currency."""
    try:
        destinations = await provider.destinations()
        places = data.places_rows(await provider.origins(), destinations)
        return places, data.currency_for(destinations, trip)
    except Exception:  # noqa: BLE001 - a picker with no options is not a dead turn
        return {"origins": [], "destinations": []}, "USD"


def _say(text: str) -> dict[str, Any]:
    return {"type": "user_input", "content": [{"type": "text", "text": text}]}


async def run_turn(request: TurnRequest) -> AsyncIterator[dict[str, Any]]:
    """Runs one turn, yielding transport events as they happen."""
    today = _today(request.client_hints)
    provider = request.provider or FixtureProvider()
    canvas: Canvas = request.canvas

    # 1. What the traveller did.
    action = request.action
    edits = canvas.edits(request.data_model, action.surface_id if action else None)
    if action is not None:
        recorded = await record_press(action, request.trip, provider, today, edits)
        trip, notes, leg = recorded.trip, recorded.notes, recorded.leg
    else:
        from_screen = model.screen_patch(request.trip, edits)
        trip = {**request.trip, **from_screen}
        notes = [problem["message"] for problem in model.problems(trip, today)] if from_screen else []
        if from_screen:
            trip = model.confirm(trip, list(from_screen))
        leg = None

    places, currency = await places_and_currency(provider, trip)
    trip["currency"] = currency
    lookups = canvas.lookups
    canvas.this_turn = set()

    def values(surface_id: str) -> dict[str, Any]:
        out = data.session_values(trip, places)
        # This turn's lookup rows go to the cards this turn draws or updates.
        if surface_id == request.surface_id or surface_id in canvas.this_turn:
            out.update(data.turn_values(lookups, trip))
        return out

    # 2. The surfaces on screen catch up with the record.
    for event in ui_events(canvas.provide(values), done=True):
        yield event

    def save(patch: dict[str, Any]) -> None:
        merged = model.merge(trip, patch)
        trip.clear()
        trip.update(merged)

    tool_context = ToolContext(trip=trip, provider=provider, save=save, today=today)

    lines = [request.message or (describe_action(action, leg) if action else "")]
    if notes:
        lines.append(f"[interface] Recorded as set. Notes on it: {' '.join(notes)}")
    for error in request.errors:
        lines.append(f"[renderer] The renderer reported an error: {error.describe()}")
    opening = "\n\n".join(line for line in lines if line) or "Continue."

    yield {"type": "start", "model": request.model, "surfaceId": request.surface_id}

    began = time.perf_counter()
    marks: dict[str, float] = {}

    def mark(name: str) -> bool:
        if name in marks:
            return False
        marks[name] = round((time.perf_counter() - began) * 1000, 1)
        return True

    stable, volatile = build_prompt_parts(
        surface=request.surface,
        surface_id=request.surface_id,
        trip=trip,
        today=today,
        on_screen=canvas.surfaces,
    )
    setup = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    previous_interaction_id = request.interaction_id
    if request.setup and request.setup != setup:
        previous_interaction_id = None

    # Each round sends the whole turn so far, so a round never depends on the
    # API having kept the one before it. The previous turn is the only state
    # resumed from the server.
    history: list[dict[str, Any]] = [_say(f"{volatile}\n\n---\n\n{opening}")]
    last_interaction_id = previous_interaction_id
    stop_reason: str | None = None
    told = {"rejected": False, "advice": False, "promise": False}
    spoken = ""
    drew = False
    dispatched = False
    #: Surfaces drawn in earlier rounds of this turn, which are on screen now.
    drawn_this_turn: list[str] = []

    for round_index in range(MAX_TOOL_ROUNDS):
        drawing = Drawing(canvas, request.surface_id, values)
        rejected: tuple[str, str] | None = None
        advice: list[str] = []

        def read(events: list[tuple]) -> list[dict[str, Any]]:
            nonlocal rejected, spoken, drew
            out: list[dict[str, Any]] = []
            for event in events:
                kind = event[0]
                if kind == "text":
                    spoken += event[1]
                    mark("firstWord")
                    out.append({"type": "text", "delta": event[1], "round": round_index})
                elif kind == "ui":
                    drew = True
                    if mark("firstSurface"):
                        out.append({"type": "timing", "ms": dict(marks)})
                    out.extend(ui_events(event[2], done=not drawing.stream.is_in_block))
                elif kind == "rejected":
                    rejected = rejected or (event[1], event[2])
                    out.append({"type": "ui_error", "message": event[1], "express": event[2], "source": "stream"})
                elif kind == "advice":
                    advice.append(event[1])
            return out

        result = None
        failure: Exception | None = None
        try:
            async for event in stream_interaction(
                api_key=request.api_key,
                model=request.model,
                input=list(history),
                tools=[*gemini_tools(), *grounding_tools()],
                system_instruction=stable,
                thinking_level=request.effort,
                previous_interaction_id=previous_interaction_id,
                fallback_model=FALLBACK_MODEL,
                # A dropped stream may restart only while nothing has reached
                # the screen and no tool is waiting on its result.
                has_drawn=lambda: bool(drawing.drawn) or dispatched,
                client=request.client,
            ):
                if event["type"] == "text":
                    for out in read(drawing.feed(event["delta"])):
                        yield out
                elif event["type"] == "restart":
                    drawing = Drawing(canvas, request.surface_id, values)
                    spoken = ""
                    yield event
                elif event["type"] == "served_by":
                    yield event
                elif event["type"] == "result":
                    result = event["result"]
        except Exception as error:  # noqa: BLE001 - every failure gets a sentence
            failure = error

        # What arrived before a failure is still on screen and still usable.
        for out in read(drawing.close()):
            yield out

        if failure is not None:
            reported = describe_api_error(failure)
            if drew and reported.get("retryable"):
                reported = {
                    **reported,
                    "message": (
                        "The model dropped out part-way through this turn; what it had "
                        f"already drawn still works. ({reported.get('message', '')})"
                    ),
                }
            yield reported
            break
        if result is None:
            yield {"type": "error", "message": "The model stream ended without a result.", "retryable": True}
            break

        last_interaction_id = result.interaction_id or last_interaction_id
        stop_reason = result.status
        yield {"type": "usage", **result.usage.as_dict()}

        corrections: list[str] = []
        if rejected and not told["rejected"]:
            told["rejected"] = True
            yield {"type": "retry", "reason": rejected[0]}
            corrections.append(
                "That A2UI block was refused, so it was not drawn:\n\n"
                f"{rejected[0]}\n\nThe block was:\n\n{rejected[1][:4000]}\n\n"
                "Write the block again, corrected. Do not repeat the prose."
            )
        if advice and not told["advice"]:
            told["advice"] = True
            yield {"type": "retry", "reason": "a surface cannot be answered as drawn"}
            corrections.append(
                "Drawn, but it cannot be answered as it stands:\n\n"
                + "\n".join(f"- {note}" for note in advice)
                + "\n\nFix it with an update to that surface. Only the <a2ui> block."
            )
        if not result.tool_calls and not corrections and not drew and promised(spoken) and not told["promise"]:
            told["promise"] = True
            yield {"type": "retry", "reason": "the turn promised and drew nothing"}
            corrections.append(TYPED_NUDGE)

        if not result.tool_calls:
            if not corrections:
                break
            history.extend(_say(text) for text in corrections)
            continue

        # Every call this round, answered together.
        results: list[dict[str, Any]] = []
        for call in result.tool_calls:
            yield {"type": "tool", "name": call.name, "input": call.args, "status": "running"}
            began_tool = time.perf_counter()
            dispatched = True
            before = json.dumps(trip, sort_keys=True, default=str)
            output, is_error = await run_tool(call.name, call.args, tool_context)
            marks[f"tool:{call.name}"] = round((time.perf_counter() - began_tool) * 1000, 1)
            if trip.get("destination"):
                places, currency = await places_and_currency(provider, trip)
                trip["currency"] = currency
            yield {"type": "tool_result", "name": call.name, "result": output, "isError": is_error}

            landed = data.file_rows(lookups, call.name, call.args, output, trip) if not is_error else None
            if landed is not None or json.dumps(trip, sort_keys=True, default=str) != before:
                for event in ui_events(canvas.provide(values)):
                    yield event

            payload = (
                data.without_the_rows(
                    call.name,
                    output,
                    request.surface_id,
                    landed[1],
                    shown=canvas.shows(landed[0]),
                )
                if landed
                else output
            )
            results.append(
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                payload if isinstance(payload, dict) else {"result": payload},
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                    ],
                }
            )

        history.extend(call.replayable() for call in result.tool_calls)
        history.extend(results)
        drawn_this_turn.extend(sorted(drawing.drawn - set(drawn_this_turn)))
        if drawn_this_turn:
            # Said with the results, because the next round is where the model
            # decides whether to write the block again.
            names = ", ".join(f"`{surface_id}`" for surface_id in drawn_this_turn)
            history.append(
                _say(
                    f"[host] Already on screen from this turn: {names}. They stay, and a card "
                    "bound to the rows above has filled in. Do not create them again; update one "
                    'with surface("id", update=true) only if something on it must change.'
                )
            )
        history.extend(_say(text) for text in corrections)
        yield {"type": "trip", "trip": dict(trip)}

        if round_index == MAX_TOOL_ROUNDS - 1:
            yield {
                "type": "error",
                "message": f"Stopped after {MAX_TOOL_ROUNDS} rounds of tool calls.",
                "retryable": True,
            }

    yield {"type": "trip", "trip": dict(trip)}
    # Handed over before anything else, so a traveller who presses something
    # now (which cancels the rest of this stream) keeps the trip.
    receipt = TurnResult(interaction_id=last_interaction_id, trip=trip, stop_reason=stop_reason, setup=setup)
    yield {"type": "__result__", "result": receipt}
    mark("answered")
    yield {"type": "done", "stopReason": stop_reason}

    # 6. No panel yet: ask for one, once there is a trip to show.
    if request.surface == "inline" and "sidebar" not in canvas.surfaces and trip.get("destination"):
        async for event in draw_panel(request.api_key, request.client, canvas, trip, today, values):
            yield event

    mark("done")
    yield {"type": "timing", "ms": dict(marks)}


async def run_turn_collected(request: TurnRequest) -> dict[str, Any]:
    """Every event of a turn, gathered, for a caller with no stream."""
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
        "setup": result.setup if result else request.setup,
        "errors": errors,
    }
