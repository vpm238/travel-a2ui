"""The HTTP surface: one service, three front ends and an agent behind them.

    /               the React client
    /flutter        the Flutter web client
    /api/*          the agent, the session and the catalog
    /mcp            the same agent, for Claude and other MCP hosts

One Cloud Run service rather than two, and that is a decision worth stating.
Splitting the front end from the API would buy nothing here — there is no
independent scaling story, no separate release cadence, and no second team —
while costing a cross-origin configuration, a second deployment to keep in
step, and a class of bug where the two halves are different versions of the
same app. Same origin means the browser sends no preflight and the client needs
no base URL at all.

The API key is never stored. It arrives on the request that uses it and leaves
with it; a deployment may carry its own, and then the UI stops asking.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import CATALOG_ID, CATALOG_JSON, SurfaceAction, TurnRequest, run_turn
from .contract import INSTANTIATION_MAX_AGE_MS, contract_stamp
from .providers.fixture import FixtureProvider
from . import mcp
from .sessions import SessionStore
from .surface import STANDING_SURFACES
from .voice import VoiceSession, relay
from .skills import SKILL_VARIANTS, describe_all_skills, is_skill_variant

_ROOT = pathlib.Path(__file__).resolve().parents[4]

#: Where the built clients are, when they have been built.
#:
#: Absent in development, which is deliberate rather than unhandled: `npm run
#: dev` serves the React app on its own port against this API, and mounting a
#: stale `dist/` underneath it is how you end up debugging a build from
#: yesterday.
WEB_DIST = _ROOT / "apps" / "web" / "dist"
FLUTTER_DIST = _ROOT / "apps" / "flutter_client" / "build" / "web"

MODELS = [
    {"id": "gemini-3.8-flash", "label": "Flash 3.8", "note": "Default. Fastest to first surface"},
    {"id": "gemini-3.7-flash", "label": "Flash 3.7", "note": "The previous Flash"},
    {"id": "gemini-3.5-flash-lite", "label": "Flash Lite", "note": "Cheapest; simpler surfaces"},
]

SURFACES = ["inline", "sidebar", "home"]

sessions = SessionStore()
provider = FixtureProvider()

app = FastAPI(title="Travel A2UI", docs_url=None, redoc_url=None)


def _no_store(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"cache-control": "no-store"})


@app.get("/api/meta")
async def meta() -> JSONResponse:
    """Everything a client needs to configure itself, so none of it is compiled in."""
    destinations = await provider.destinations()
    return _no_store(
        {
            "name": os.environ.get("PUBLIC_NAME", "Travel A2UI"),
            "catalogId": CATALOG_ID,
            "protocolVersion": "v0.9.1",
            "defaultModel": os.environ.get("DEFAULT_MODEL", "gemini-3.8-flash"),
            "defaultSkill": os.environ.get("DEFAULT_SKILL", "express-monolithic"),
            "models": MODELS,
            "surfaces": SURFACES,
            "skills": describe_all_skills(),
            "destinations": [
                {
                    "city": entry["city"],
                    "country": entry["country"],
                    "airport": entry["airport"],
                    "summary": entry["summary"],
                }
                for entry in destinations
            ],
            # Where this deployment's travel data comes from, advertised so the
            # front end can say so once in the chrome instead of every surface
            # carrying a badge — and so a reader of the API can tell a demo
            # from a live deployment without guessing from the prices.
            "provenance": provider.provenance.as_dict(),
            "contract": {"stamp": contract_stamp(), "maxAgeMs": INSTANTIATION_MAX_AGE_MS},
            "mcpEndpoint": "/mcp",
            # True when the deployment carries its own key and the UI need not ask.
            "keyProvided": bool(os.environ.get("GEMINI_API_KEY")),
            "runtime": "python",
            # The two agent frameworks, offered to the traveller as a choice.
            # They are genuinely different runtimes — a request/response loop
            # this server drives against the Interactions API, and a
            # bidirectional session Google drives against the Live API — and
            # the honest way to show that the interface layer is independent of
            # the runtime is to let someone switch and watch the same
            # components come back.
            #
            # They share nothing. The front end reloads on a switch, so each
            # opens on its own session with an empty trip: two APIs with two
            # conversation histories is difference enough without also deciding
            # which parts of a half-made trip survive the crossing.
            "backends": [
                {
                    "id": "python",
                    "label": "Python server",
                    "origin": "",
                    "voice": False,
                    "note": (
                        "Gemini Interactions API, driven from this server. Typed "
                        "conversation; surfaces stream in as the model composes them."
                    ),
                },
                {
                    "id": "live",
                    "label": "Gemini Live",
                    "origin": "",
                    "voice": True,
                    "note": (
                        "Gemini Live API, relayed through this server. Speak or type; "
                        "it answers out loud and draws the same surfaces."
                    ),
                },
            ],
        }
    )


@app.get("/api/catalog")
async def catalog() -> JSONResponse:
    return JSONResponse(CATALOG_JSON, headers={"cache-control": "public, max-age=300"})


@app.get("/api/session")
async def get_session(sessionId: str = "") -> JSONResponse:  # noqa: N803 - wire name
    if not sessionId:
        raise HTTPException(status_code=400, detail="sessionId is required")
    session = sessions.get(sessionId)
    return _no_store({"trip": session.trip, "turns": session.turns})


@app.post("/api/session/reset")
async def reset_session(request: Request) -> JSONResponse:
    body = await _json_body(request)
    session_id = body.get("sessionId")
    if not session_id:
        raise HTTPException(status_code=400, detail="sessionId is required")
    sessions.reset(str(session_id))
    return _no_store({"ok": True})


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is a 400, not a 500
        return {}
    return body if isinstance(body, dict) else {}


@app.post("/api/chat")
async def chat(request: Request, x_goog_api_key: str = Header(default="")) -> StreamingResponse:
    """One turn, as server-sent events.

    SSE rather than a WebSocket because the traffic is one-directional for the
    length of a turn and SSE reconnects, proxies and debugs like ordinary HTTP.
    The stream carries the same events the agent yields, so a second client
    implements a renderer and not a protocol.
    """
    body = await _json_body(request)
    api_key = (x_goog_api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="A Gemini API key is required. Send it as the x-goog-api-key header.",
        )

    session_id = str(body.get("sessionId") or sessions.new_id())
    session = sessions.get(session_id)

    skill = body.get("skill")
    if not is_skill_variant(skill):
        skill = os.environ.get("DEFAULT_SKILL", SKILL_VARIANTS[0])

    action_body = body.get("action")
    action = None
    if isinstance(action_body, dict) and action_body.get("name"):
        action = SurfaceAction(
            name=str(action_body["name"]),
            surface_id=str(action_body.get("surfaceId") or "inline-1"),
            context=action_body.get("context") or {},
            data_model=action_body.get("dataModel"),
            source_component_id=action_body.get("sourceComponentId"),
        )

    # Where this turn draws.
    #
    # A standing surface has one id for the life of the conversation — there is
    # one panel, and redrawing it is the point. An inline card is the opposite:
    # it is a thing that was asked once, and the conversation is the list of
    # them. So each one gets its own id.
    #
    # They used to share `inline-1`, and the renderer stores surfaces by id, so
    # every card in the transcript was a view onto the *same* surface. Answering
    # a question rewrote the question — and every earlier card with it — which
    # looked like the interface refreshing itself at random. It also quietly
    # disabled the finished-card treatment: a card is greyed and made inert once
    # the turn that drew it is over, and that was working exactly as written
    # against a card whose content had already been replaced.
    #
    # `surfaceId` in the body is still honoured, because a client re-attaching
    # to a surface it already has is asking for that one by name.
    requested_surface = str(body.get("surface") or "inline")
    if requested_surface in STANDING_SURFACES:
        drawn_surface_id = requested_surface
    else:
        drawn_surface_id = str(body.get("surfaceId") or session.next_inline_surface_id())

    turn = TurnRequest(
        api_key=api_key,
        model=str(body.get("model") or os.environ.get("DEFAULT_MODEL", "gemini-3.8-flash")),
        message=str(body.get("message") or ""),
        action=action,
        interaction_id=session.interaction_id,
        trip=dict(session.trip),
        surface=requested_surface,
        surface_id=drawn_surface_id,
        skill=str(skill),
        effort=str(body.get("effort") or "medium"),
        shape=session.shape,
        origin_hint=_origin_hint(body.get("client")),
        provider=provider,
    )

    async def events() -> AsyncIterator[bytes]:
        # The session id goes out first, so a client that did not send one
        # knows what to send next time. Everything after it is a turn event.
        yield _sse({"type": "session", "sessionId": session_id})
        async for event in run_turn(turn):
            if event["type"] == "__result__":
                result = event["result"]
                sessions.save(
                    session_id,
                    interaction_id=result.interaction_id,
                    trip=result.trip,
                    shape=result.shape,
                )
                continue
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store",
            # Proxies that buffer a stream turn streaming into a slow
            # request/response, which looks to the traveller exactly like the
            # empty-screen wait this whole design is about avoiding.
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )


def _sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def _origin_hint(client: Any) -> dict[str, Any] | None:
    """Where the traveller might be flying from. Never a decision.

    Coordinates when the browser gave them, the timezone otherwise. The
    difference is not small: a timezone covers a continent-slice, so
    `America/New_York` offered JFK to Boston, Philadelphia and Atlanta alike —
    and Atlanta is 1,211 km from JFK and 965 km from Chicago, so the confident
    answer was also the wrong one.

    With coordinates the hint carries the nearest few rather than one, because
    "nearest" is not the same as "theirs": someone in Atlanta may well fly from
    Miami. Offering three to press beats asserting one, and both beat asking
    them to type an airport code.
    """
    if not isinstance(client, dict):
        return None

    from .providers.fixture import origin_for_time_zone, origins_near

    lat, lon = client.get("lat"), client.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not (
        isinstance(lat, bool) or isinstance(lon, bool)
    ):
        # Out-of-range coordinates are not worth a guess; a bad fix is worse
        # than none, because it looks just as confident.
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            near = origins_near(float(lat), float(lon))
            if near:
                first = near[0]
                return {
                    "code": first["code"],
                    "city": first["city"],
                    "from": "location",
                    "nearby": [
                        {"code": a["code"], "city": a["city"], "km": a["km"]} for a in near
                    ],
                }

    zone = client.get("timeZone")
    if not isinstance(zone, str) or not zone:
        return None
    suggested = origin_for_time_zone(zone)
    if not suggested:
        return None
    return {
        "code": suggested["code"],
        "city": suggested["city"],
        "timeZone": zone,
        "from": "timezone",
    }


@app.get("/mcp")
async def mcp_get() -> JSONResponse:
    """Streamable HTTP lets a server decline the SSE channel.

    This one is stateless — every POST is self-contained — so there is nothing
    to push and nothing to keep open.
    """
    return JSONResponse(
        {"error": "This MCP server is stateless: POST JSON-RPC to this endpoint."},
        status_code=405,
        headers={"allow": "POST"},
    )


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    """The MCP endpoint: these surfaces, inside somebody else's agent."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - a parse error has its own JSON-RPC code
        return JSONResponse(
            mcp.err(None, -32700, "Parse error: body is not JSON"), status_code=400
        )

    context = mcp.RenderContext(
        # Chosen once, at install time, by whoever knows what their host renders.
        view=request.query_params.get("view") or "",
        origin=_renderer_origin(request),
        # The provider travels with the request because the endpoint is
        # stateless: without it an MCP call would answer from fixtures on a
        # deployment configured for live inventory, and answer *differently*
        # from the same tool called through the web app.
        provider=provider,
    )
    context.view = mcp._view_of(context.view or None)

    body, status = await mcp.handle(payload, context)
    if body is None:
        return Response(status_code=status)
    return JSONResponse(body, status_code=status, headers={"cache-control": "no-store"})


