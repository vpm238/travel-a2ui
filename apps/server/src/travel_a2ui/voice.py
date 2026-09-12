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
import pathlib
from typing import Any

from .tools import gemini_tools

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_MCP = json.loads((_ROOT / "data" / "mcp-tools.json").read_text("utf-8"))

MCP_TOOLS: list[dict[str, Any]] = _MCP["tools"]
A2UI_MIME: str = _MCP["a2uiMimeType"]


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
