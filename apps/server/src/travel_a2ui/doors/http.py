"""The HTTP surface: one service, two front ends and an agent behind them.

    /               the React client
    /flutter        the Flutter web client
    /api/*          the agent, the session and the catalog

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
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import ROOT
from ..brain import data, host_actions, inbound
from ..brain import trip as model
from ..brain.providers.fixture import FixtureProvider
from ..brain.skills import describe_all_skills
from ..brain.ui import STANDING_SURFACES
from ..sessions import SessionStore
from . import guard
from .interactions import (
    CATALOG_ID,
    CATALOG_JSON,
    PROTOCOL_VERSION,
    TurnRequest,
    WarmRequest,
    run_turn,
    warm,
)
from .interactions import (
    DEFAULT_EFFORT as AGENT_DEFAULT_EFFORT,
)
from .interactions import (
    DEFAULT_MODEL as AGENT_DEFAULT_MODEL,
)
from .interactions.turn import places_and_currency, ui_events
from .live import INSTANTIATION_MAX_AGE_MS, VoiceSession, contract_stamp, relay

_ROOT = ROOT

#: Where the built clients are. Either may be missing: `npm run dev:web`
#: serves React on its own port against this API, and Flutter is optional.
WEB_DIST = _ROOT / "apps" / "web" / "dist"
FLUTTER_DIST = _ROOT / "renderers" / "flutter" / "build" / "web"
#: The A2UI quickstart (`docs/site`), a static Starlight site built for `/docs`.
DOCS_DIST = _ROOT / "docs" / "site" / "dist"

#: What this deployment can run, reported for information.
#:
#: Not a picker any more. One was offered in the header and it governed the
#: reply but not the panel beside it, which was pinned to the small model with
#: the picked one wired in as its *fallback* — so choosing the better model
#: changed half the screen. `DEFAULT_MODEL` decides, `PANEL_MODEL` decides for
#: the panels, and both live in `doors/settings.py`, where every door reads the
#: same answer. This list stays because a reader of the API should be able to see what
#: the deployment is running without reading its source.
MODELS = [
    {
        "id": "gemini-3.8-flash",
        "label": "Flash 3.8",
        "note": "Default. Follows the whole journey; a few seconds slower",
    },
    {
        "id": "gemini-3.5-flash-lite",
        "label": "Flash Lite",
        "note": "Fastest to first surface; misses the return leg",
    },
    {"id": "gemini-3.7-flash", "label": "Flash 3.7", "note": "The previous Flash"},
]

SURFACES = ["inline", "sidebar", "home"]

sessions = SessionStore()
provider = FixtureProvider()

#: Overridable per deployment; the defaults themselves live in `agent.py`, next
#: to the loop that uses them, so the voice relay and the typed path cannot
#: drift onto two different models.
#:
#: `minimal` thinking because this turn is mostly recall: the catalog, the
#: component signatures and the rules are all in the prompt, and the job is to
#: pick three components and bind them. A traced turn at `low` spent 3,316
#: thought tokens — about thirteen seconds of a forty-three second turn —
#: deciding how to draw a form it draws every time. The picker still offers the
#: rest.
DEFAULT_EFFORT = os.environ.get("DEFAULT_EFFORT", AGENT_DEFAULT_EFFORT)


def _model(requested: Any) -> str:
    return guard.chosen_model(requested, (entry["id"] for entry in MODELS), AGENT_DEFAULT_MODEL)


def _shared_key_refused(request: Any, own_key: str) -> bool:
    """True when this request would run on the server's key past its limit."""
    if own_key.strip() or not guard.server_key():
        return False
    address = guard.client_address(request.headers, request.client.host if request.client else None)
    return not guard.SHARED_KEY_LIMIT.allow(address)


app = FastAPI(title="Travel A2UI", docs_url=None, redoc_url=None)


def _no_store(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"cache-control": "no-store"})


@app.post("/api/warm")
async def warm_up(request: Request, x_goog_api_key: str = Header(default="")) -> JSONResponse:
    """Start the conversation before the traveller has typed anything.

    The client calls this once, when somebody first touches the composer — which
    is the moment they are about to type and several seconds before they finish.
    The reply is a receipt the next turn resumes, so that turn pays forty-odd
    input tokens instead of five thousand.

    A POST because it creates something. Cheap, and safe to call twice: a second
    conversation is started, the client keeps the newer receipt, and the older
    one is never referred to again.
    """
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - an empty body is a valid warm-up
        body = {}

    api_key = (x_goog_api_key or guard.server_key()).strip()
    if not api_key:
        # Not an error. A visitor with no key has nothing to warm, and saying so
        # with a 400 would put a red line in their console on page load.
        return _no_store({"interactionId": None, "setup": None, "skipped": "no key"})
    if _shared_key_refused(request, x_goog_api_key):
        return _no_store({"interactionId": None, "setup": None, "skipped": "limited"})

    return _no_store(await warm(WarmRequest(api_key=api_key, model=_model(body.get("model")))))