def _renderer_origin(request: Request) -> str:
    """Where the view should load the renderer from.

    Normally the origin the host just called. `?origin=` covers the case where
    it is not — a tunnel, a proxy, a preview URL that differs from the public
    one — and only over http(s), because anything else is a script source
    somebody put in a URL.
    """
    from urllib.parse import urlparse

    override = request.query_params.get("origin")
    if override:
        parsed = urlparse(override)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


@app.websocket("/api/voice")
async def voice(socket: WebSocket) -> None:
    """One voice call, relayed.

    A WebSocket here and server-sent events for the typed turn, and the
    asymmetry is the honest one: a call is bidirectional for its whole length
    and a turn is not.

    The browser could open a socket straight to Google. Then every client would
    need the catalog, the compiler, the tools and the trip — and the claim that
    a client only knows how to draw components would stop being true. What goes
    over this socket is microphone bytes up, audio and A2UI down, which is
    exactly what a Swift or Flutter client would send and receive.

    The key arrives in the opening frame and is never stored.
    """
    await socket.accept()

    try:
        opening = await socket.receive_json()
    except Exception:  # noqa: BLE001 - a client that hung up before speaking
        await socket.close()
        return

    if opening.get("type") != "start":
        await socket.send_json(
            {"type": "error", "message": "The first frame must be a start."}
        )
        await socket.close()
        return

    api_key = str(opening.get("apiKey") or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not api_key:
        await socket.send_json({"type": "error", "message": "A Gemini API key is required."})
        await socket.close()
        return

    session_id = str(opening.get("sessionId") or sessions.new_id())
    stored = sessions.get(session_id)

    async def send(message: dict[str, Any]) -> None:
        await socket.send_json(message)

    async def incoming():
        while True:
            try:
                yield await socket.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                return
            except Exception:  # noqa: BLE001 - a frame we could not read
                continue

    call = VoiceSession(
        api_key=api_key,
        trip=dict(stored.trip),
        provider=provider,
        contract=contract_stamp(),
        model=str(opening.get("model") or ""),
        voice=opening.get("voice"),
        # The trip a call changes is the trip the typed conversation reads.
        # Same session, one store — say "make it three of us" out loud and the
        # panel beside the conversation moves.
        on_trip=lambda value: sessions.patch_trip(session_id, value),
    )

    try:
        await relay(call, send, incoming())
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await socket.close()
        except Exception:  # noqa: BLE001 - already closed
            pass


@app.get("/api/healthz")
@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Whether this process is up, and how much it is holding.

    Answered at two paths because one of them does not always arrive. On Cloud
    Run, a request for exactly `/healthz` is answered by Google's own frontend
    with its 404 page — the container never sees it, and from outside that is
    indistinguishable from an app that failed to register the route. `/healthz/`
    with the trailing slash reaches the app, which is how that was pinned down.
    `/api/healthz` is under a prefix nothing intercepts, so it is the one to
    check from a script.

    This is not Cloud Run's own health check: that one is a TCP connect to the
    port, and it passes as soon as uvicorn binds.
    """
    return JSONResponse({"ok": True, "sessions": len(sessions)})


def mount_clients() -> None:
    """Serves the built front ends, when they have been built.

    Mounted last so nothing here can shadow an API route, and each only if its
    build output exists — a missing `dist/` in development is the normal case,
    not a misconfiguration.
    """
    if FLUTTER_DIST.is_dir():
        app.mount("/flutter", StaticFiles(directory=FLUTTER_DIST, html=True), name="flutter")

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

        @app.exception_handler(404)
        async def spa_fallback(request: Request, _exc: Any) -> Any:
            # A single-page app owns its own routing, so an unknown path that
            # is not an API path is a route the client knows about and the
            # server does not. An API path stays a 404, or a typo in a fetch
            # silently returns HTML and fails somewhere much less obvious.
            if request.url.path.startswith(("/api/", "/mcp", "/healthz")):
                return _no_store({"error": f"No route for {request.url.path}"}, 404)
            return FileResponse(WEB_DIST / "index.html")


mount_clients()
