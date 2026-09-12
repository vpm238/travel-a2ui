"""The model, through the Interactions API.

The Worker hand-rolls this: an SSE reader, a line splitter, a dispatch over
`event_type` strings, and a buffer per step for tool arguments that arrive as
partial JSON. About 200 lines, and three of its bugs were in the parsing rather
than in the agent.

Here the SDK does it. `client.aio.interactions.create(stream=True)` yields typed
events, so what is left is the part that is actually this app's: turning a
stream of steps into one result the agent loop can act on.

Two things the SDK does not decide, which cost real bugs the first time and are
kept in comments where they were learned:

  **A tool call's arguments are not whole until the step stops.** They arrive
  as partial JSON across several deltas, and some calls arrive complete in
  `step.start` instead. Seeding the buffer from `step.start` unconditionally
  produced `{}{"destination":"Madrid"}` — which parses as nothing, so every
  tool in the app was called with no arguments and nobody noticed, because a
  tool called with no arguments politely asks for more information.

  **Usage is reported in two incompatible ways.** A plain model turn reports
  the interaction's total on `interaction.completed` and nothing per step; a
  managed agent reports per step and not at all at the end. Adding both
  double-counts; reading only `step.stop` shows every model turn costing zero.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Sequence

from google.genai import Client


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    thought_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "cacheReadTokens": self.cached_tokens,
            # Gemini caches implicitly: there is no write to pay for, and
            # reporting one would invent a cost that does not exist.
            "cacheWriteTokens": 0,
            "thoughtTokens": self.thought_tokens,
        }


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class InteractionResult:
    interaction_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""
    usage: Usage = field(default_factory=Usage)
    status: str | None = None
    #: The model that actually answered, when it is not the one that was asked
    #: for. Set only on a fallback, so a caller can say so rather than quietly
    #: reporting a model that was busy.
    served_by: str | None = None


class GeminiError(Exception):
    """An API failure in words the traveller can act on.

    "401" is not a message; "that key was rejected" is. Because the key comes
    from the person sitting in front of the app, auth failures are the most
    likely error here and deserve the clearest wording — which is why the
    sentence is built at the point of failure rather than reconstructed from a
    status code at the far end.
    """

    def __init__(self, message: str, status: int = 500, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def _describe(status: int, detail: str) -> GeminiError:
    if status in (401, 403):
        return GeminiError(
            "That API key was rejected. Check it is a Gemini key with the "
            "Interactions API enabled.",
            status,
            False,
        )
    if status == 429:
        return GeminiError(
            "That key has hit its rate limit. Wait a moment and try again.", status, True
        )
    if status == 404:
        return GeminiError(
            "That model is not available to this key. Try another model.", status, False
        )
    if status >= 500:
        # Google's own words, kept. "Gemini had a problem" was all this said,
        # and a turn that dies with a sentence carrying no information is a bug
        # report nobody can write — it took a tracing harness to find out that
        # one model was failing mid-stream and another was not.
        said = detail.strip()
        return GeminiError(
            f"Gemini had a problem. Worth trying again. ({said[:300]})"
            if said
            else "Gemini had a problem. Worth trying again.",
            status,
            True,
        )
    return GeminiError(detail or f"Gemini returned {status}.", status, False)


def _as_dict(value: Any) -> dict[str, Any]:
    """A pydantic event, a TypedDict or a plain dict, as a plain dict.

    The SDK's union is `lenient`, so an event type it does not know arrives as
    `UnknownInteractionSSEEvent` with the raw payload on it. Reading through a
    dict rather than through attributes means a new step type upstream degrades
    to "ignored" rather than to an exception mid-turn.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    return dict(getattr(value, "__dict__", {}) or {})


def _read_usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(raw.get("total_input_tokens") or 0),
        output_tokens=int(raw.get("total_output_tokens") or 0),
        cached_tokens=int(raw.get("total_cached_tokens") or 0),
        thought_tokens=int(raw.get("total_thought_tokens") or 0),
    )


def _parse_args(raw: str) -> dict[str, Any]:
    """Streamed tool arguments, which are only valid JSON once complete."""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


#: What `generation_config.thinking_level` accepts, cheapest first.
#:
#: `minimal` was missing here and it is the one that matters: a turn asked for
#: `low` still spent 3,316 thought tokens — about thirteen seconds — deciding
#: how to draw a form it draws every time.
THINKING_LEVELS = ("minimal", "low", "medium", "high")


def supported_level(model: str, level: str | None) -> str | None:
    """The requested thinking level, or the cheapest one this model has.

    Measured, because the API's answer and the model's answer are different
    questions. `generation_config.thinking_level` accepts four values; ask
    `gemini-3.8-flash` for the cheapest of them and the whole turn dies with

        400 'minimal' is not a supported thinking level for this model.
        Allowed values are: medium, low, high.

    while every Flash Lite takes it. So a level this model does not have is
    raised to the cheapest one it does rather than sent and refused — a default
    that gets faster where it can is worth having, and a default that 400s
    somebody's turn is not.
    """
    if level not in THINKING_LEVELS:
        return None
    if level == "minimal" and "lite" not in model.lower():
        return "low"
    return level