OPENERS = [
    "Six days in Madrid in April, two of us, around $2,500 all in",
    "Find me a nonstop to Lisbon and somewhere to stay in Alfama",
    "Plan three days in Tokyo — first visit, we like walking",
    "What would a week in Mexico City cost in November?",
]


@app.get("/api/meta")
async def meta() -> JSONResponse:
    """Everything a client needs to configure itself, so none of it is compiled in."""
    destinations = await provider.destinations()
    return _no_store(
        {
            "name": os.environ.get("PUBLIC_NAME", "Travel A2UI"),
            "catalogId": CATALOG_ID,
            "protocolVersion": PROTOCOL_VERSION,
            "defaultModel": AGENT_DEFAULT_MODEL,
            "defaultSkill": "express-modular",
            "models": MODELS,
            "surfaces": SURFACES,
            # The browser needs this one, unlike the Gemini key: the Maps
            # JavaScript API is loaded by the page. That is what a Maps key is
            # for — it is restricted by HTTP referrer rather than kept secret,
            # so shipping it to the client is the documented way to use it, and
            # a deployment without one simply gets no maps.
            "mapsApiKey": os.environ.get("GOOGLE_MAPS_API_KEY", ""),
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
            # What an empty conversation offers to say first. Here rather than
            # in each client, so the React and Flutter apps open on the same
            # suggestions and changing them is a deploy, not two releases.
            "openers": OPENERS,
            "contract": {"stamp": contract_stamp(), "maxAgeMs": INSTANTIATION_MAX_AGE_MS},
            # True when the deployment carries its own key and the UI need not ask.
            "keyProvided": bool(os.environ.get("GEMINI_API_KEY")),
            # Where a first visit's sample trip is, or null for none. It is a
            # recording of a real conversation with this agent
            # (`tools/sample/record.py`), so what a visitor sees before they
            # spend anything is what the agent actually draws — not a layout
            # the host composed. Off with `SAMPLE_TRIP=0`, which the scripted
            # test server sets so a test starts from an empty conversation.
            "sampleTrip": (
                "sample-trip.json"
                if os.environ.get("SAMPLE_TRIP", "1") != "0" and (WEB_DIST / "sample-trip.json").exists()
                else None
            ),
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


@app.post("/api/express")
async def express(request: Request) -> JSONResponse:
    """A surface's messages, as Express — by the A2UI SDK's decompiler.

    For the Wire view. The server holds the catalog and the SDK, so it answers.
    """
    from ..brain.catalog import decompile

    body = await _json_body(request)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > 50:
        raise HTTPException(status_code=400, detail="messages must be a list of 1 to 50 A2UI messages")
    try:
        text = decompile(messages)
    except Exception as error:  # noqa: BLE001 - a surface that does not decompile is a 422, not a 500
        return JSONResponse({"error": f"{type(error).__name__}: {error}"}, status_code=422)
    return _no_store({"express": text})


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
    """One turn, as server-sent events. The request and events are `docs/transport.md`."""
    body = await _json_body(request)
    api_key = (x_goog_api_key or guard.server_key()).strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="A Gemini API key is required. Send it as the x-goog-api-key header.",
        )
    if _shared_key_refused(request, x_goog_api_key):
        raise HTTPException(status_code=429, detail=guard.LIMITED)

    session_id = str(body.get("sessionId") or sessions.new_id())
    session = sessions.get(session_id)
    renderer = inbound.read(body)
    canvas = session.canvas
    unrenderable = canvas.negotiate(renderer.capabilities)
    if unrenderable is not None:

        async def refused() -> AsyncIterator[bytes]:
            yield _sse({"type": "session", "sessionId": session_id})
            yield _sse({"type": "error", "message": unrenderable, "retryable": False})
            yield _sse({"type": "done", "stopReason": "error"})

        return StreamingResponse(refused(), media_type="text/event-stream")
    held = renderer.surfaces
    if held is not None and renderer.action is not None and renderer.action.surface_id not in held:
        held = [*held, renderer.action.surface_id]
    stale = canvas.reconcile(held)

    # A standing surface keeps its id for the conversation; every inline card
    # gets a new one, so answering a question never rewrites an earlier card.
    requested_surface = str(body.get("surface") or "inline")
    if requested_surface in STANDING_SURFACES:
        drawn_surface_id = requested_surface
    else:
        drawn_surface_id = session.next_inline_surface_id(held or ())

    turn = TurnRequest(
        api_key=api_key,
        model=_model(body.get("model")),
        message=str(body.get("message") or ""),
        action=renderer.action,
        errors=renderer.errors,
        data_model=renderer.data_model,
        # The client's copy wins: it is the one party present for every turn.
        interaction_id=_resumed(body, "interactionId") or session.interaction_id,
        trip=_resumed(body, "trip") or dict(session.trip),
        surface=requested_surface,
        surface_id=drawn_surface_id,
        effort=guard.chosen_effort(body.get("effort"), DEFAULT_EFFORT),
        setup=_resumed(body, "setup") or session.setup,
        client_hints=body.get("client") if isinstance(body.get("client"), dict) else None,
        canvas=canvas,
        provider=provider,
    )

    async def events() -> AsyncIterator[bytes]:
        yield _sse({"type": "session", "sessionId": session_id})
        for problem in renderer.refused:
            yield _sse({"type": "warning", "message": f"Not read: {problem}"})
        for event in ui_events(stale, done=True):
            yield _sse(event)

        # A press the host answers itself: nothing to decide, so no model turn.
        action = renderer.action
        if action is not None and host_actions.handles(action.name):
            patch = host_actions.apply(action.name, turn.trip, action.context)
            if patch is not None:
                trip = model.merge(turn.trip, patch)
                sessions.save(session_id, trip=trip)
                places, _ = await places_and_currency(provider, trip)
                values = lambda _surface: data.session_values(trip, places)  # noqa: E731
                for event in ui_events(canvas.provide(values), done=True):
                    yield _sse(event)
                yield _sse({"type": "trip", "trip": trip})
                yield _sse({"type": "resume", "trip": trip})
                yield _sse({"type": "done", "stopReason": "host"})
                return

        async for event in run_turn(turn):
            if event["type"] == "__result__":
                result = event["result"]
                # The receipt: everything needed for the next turn, held by the
                # client and sent back, so any instance can answer it.
                yield _sse(
                    {
                        "type": "resume",
                        "interactionId": result.interaction_id,
                        "trip": result.trip,
                        "setup": result.setup,
                    }
                )
                sessions.save(
                    session_id,
                    interaction_id=result.interaction_id,
                    trip=result.trip,
                    setup=result.setup,
                )
                continue
            # Written the moment it moves, so a stream the traveller cancels by
            # pressing something still leaves the trip recorded.
            if event["type"] == "trip" and isinstance(event.get("trip"), dict):
                sessions.save(session_id, trip=event["trip"])
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-store",
            # A buffering proxy turns a stream into a slow response.
            "x-accel-buffering": "no",
            "connection": "keep-alive",
        },
    )


