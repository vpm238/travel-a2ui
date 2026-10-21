"""The warm-up: start the conversation before anybody has said anything.

A turn that resumes an existing conversation is much cheaper than one that does
not, because the stable half of the prompt — the role, the catalog, the
component signatures — is already in it. So the client opens one as soon as the
page loads, with a message written to be dispatched in a word and then ignored.

Nothing is drawn and nothing is looked up. What comes back is the interaction id
the first real turn resumes from, and the stamp of the rules it was started
with.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from ...brain import trip as model
from ...brain.catalog import CATALOG_ID
from ...brain.skills import build_prompt_parts
from ...gemini import stream_interaction, supported_level
from ..settings import DEFAULT_MODEL, FALLBACK_MODEL, _today


#: What the warm-up says. Nothing is drawn and nothing is looked up.
#:
#: It does enter the conversation, because that is the entire point — the
#: conversation has to exist for the next turn to resume it — so it is written
#: to be a turn the model can dispatch in one word and then ignore.
WARM_INPUT = (
    "(System warm-up. Do not draw anything, do not call any tool, do not plan "
    "anything. Reply with the single word: ready.)"
)


@dataclass
class WarmRequest:
    """Enough to start a conversation, and nothing about a trip."""

    api_key: str
    skill: str = "express-modular"
    model: str = DEFAULT_MODEL
    client: Any | None = None


async def warm(request: WarmRequest) -> dict[str, Any]:
    """Start the conversation before the traveller has said anything.

    The first interface takes about eight times longer than every one after it,
    and the reason is not the agent thinking harder — it is the system
    instruction. The Interactions API is stateful, so the fifteen thousand
    tokens of role, flow, journey, inventory, controls and catalog go up once
    when a conversation starts and never again. Measured, same ask, same model
    (`tools/eval/latency.py`):

        cold     firstWord 5.3s   firstSurface 19.6s   done 29.4s
        second   firstWord 1.8s   firstSurface  2.4s   done 15.0s
        warmed   firstWord 5.2s   firstSurface 11.6s   done 13.5s

    So this pays that cost early, against a throwaway turn, and hands back the
    receipt. The traveller's first message is then a *second* turn: it sends the
    volatile half and forty-odd tokens rather than five thousand.

    Only the stable half exists at this point, which is the reason this is
    possible at all — `build_prompt_parts` splits the prompt by what varies, and
    the stable half depends on the skill variant alone. No surface, no trip, no
    date is baked in here, so nothing about the warmed conversation is stale by
    the time somebody types.

    It returns rather than streams: there is no interface coming and nobody
    waiting to see one. A failure is reported and not raised — a warm-up that
    did not happen costs the first turn its head start and nothing else.
    """
    began = time.perf_counter()
    stable, _ = build_prompt_parts(
        variant=request.skill,
        # Placeholders. None of these reach the stable half; they are here
        # because the function needs a whole trip's worth of arguments to
        # compute the volatile one, which is thrown away.
        surface="inline",
        surface_id="inline-1",
        catalog_id=CATALOG_ID,
        trip={},
        today=_today(None),
    )
    setup = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]

    interaction_id: str | None = None
    error: str | None = None
    try:
        async for event in stream_interaction(
            api_key=request.api_key,
            model=request.model,
            input=[{"type": "user_input", "content": [{"type": "text", "text": WARM_INPUT}]}],
            system_instruction=stable,
            # No tools on purpose. A warm-up that can call something is a
            # warm-up that might, and a `search_flights` for a trip nobody has
            # described is the opposite of fast.
            thinking_level=supported_level(request.model, "minimal"),
            fallback_model=FALLBACK_MODEL,
            client=request.client,
        ):
            if event["type"] == "result":
                interaction_id = event["result"].interaction_id
    except Exception as problem:  # noqa: BLE001 - a cold first turn, not a failure
        error = str(problem)[:200]

    return {
        "interactionId": interaction_id,
        "setup": setup,
        "ms": round((time.perf_counter() - began) * 1000, 1),
        **({"error": error} if error else {}),
    }