def build_body(
    *,
    model: str,
    input: Sequence[dict[str, Any]],
    system_instruction: str | None = None,
    tools: Sequence[dict[str, Any]] | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
) -> dict[str, Any]:
    """The request, as the Interactions API wants it.

    Split out from the call so a test can assert what is sent without a network
    or a key — which is the only way to check that `previous_interaction_id` is
    threaded, and threading it is the difference between a tenth turn sending
    one message and re-uploading nine.
    """
    body: dict[str, Any] = {"model": model, "input": list(input), "stream": True}
    if system_instruction:
        body["system_instruction"] = system_instruction
    if tools:
        body["tools"] = list(tools)
    if thinking_level:
        # Rejected outright by the API if it is not one of these — a 400 that
        # kills the whole turn for a typo in a query string. The four are what
        # `generation_config.thinking_level` accepts; anything else is dropped
        # and the model's own default applies.
        level = supported_level(model, thinking_level)
        if level:
            body["generation_config"] = {"thinking_level": level}
    if previous_interaction_id:
        body["previous_interaction_id"] = previous_interaction_id
    return body


async def stream_interaction(
    *,
    api_key: str,
    model: str,
    input: Sequence[dict[str, Any]],
    system_instruction: str | None = None,
    tools: Sequence[dict[str, Any]] | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    #: Where to go when the model asked for is busy. See `_open`.
    fallback_model: str | None = None,
    client: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """One model turn, streamed.

    An async generator rather than a function taking an `on_text` callback, and
    the difference is not stylistic. The caller is itself a generator feeding an
    SSE response, and a callback cannot yield — so a callback-shaped version has
    to buffer every delta until the model turn ends and emit them all at once,
    which is exactly the "screen stays empty, then everything lands" behaviour
    the streaming exists to avoid.

    Yields `{"type": "text", "delta": ...}` as prose arrives, then exactly one
    `{"type": "result", "result": InteractionResult}` last.

    `client` is injectable so a test can drive the whole loop off a scripted
    stream. Nothing else about this function knows it is being tested.
    """
    genai = client or Client(api_key=api_key)
    body = build_body(
        model=model,
        input=input,
        system_instruction=system_instruction,
        tools=tools,
        thinking_level=thinking_level,
        previous_interaction_id=previous_interaction_id,
    )

    result = InteractionResult()
    # Steps are addressed by index, and a tool call's arguments arrive across
    # several deltas as partial JSON — whole only once the step stops.
    open_steps: dict[int, dict[str, str]] = {}

    stream, served_by = await _open(genai, body, model, fallback_model)
    if served_by:
        result.served_by = served_by
        yield {"type": "served_by", "model": served_by}

    async for event in stream:
        raw = _as_dict(event)
        kind = str(raw.get("event_type") or "")
        index = raw.get("index")
        index = index if isinstance(index, int) else 0

        if kind in ("interaction.created", "interaction.completed"):
            interaction = _as_dict(raw.get("interaction"))
            if isinstance(interaction.get("id"), str):
                result.interaction_id = interaction["id"]
            if isinstance(interaction.get("status"), str):
                result.status = interaction["status"]
            # A plain model turn reports usage *only* here, and reports the
            # whole interaction's total — so this replaces the per-step tally
            # rather than adding to it.
            if interaction.get("usage"):
                result.usage = _read_usage(_as_dict(interaction["usage"]))

        elif kind == "step.start":
            step = _as_dict(raw.get("step"))
            if step.get("type") == "function_call":
                # Some calls arrive whole rather than streamed — but the
                # streamed ones open with `arguments: {}`, which is truthy.
                # Only a non-empty object is a whole call; seeding from an
                # empty one and appending the real deltas gives `{}{"a":1}`,
                # which parses as nothing at all.
                whole = _as_dict(step.get("arguments"))
                open_steps[index] = {
                    "id": str(step.get("id") or f"call_{index}"),
                    "name": str(step.get("name") or ""),
                    "args": json.dumps(whole) if whole else "",
                }

        elif kind == "step.delta":
            delta = _as_dict(raw.get("delta"))
            delta_type = str(delta.get("type") or "")
            if delta_type == "text" and isinstance(delta.get("text"), str):
                result.text += delta["text"]
                yield {"type": "text", "delta": delta["text"]}
            elif delta_type in ("arguments_delta", "arguments"):
                chunk = delta.get("arguments")
                if chunk is None:
                    chunk = delta.get("partial_arguments")
                if isinstance(chunk, str):
                    step = open_steps.setdefault(
                        index, {"id": f"call_{index}", "name": "", "args": ""}
                    )
                    step["args"] += chunk

        elif kind == "step.stop":
            # `step_usage` is this step; the sibling `usage` is the running
            # total, so adding both would double-count. A managed agent reports
            # here and a plain model does not, which is why this is a tally and
            # `interaction.completed` is allowed to replace it.
            if raw.get("step_usage"):
                step_usage = _read_usage(_as_dict(raw["step_usage"]))
                result.usage.input_tokens += step_usage.input_tokens
                result.usage.output_tokens += step_usage.output_tokens
                result.usage.cached_tokens += step_usage.cached_tokens
                result.usage.thought_tokens += step_usage.thought_tokens

            step = open_steps.get(index)
            if step and step["name"]:
                del open_steps[index]
                result.tool_calls.append(
                    ToolCall(id=step["id"], name=step["name"], args=_parse_args(step["args"]))
                )

        elif kind == "error":
            error = _as_dict(raw.get("error"))
            # `code` is not always a number. A mid-stream failure carries
            # `"code": "api_error"`, and `int()` on that raised a ValueError
            # *inside the raise* — so the exception that surfaced was
            # "invalid literal for int() with base 10: 'api_error'" and Google's
            # actual message was thrown away. Every mid-stream failure this app
            # has ever had was reported as a bug in this line.
            code = error.get("code")
            try:
                status = int(code)
            except (TypeError, ValueError):
                status = 500
            raise GeminiError(
                str(error.get("message") or "The model reported an error mid-stream."),
                status,
                True,
            )

    # A stream that ends without `step.stop` still owes us its calls; dropping
    # them would end the turn silently having done nothing.
    for step in open_steps.values():
        if step["name"]:
            result.tool_calls.append(
                ToolCall(id=step["id"], name=step["name"], args=_parse_args(step["args"]))
            )

    yield {"type": "result", "result": result}


#: How long to wait before trying a busy model again, in seconds.
#:
#: Two attempts, not ten. "Currently experiencing high demand" is a capacity
#: spike on Google's side, and it either clears in a couple of seconds or it is
#: lasting minutes — measured, it lasted minutes. A retry loop long enough to
#: outlast one of those is a traveller watching a spinner for a minute, which is
#: worse than an answer from a smaller model.
_BACKOFF = (1.5, 4.0)


async def _open(
    genai: Any, body: dict[str, Any], model: str, fallback_model: str | None
) -> tuple[Any, str | None]:
    """The stream, from the model asked for or from one that is actually up.

    A demo dies differently from a product. A product can return 503 and let the
    caller decide; a demo has one traveller in front of it, halfway through
    planning a trip, and "the model is busy" ends the conversation.

    So: two attempts at what was asked for, then — if the deployment named a
    fallback — the same turn on that instead, and the caller is told which model
    answered so it can say so on screen. Only for failures that are about
    capacity. A rejected key, a bad request or a model that does not exist are
    not going to go better on a second model, and pretending otherwise turns one
    clear error into three confusing ones.

    Measured, and the reason this exists: twelve of thirty-six eval turns on
    Flash 3.8 came back with no surface at all, every one of them "currently
    experiencing high demand". Not a wrong component, not a compile failure —
    the model was simply not there. Every turn that *ran* drew the right thing.
    """
    attempts = len(_BACKOFF) + 1
    last: GeminiError | None = None

    for attempt in range(attempts):
        try:
            return await genai.aio.interactions.create(**body), None
        except Exception as error:  # noqa: BLE001 - every failure gets a sentence
            described = _from_sdk_error(error)
            if not described.retryable:
                raise described from error
            last = described
            if attempt < len(_BACKOFF):
                await asyncio.sleep(_BACKOFF[attempt])

    if fallback_model and fallback_model != model:
        try:
            return await genai.aio.interactions.create(
                **{**body, "model": fallback_model}
            ), fallback_model
        except Exception as error:  # noqa: BLE001
            raise _from_sdk_error(error) from error

    raise last or GeminiError("The model did not answer.", 503, True)


def _from_sdk_error(error: Exception) -> GeminiError:
    """An SDK exception, turned into one of ours.

    Matched on the status code the SDK carries rather than on the class, so a
    rename upstream degrades to the generic message instead of to a crash.
    """
    if isinstance(error, GeminiError):
        return error
    status = (
        getattr(error, "status_code", None)
        or getattr(error, "code", None)
        or getattr(getattr(error, "response", None), "status_code", None)
    )
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 500
    return _describe(status, str(error))


def describe_api_error(error: Exception) -> dict[str, Any]:
    """The error, as the event the browser renders."""
    if isinstance(error, GeminiError):
        return {"type": "error", "message": str(error), "retryable": error.retryable}
    if isinstance(error, (TimeoutError, __import__("asyncio").CancelledError)):
        return {"type": "error", "message": "Stopped.", "retryable": False}
    described = _from_sdk_error(error)
    return {"type": "error", "message": str(described), "retryable": described.retryable}