def _sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def _resumed(body: dict[str, Any], key: str) -> Any:
    """A value the client carried back from the last turn, if it did.

    Read defensively: a client that omits it, or sends the wrong shape, falls
    back to this instance's own memory rather than failing. Both paths are
    correct — the continuation is an optimisation for the case where this
    instance is not the one that answered last time.
    """
    resume = body.get("resume")
    if not isinstance(resume, dict):
        return None
    value = resume.get(key)
    if key == "trip":
        return dict(value) if isinstance(value, dict) and value else None
    return value if isinstance(value, str) and value else None


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
    exactly what the Flutter client sends and receives.

    The key arrives in the opening frame and is never stored.
    """
    if not guard.origin_allowed(socket.headers.get("origin"), socket.headers.get("host")):
        await socket.close(code=1008)
        return
    await socket.accept()

    try:
        opening = await socket.receive_json()
    except Exception:  # noqa: BLE001 - a client that hung up before speaking
        await socket.close()
        return

    if opening.get("type") != "start":
        await socket.send_json({"type": "error", "message": "The first frame must be a start."})
        await socket.close()
        return

    own_key = str(opening.get("apiKey") or "").strip()
    api_key = own_key or guard.server_key()
    if not api_key:
        await socket.send_json({"type": "error", "message": "A Gemini API key is required."})
        await socket.close()
        return
    if not own_key:
        address = guard.client_address(socket.headers, socket.client.host if socket.client else None)
        if not guard.SHARED_KEY_LIMIT.allow(address):
            await socket.send_json({"type": "error", "message": guard.LIMITED})
            await socket.close()
            return

    # The query string first, because that is where the client puts it
    # (`voice.ts` sets `?sessionId=`). A call is the same conversation as the
    # typed one: same trip, same panel, and the Live resumption handle kept
    # where the next connection will look. The opening frame is also accepted.
    session_id = str(socket.query_params.get("sessionId") or opening.get("sessionId") or sessions.new_id())
    stored = sessions.get(session_id)

    renderer = inbound.read(opening)
    canvas = stored.canvas
    unrenderable = canvas.negotiate(renderer.capabilities)
    if unrenderable is not None:
        await socket.send_json({"type": "error", "message": unrenderable})
        await socket.close()
        return
    stale = canvas.reconcile(renderer.surfaces)

    async def send(message: dict[str, Any]) -> None:
        await socket.send_json(message)

    for event in ui_events(stale, done=True):
        await send(event)

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
        # The Live model is the server's choice (`VOICE_MODEL`), not the client's.
        model="",
        voice=opening.get("voice"),
        # The trip a call changes is the trip the typed conversation reads.
        # Same session, one store — say "make it three of us" out loud and the
        # panel beside the conversation moves.
        on_trip=lambda value: sessions.patch_trip(session_id, value),
        # Where to pick the conversation up, and where to record a fresh place
        # to pick it up from. A Live session belongs to Google and ends on its
        # own schedule; this is what makes that a reconnection rather than an
        # amnesia, so that releasing the microphone stays the ordinary thing it
        # looks like.
        resume=stored.live_handle,
        on_resume=lambda handle: sessions.set_live_handle(session_id, handle),
        # The same mirror of the renderer the typed door keeps.
        canvas=canvas,
        held=list(renderer.surfaces or []),
        # Same reading of "today" as the typed path: a call plans dates too.
        client_hints=opening.get("client") if isinstance(opening.get("client"), dict) else None,
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


def _is_api(path: str) -> bool:
    return path.startswith(("/api/", "/healthz"))


class BuiltClient(StaticFiles):
    """A front end served from its build folder, looked up on each request.

    So a client built while the server is running is served at once, with no
    restart, and one not built yet says how to build it instead of a bare 404.
    `instead` is another client, `(folder, url)`, that the bare address sends
    you to when only that one is built.
    """

    def __init__(self, directory: Any, how_to_build: str, instead: tuple[Any, str] | None = None) -> None:
        super().__init__(directory=directory, html=True, check_dir=False)
        self.folder = directory
        self.how_to_build = how_to_build
        self.instead = instead

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self.folder.is_dir():
            await super().__call__(scope, receive, send)
            return
        path = scope.get("path", "")
        if _is_api(path):
            raise HTTPException(status_code=404)
        if self.instead and path == "/" and self.instead[0].is_dir():
            await RedirectResponse(self.instead[1])(scope, receive, send)
            return
        page = f"Not built yet. {self.how_to_build}, then reload this page.\n"
        await PlainTextResponse(page, status_code=404)(scope, receive, send)


def mount_clients() -> None:
    """Serves the front ends: React at `/`, Flutter at `/flutter`, the docs at `/docs`.

    Mounted last so nothing here can shadow an API route.
    """
    app.mount(
        "/flutter",
        BuiltClient(
            FLUTTER_DIST,
            "Build the Flutter client: cd renderers/flutter && flutter build web --base-href=/flutter/",
        ),
        name="flutter",
    )

    # The quickstart: documentation about this app, served beside it so the
    # tour and the demo it tours share one address. A static site with its own
    # 404 page, which `html=True` serves for a missing path under /docs.
    if DOCS_DIST.is_dir():
        app.mount("/docs", StaticFiles(directory=DOCS_DIST, html=True), name="docs")

    app.mount(
        "/",
        BuiltClient(
            WEB_DIST,
            "Build the React client: npm install && npm run build",
            instead=(FLUTTER_DIST, "/flutter/"),
        ),
        name="web",
    )

    @app.exception_handler(404)
    async def spa_fallback(request: Request, _exc: Any) -> Any:
        # A single-page app owns its own routing, so an unknown path that is
        # not an API path is a route the client knows about and the server
        # does not. An API path stays a 404, or a typo in a fetch silently
        # returns HTML and fails somewhere much less obvious.
        if _is_api(request.url.path) or not (WEB_DIST / "index.html").is_file():
            return _no_store({"error": f"No route for {request.url.path}"}, 404)
        return FileResponse(WEB_DIST / "index.html")


mount_clients()
