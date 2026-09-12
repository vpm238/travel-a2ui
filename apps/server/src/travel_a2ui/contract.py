"""What a Gemini Live session would be bound to right now.

The Interactions API has an agent object on the server, so a conversation that
outlives a deploy is the server's problem. The Live API has none: a session is
set up from whatever the client sends at connect time, and a client that
remembered "I instantiated successfully" has no way to find out that the thing
it instantiated *against* was replaced last night.

So the server publishes a stamp over everything a Live session is composed
from, and a stored instantiation carries the stamp it was made under. Change
the catalog, the skill, the tools or the model and the stamp moves; every
stored instantiation goes stale on its next look and the traveller is asked to
instantiate again. Which is a small annoyance, and much smaller than a voice
agent composing confidently against a catalog that no longer exists.

The age limit is the same idea for the case the stamp cannot catch: nothing
changed, but the session is a day old and the key behind it may not be good any
more.
"""

from __future__ import annotations

import json

from .agent import CATALOG_JSON
from .skills import skill_text
from .voice import VOICE_MODEL  # re-exported: callers ask the contract what it stamps

#: How long an instantiation is good for, stamp unchanged.
INSTANTIATION_MAX_AGE_MS = 24 * 60 * 60 * 1000


def fingerprint(text: str) -> str:
    """FNV-1a, 32-bit, with the length appended.

    Not a security hash and not trying to be: the job is that a different input
    almost certainly produces a different string, cheaply, in two languages that
    have to agree. The length suffix is there because a 32-bit digest collides
    more often than people expect, and two catalogs of different sizes should
    never stamp the same however unlucky the hash is.

    The masking is deliberate rather than incidental. JavaScript's `Math.imul`
    is a 32-bit multiply and Python's `*` is not, so without `& 0xFFFFFFFF` the
    two implementations agree for a few characters and then diverge silently.
    """
    hash_value = 0x811C9DC5
    for char in text:
        hash_value ^= ord(char)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    digest = f"{hash_value:08x}"
    # `toString(36)` for the length, to match the TypeScript exactly.
    length = _base36(len(text))
    return f"{digest}{length}"


def _base36(value: int) -> str:
    if value == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while value:
        value, remainder = divmod(value, 36)
        out = digits[remainder] + out
    return out


_cached: str | None = None


def contract_stamp() -> str:
    """The stamp for what a Live session would be set up with right now."""
    global _cached
    if _cached is not None:
        return _cached

    from .voice import VOICE_MODEL, voice_tools

    parts = [
        # `separators` and `ensure_ascii` matter: this has to be the same bytes
        # the TypeScript's `JSON.stringify` produces, or the two servers stamp
        # the same catalog differently and every instantiation made against one
        # is stale on the other.
        json.dumps(CATALOG_JSON, separators=(",", ":"), ensure_ascii=False),
        # The voice relay builds its prompt from this variant, so these are the
        # instructions that actually reach a Live session.
        skill_text("express-monolithic"),
        json.dumps(voice_tools(), separators=(",", ":"), ensure_ascii=False),
        VOICE_MODEL,
    ]
    _cached = fingerprint("".join(parts))
    return _cached
