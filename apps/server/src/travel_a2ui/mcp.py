"""The MCP endpoint: these surfaces, inside somebody else's agent.

This is the transport. `surfaces.py` composes the interface; this speaks the
protocol that carries it — JSON-RPC 2.0 over Streamable HTTP, with `initialize`,
`tools/list`, `tools/call`, `resources/*`, `prompts/*`, notification semantics
and error codes. Without it the plugin has nothing to connect to.

**Every tool result carries three things at once**, and that is the whole
design:

    content[0]            a plain-text summary, for a host with no renderer
    content[1]            the A2UI payload under `application/vnd.a2ui+json`,
                          for a host that has its own
    structuredContent     the same messages, where an MCP Apps view reads them

A host that understands none of it still gets the summary and loses nothing but
the pictures. That degradation is deliberate: an MCP tool that is useless in a
plain host is a bad MCP tool.

The piece whose absence once made the plugin render nothing: a host does not
look for HTML *inside* a tool result. It looks for a `ui://` resource with the
MCP Apps MIME type, reads it once as a **template**, and then forwards each tool
result to that template. Returning `text/html` per call produces a resource
nothing is looking for.

Stateless on purpose. Every POST is self-contained, so there is no session to
lose and nothing to clean up — which also means the travel provider has to
arrive with the request rather than being read from somewhere, or an MCP call
would answer from fixtures on a deployment configured for live inventory, and
answer *differently* from the same tool called through the web app.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from dataclasses import dataclass
from typing import Any

from .agent import CATALOG_ID, CATALOG_JSON, _parser
from .providers.types import TravelProvider
from .skills import skill_text
from .surfaces import Surface, build_surface

_ROOT = pathlib.Path(__file__).resolve().parents[4]
_MCP = json.loads((_ROOT / "data" / "mcp-tools.json").read_text("utf-8"))

TOOLS: list[dict[str, Any]] = _MCP["tools"]

#: The MIME type an A2UI payload travels under.
A2UI_MIME: str = _MCP["a2uiMimeType"]

#: Newest first. The server speaks whichever of these the client asked for: a
#: stateless server that announces its own favourite ends up on an older
#: contract than either side wanted.
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]

#: The MCP Apps view, declared once and read once per conversation.
APP_URI = "ui://travel-a2ui/surface"
APP_MIME = "text/html;profile=mcp-app"

#: The capability a host advertises when it can render one.
UI_EXTENSION = "io.modelcontextprotocol/ui"

SERVER_INFO = {"name": "travel-a2ui", "title": "Travel A2UI", "version": "0.1.0"}

INSTRUCTIONS = (
    "These tools return user interfaces, not text. Call one whenever the user is choosing "
    "between options, looking at an itinerary, or asking what a trip costs.\n\n"
    "The `show_*` tools are shortcuts for the six layouts that come up most. The real "
    "capability is composition: call `get_a2ui_component_reference` once to learn the "
    "catalog — flight and hotel cards, itinerary days, maps, price summaries, stat tiles, "
    "sliders, date pickers, checkboxes, layout primitives — then write A2UI Express and "
    "send it to `render_a2ui_express` to build whatever this particular conversation needs. "
    "Prefer that over describing an interface in prose.\n\n"
    "Every result carries three things: a plain-text summary you can read, an A2UI payload "
    f"({A2UI_MIME}) for a host with its own renderer, and an HTML view for one without. "
    "Interactions in the surface come back to you as the user's next turn, so build "
    "surfaces that ask a question and let the user answer by using them.\n\n"
    "Every tool that composes content takes `surface`: `inline` answers the current "
    "message, `sidebar` is a persistent panel of controls, `home` is a standing summary. "
    "It changes what gets composed, not just where it lands."
)

RESOURCES = [
    {
        "uri": "a2ui://catalog/travel",
        "name": "Travel component catalog",
        "title": "A2UI travel catalog",
        "description": (
            "The JSON Schema catalog of every component these tools can render — the "
            "vocabulary available to render_a2ui_express."
        ),
        "mimeType": "application/json",
    },
    {
        "uri": "a2ui://skill/express",
        "name": "A2UI Express skill",
        "title": "How to write A2UI Express",
        "description": (
            "The output contract and every component signature, as the model is taught them."
        ),
        "mimeType": "text/markdown",
    },
]

PROMPTS = [
    {
        "name": "a2ui-express",
        "title": "Write A2UI Express",
        "description": (
            "Loads the A2UI Express output contract and the travel catalog signatures, so you "
            "can compose your own interfaces and render them with render_a2ui_express."
        ),
        "arguments": [],
    }
]


def _soon(days_out: int, today: _dt.date | None = None) -> str:
    """A date far enough ahead to be plausible.

    Computed rather than written down: a literal would have worked until the day
    it went past, and then every example in the console would be a refusal.
    """
    return ((today or _dt.date.today()) + _dt.timedelta(days=days_out)).isoformat()


def tool_examples(today: _dt.date | None = None) -> dict[str, dict[str, Any]]:
    """Arguments that make each tool do something worth looking at.

    Beside the tools rather than in the console that calls them, because they
    are part of describing a tool and a test can then prove they work. They were
    a private table in the web app once, and the headline one omitted the date
    `show_flight_options` requires — so the first button anyone pressed in the
    MCP console answered with a refusal, on the deployed site, for as long as
    that console had existed.
    """
    return {
        "show_flight_options": {
            "destination": "Madrid",
            "origin": "JFK",
            "date": _soon(45, today),
            "endDate": _soon(52, today),
            "travelers": 2,
            "cabin": "economy",
        },
        "show_hotel_options": {"destination": "Madrid", "nights": 6, "maxNightly": 260},
        "show_trip_controls": {"destination": "Madrid", "travelers": 2},
        "show_itinerary": {"destination": "Lisbon", "days": 3},
        "show_trip_dashboard": {
            "destination": "Madrid",
            "nights": 6,
            "travelers": 2,
            "budget": 2600,
            "spent": 1320,
        },
        "show_price_summary": {"destination": "Tokyo", "travelers": 2, "nights": 7},
        "render_a2ui_express": {
            "surfaceId": "mcp-custom",
            "source": (
                'surface("mcp-custom")\n'
                'head = Text("Composed on the fly", variant="h3")\n'
                "root = Column([head])"
            ),
        },
        "get_a2ui_component_reference": {},
    }


def _with_view(tool: dict[str, Any], examples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        **tool,
        "_meta": {
            "ui": {"resourceUri": APP_URI, "visibility": ["model", "app"]},
            "example": examples.get(tool["name"], {}),
        },
    }


def _app_resource(origin: str) -> dict[str, Any]:
    return {
        "uri": APP_URI,
        "name": "travel-surface",
        "title": "Travel A2UI surface",
        "description": (
            "The A2UI renderer these tools draw into — the same React components the web "
            "app uses."
        ),
        "mimeType": APP_MIME,
        "_meta": {
            "ui": {
                "csp": {
                    # Everything is inlined into the template, so the view
                    # fetches nothing and no content policy can break it.
                    "connectDomains": [origin] if origin else [],
                    "resourceDomains": [],
                    "frameDomains": [],
                    "baseUriDomains": [],
                },
                "prefersBorder": True,
            }
        },
    }


@dataclass
class RenderContext:
    """Everything about a request that changes what a tool result looks like."""

    #: `app` (the default, what Claude speaks), `payload` for a host with its
    #: own renderer, `legacy` for the older MCP-UI shape.
    view: str
    #: Absolute origin the view loads the renderer from. No trailing slash.
    origin: str
    provider: TravelProvider
    today: str | None = None


def ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def err(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def tool_error(message: str) -> dict[str, Any]:
    """A tool that could not answer, in the shape a host reads as an outcome.

    `isError` on the result rather than a JSON-RPC error: the *call* worked, and
    what came back is something the model has to act on. A protocol error would
    tell the host the server is broken, which it is not.
    """
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _view_of(requested: str | None) -> str:
    if requested in ("payload", "legacy"):
        return requested
    # `html` and `both` were the old spellings; keep them working rather than
    # breaking an install that is already out there.
    if requested in ("html", "both"):
        return "legacy"
    return "app"


async def handle_rpc(request: dict[str, Any], context: RenderContext) -> dict[str, Any] | None:
    """One JSON-RPC request. Returns None for a notification, which takes no reply."""
    request_id = request.get("id")
    is_notification = "id" not in request
    params = request.get("params") or {}
    method = request.get("method")

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok(
            request_id,
            {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False, "subscribe": False},
                    "prompts": {"listChanged": False},
                    "extensions": {UI_EXTENSION: {"mimeTypes": [APP_MIME]}},
                },
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return ok(request_id, {})

    if method == "tools/list":
        today = _dt.date.fromisoformat(context.today) if context.today else None
        examples = tool_examples(today)
        return ok(request_id, {"tools": [_with_view(tool, examples) for tool in TOOLS]})

    if method == "tools/call":
        return await call_tool(request_id, params, context)

    if method == "resources/list":
        return ok(request_id, {"resources": [_app_resource(context.origin), *RESOURCES]})

    if method == "resources/read":
        return read_resource(request_id, params, context)

    if method == "prompts/list":
        return ok(request_id, {"prompts": PROMPTS})

    if method == "prompts/get":
        if params.get("name") != "a2ui-express":
            return err(request_id, -32602, f"Unknown prompt: {params.get('name')}")
        return ok(
            request_id,
            {
                "description": PROMPTS[0]["description"],
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": _skill_express()},
                    }
                ],
            },
        )

    if is_notification:
        return None
    return err(request_id, -32601, f"Method not found: {method}")


def _skill_express() -> str:
    """The Express skill, body only — what the model is taught."""
    from .skills import _body

    return _body(skill_text("express-monolithic"))


def read_resource(
    request_id: Any, params: dict[str, Any], context: RenderContext
) -> dict[str, Any]:
    uri = params.get("uri")

    if uri == "a2ui://catalog/travel":
        return ok(
            request_id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(CATALOG_JSON, ensure_ascii=False),
                    }
                ]
            },
        )

    if uri == "a2ui://skill/express":
        return ok(
            request_id,
            {
                "contents": [
                    {"uri": uri, "mimeType": "text/markdown", "text": _skill_express()}
                ]
            },
        )

    return err(request_id, -32602, f"Unknown resource: {uri}")


async def call_tool(
    request_id: Any, params: dict[str, Any], context: RenderContext
) -> dict[str, Any]:
    name = params.get("name") or ""
    args = params.get("arguments") or {}

    # Not a surface: this one hands back the vocabulary so the *next* call can
    # compose one. It is what makes the layouts generative rather than a menu.
    if name == "get_a2ui_component_reference":
        return ok(
            request_id,
            {
                "content": [{"type": "text", "text": _skill_express()}],
                "structuredContent": {
                    "catalogId": CATALOG_ID,
                    "version": "v0.9.1",
                    "components": list(CATALOG_JSON.get("components") or {}),
                },
                "isError": False,
            },
        )

    try:
        surface: Surface = await build_surface(name, args, context.provider, context.today)
    except ValueError as error:
        if str(error).startswith("Unknown surface tool"):
            return err(request_id, -32602, f"Unknown tool: {name}")
        return ok(request_id, tool_error(str(error)))
    except Exception as error:  # noqa: BLE001 - a refusal is an outcome, not a fault
        return ok(request_id, tool_error(str(error)))

    try:
        messages = _parser(surface.surface_id).compile(surface.express, is_final=True)
    except Exception as error:  # noqa: BLE001
        # A compile failure is the host model's to fix — it wrote the Express —
        # so say what broke rather than returning something it cannot act on.
        return ok(
            request_id,
            tool_error(f"The A2UI Express did not compile: {error}"),
        )

    content: list[dict[str, Any]] = [{"type": "text", "text": surface.summary}]

    if context.view != "legacy":
        content.append(
            {
                "type": "resource",
                "resource": {
                    "uri": f"ui://a2ui/{surface.surface_id}",
                    "mimeType": A2UI_MIME,
                    "text": json.dumps(messages, ensure_ascii=False),
                },
            }
        )
    else:
        # The older MCP-UI convention: a `text/html` resource per result with
        # the payload already inside it. Opt-in, because a host that speaks MCP
        # Apps has already read the template and would then have two candidate
        # views for one result — and which it picks is not ours to guess.
        content.append(
            {
                "type": "resource",
                "resource": {
                    "uri": f"ui://a2ui/{surface.surface_id}.html",
                    "mimeType": "text/html",
                    "text": render_view(
                        surface.surface_id, messages, surface.summary, context.origin
                    ),
                },
            }
        )

    # `structuredContent` is where an MCP Apps view reads the surface from: the
    # host forwards this result to the template once the handshake is done. Not
    # decoration — without it the view has nothing to draw.
    return ok(
        request_id,
        {
            "content": content,
            "structuredContent": {
                "surfaceId": surface.surface_id,
                "catalogId": CATALOG_ID,
                "messages": messages,
            },
            "_meta": {"ui": {"resourceUri": APP_URI}},
            "isError": False,
        },
    )


def _escape_script(text: str) -> str:
    """The only sequence that can end a `<script>` block early.

    This is the whole of the safety story for the payload, and it is why the
    payload goes into a JSON script block rather than a JS string literal:
    inside `<script type="application/json">` there is exactly one thing to
    escape, and it is this one.
    """
    return text.replace("</script", "<\\/script")


def render_view(
    surface_id: str, messages: list[dict[str, Any]], summary: str, origin: str
) -> str:
    """The legacy per-result HTML view."""
    shell = (_ROOT / "apps" / "mcp-view" / "shell.html").read_text("utf-8")
    payload = _escape_script(
        json.dumps({"surfaceId": surface_id, "messages": messages, "summary": summary},
                   ensure_ascii=False)
    )
    return shell.replace("__ORIGIN__", origin).replace("__A2UI_PAYLOAD__", payload, 1)


def app_template(origin: str) -> str:
    """The MCP Apps template, built from the assets this deployment serves.

    Assembled rather than imported as a build artifact: composing it from the
    files actually being served means the template can never be a stale copy of
    the renderer the rest of the app uses. Everything is inlined, so the view
    fetches nothing — which is why its resource declares `resourceDomains: []`.
    """
    base = _ROOT / "apps" / "web" / "dist" / "mcp-view"
    script = (base / "app.js").read_text("utf-8") if (base / "app.js").is_file() else ""
    style = (base / "app.css").read_text("utf-8") if (base / "app.css").is_file() else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        "<title>A2UI surface</title>\n"
        f"<style>{style}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div id="root"></div>\n'
        f"<script>{_escape_script(script)}</script>\n"
        "</body>\n"
        "</html>\n"
    )


async def handle(
    payload: Any,
    context: RenderContext,
) -> tuple[Any, int]:
    """A whole POST body: one request or a batch. Returns (body, status).

    A body of nothing but notifications gets 202 and no content, which is what
    JSON-RPC asks for and what a host checks.
    """
    batch = payload if isinstance(payload, list) else [payload]

    responses: list[dict[str, Any]] = []
    for entry in batch:
        if not isinstance(entry, dict):
            responses.append(err(None, -32600, "Invalid Request: not an object"))
            continue

        # The template is the one response that reads files, so it is handled
        # here and everything else stays pure.
        if (
            entry.get("method") == "resources/read"
            and (entry.get("params") or {}).get("uri") == APP_URI
        ):
            responses.append(
                ok(
                    entry.get("id"),
                    {
                        "contents": [
                            {
                                "uri": APP_URI,
                                "mimeType": APP_MIME,
                                "text": app_template(context.origin),
                                "_meta": _app_resource(context.origin)["_meta"],
                            }
                        ]
                    },
                )
            )
            continue

        response = await handle_rpc(entry, context)
        if response is not None:
            responses.append(response)

    if not responses:
        return None, 202
    return (responses if isinstance(payload, list) else responses[0]), 200
