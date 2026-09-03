"""The managed-agent backend, behind the same wire protocol as the Worker.

Same `POST /api/chat`, same SSE event shape, same `/api/meta`. Point the web app
at this instead and nothing in the front end changes — which is the point of
having two: the *interface* layer is independent of who runs the loop.

What actually differs:

    Worker (TypeScript)             here (Python)
    ─────────────────────────────   ────────────────────────────────────
    we run the tool loop            Anthropic runs it
    prompt assembled per request    agent config uploaded once, versioned
    Durable Object holds history    the managed session holds it
    tools execute in the Worker     the MCP server, called by Anthropic

The A2UI extraction is the same in both, because it is a property of the model's
output rather than of where the loop runs: text arrives, the stream splitter
separates prose from `<a2ui>` blocks, and a compiler turns those into surfaces.

Run it:

    pip install -e '.[dev]'
    python -m travel_agent.setup_agent --mcp-url https://…/mcp
    python -m travel_agent.server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import AgentState, load_catalog, load_skill
from .express import Compiler, ExpressStream, make_compiler

# These are imported at module scope rather than inside `build_app` for a reason
# that costs an afternoon to find: this module uses `from __future__ import
# annotations`, so every annotation is a string that FastAPI resolves against
# the *module's* globals. With `Request` imported inside the factory, FastAPI
# cannot resolve `request: Request`, decides it must be a query parameter, and
# every route that reads a body 422s with "Field required".

# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

CATALOG = load_catalog()
CATALOG_ID = str(CATALOG["catalogId"])

# Conversation id → managed session id. In memory on purpose: the durable half
# already lives in the managed session. Persist this map if you want a
# conversation to survive a restart of *this* process.
#
# Bounded because reloading the page starts a new conversation, so a long-lived
# process would otherwise accumulate one entry per reload forever. Oldest out
# first — Python dicts keep insertion order, which is all the recency this needs.
SESSIONS: dict[str, str] = {}
TURNS: dict[str, int] = {}
MAX_SESSIONS = 500


def remember_session(conversation_id: str, session_id: str) -> None:
    SESSIONS[conversation_id] = session_id
    while len(SESSIONS) > MAX_SESSIONS:
        oldest = next(iter(SESSIONS))
        SESSIONS.pop(oldest)
        TURNS.pop(oldest, None)


def next_turn(conversation_id: str) -> int:
    """Turn number within *this* conversation, which is what names a surface."""
    TURNS[conversation_id] = TURNS.get(conversation_id, 0) + 1
    return TURNS[conversation_id]


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def event_text_blocks(event: Any) -> list[str]:
    """Text out of an `agent.message` event, whatever shape the SDK hands back."""
    content = getattr(event, "content", None)
    if content is None and isinstance(event, dict):
        content = event.get("content")
    if not content:
        return []

    out: list[str] = []
    for block in content:
        kind = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
        if kind != "text":
            continue
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            out.append(text)
    return out


def event_resource_texts(event: Any) -> list[str]:
    """Any embedded resource text on a tool-result event.

    An MCP tool here returns an A2UI payload, so a surface can arrive as a tool
    result rather than in the model's prose. This pulls those out so both paths
    render.
    """
    content = getattr(event, "content", None)
    if content is None and isinstance(event, dict):
        content = event.get("content")
    if not content:
        return []

    out: list[str] = []
    for block in content:
        resource = getattr(block, "resource", None) or (
            block.get("resource") if isinstance(block, dict) else None
        )
        text = None
        if resource is not None:
            text = getattr(resource, "text", None) or (
                resource.get("text") if isinstance(resource, dict) else None
            )
        if text:
            out.append(text)
    return out


def build_app(state: AgentState, compiler: Compiler):  # noqa: C901 - one route, read top to bottom
    import anthropic

    app = FastAPI(title="Travel A2UI — managed agent backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-anthropic-key"],
    )

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "name": "Travel A2UI (managed agent)",
            "catalogId": CATALOG_ID,
            "protocolVersion": "v0.9.1",
            "defaultModel": "managed-agent",
            "defaultSkill": state.skill_variant,
            "models": [
                {
                    "id": "managed-agent",
                    "label": "Managed agent",
                    "note": f"{state.agent_id} v{state.agent_version}",
                }
            ],
            "surfaces": ["inline", "sidebar", "home"],
            "skills": [
                {
                    "variant": state.skill_variant,
                    "skills": ["a2ui"],
                    "inferenceFormat": "express",
                    "protocolVersion": "0.9.1",
                    "characters": len(load_skill(state.skill_variant)),
                }
            ],
            "destinations": [],
            "mcpEndpoint": state.mcp_url,
            "keyProvided": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "compiler": compiler.name,
            # The same two runtimes the Worker advertises, so the picker in the
            # front end can get you back once you have switched over here.
            "runtime": "managed-agent",
            "backends": [
                {
                    "id": "worker",
                    "label": "Cloudflare Worker",
                    "origin": state.worker,
                    "note": (
                        "The loop runs at the edge, in the Worker serving the app. "
                        "One deploy, no second service, sessions in a Durable Object."
                    ),
                },
                {
                    "id": "managed-agent",
                    "label": "Claude Managed Agent",
                    "origin": "",
                    "note": (
                        "Anthropic runs the loop and hosts the sandbox; this backend "
                        f"provisions the agent ({state.agent_id}) and relays the same events."
                    ),
                },
            ],
        }

    @app.get("/api/catalog")
    def catalog() -> Any:
        return CATALOG

    @app.post("/api/session/reset")
    async def reset(request: Request) -> dict[str, bool]:
        body = await request.json()
        conversation_id = str(body.get("sessionId", ""))
        SESSIONS.pop(conversation_id, None)
        TURNS.pop(conversation_id, None)
        return {"ok": True}

    @app.post("/api/compile")
    async def compile_express(request: Request) -> Any:
        """The compiler, as a service — the Python side of the same contract."""
        body = await request.json()
        source = body.get("source")
        if not isinstance(source, str) or not source.strip():
            return JSONResponse({"error": "source is required"}, status_code=400)
        try:
            messages = compiler.compile(source, str(body.get("surfaceId", "default_surface")))
        except Exception as error:
            return JSONResponse({"error": str(error), "source": "compile"}, status_code=422)
        return {"messages": messages, "catalogId": CATALOG_ID, "version": "v0.9.1"}

    @app.post("/api/decompile")
    async def decompile(request: Request) -> Any:
        body = await request.json()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return JSONResponse({"error": "messages is required"}, status_code=400)
        try:
            return {"express": compiler.decompile(messages)}
        except Exception as error:
            return JSONResponse({"error": str(error), "source": "decompile"}, status_code=422)

    async def session_for(client: Any, conversation_id: str) -> str:
        existing = SESSIONS.get(conversation_id)
        if existing:
            return existing
        session = await asyncio.to_thread(
            client.beta.sessions.create,
            agent={"type": "agent", "id": state.agent_id, "version": state.agent_version},
            environment_id=state.environment_id,
            title=f"Trip {conversation_id}",
        )
        remember_session(conversation_id, session.id)
        return session.id

    @app.post("/api/chat")
    async def chat(request: Request) -> Any:
        api_key = (request.headers.get("x-anthropic-key") or "").strip() or os.environ.get(
            "ANTHROPIC_API_KEY"
        )
        if not api_key:
            return JSONResponse(
                {"error": "No Anthropic API key.", "hint": "Add your key in the app."},
                status_code=401,
            )

        body = await request.json()
        conversation_id = str(body.get("sessionId", "")).strip()
        message = str(body.get("message", "")).strip()
        if not conversation_id or not message:
            return JSONResponse({"error": "sessionId and message are required"}, status_code=400)

        surface = body.get("surface") or "inline"
        # Inline surfaces are numbered per conversation, so `inline-2` means the
        # second answer in *this* conversation. Numbering them off the size of
        # the session map instead — as this did — made the id depend on how many
        # other people happened to be using the server.
        surface_id = body.get("surfaceId") or (
            f"inline-{next_turn(conversation_id)}" if surface == "inline" else surface
        )
        surface_state = body.get("surfaceState") or {}

        client = anthropic.Anthropic(api_key=api_key)

        async def stream() -> AsyncIterator[str]:
            try:
                session_id = await session_for(client, conversation_id)
            except Exception as error:
                yield sse({"type": "error", "message": str(error), "retryable": True})
                yield sse({"type": "done", "stopReason": None})
                return

            yield sse(
                {
                    "type": "start",
                    "model": "managed-agent",
                    "skill": state.skill_variant,
                    "surfaceId": surface_id,
                }
            )

            splitter = ExpressStream(compiler, surface_id)
            prompt = message
            if surface_state:
                prompt += f"\n\n[The traveller's current on-screen values: {json.dumps(surface_state)}]"
            prompt += f'\n[Draw into surface "{surface_id}". The host catalog is {CATALOG_ID}.]'

            try:
                # Stream-first: the SSE stream only delivers events that happen
                # after it opens, so opening after the send shows the whole turn
                # as one late batch.
                events = await asyncio.to_thread(client.beta.sessions.events.stream, session_id)
                await asyncio.to_thread(
                    client.beta.sessions.events.send,
                    session_id,
                    events=[
                        {"type": "user.message", "content": [{"type": "text", "text": prompt}]}
                    ],
                )
            except Exception as error:
                yield sse({"type": "error", "message": str(error), "retryable": True})
                yield sse({"type": "done", "stopReason": None})
                return

            queue: asyncio.Queue[Any] = asyncio.Queue()
            sentinel = object()

            def pump() -> None:
                try:
                    for event in events:
                        queue.put_nowait(event)
                except Exception as error:  # surfaced on the consuming side
                    queue.put_nowait(error)
                finally:
                    queue.put_nowait(sentinel)

            asyncio.get_running_loop().run_in_executor(None, pump)

            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                if isinstance(item, Exception):
                    yield sse({"type": "error", "message": str(item), "retryable": True})
                    break

                kind = getattr(item, "type", "") or ""

                if kind == "agent.message":
                    for text in event_text_blocks(item):
                        for parsed in splitter.push(text):
                            if parsed.kind == "text":
                                yield sse({"type": "text", "delta": parsed.delta})
                            elif parsed.kind == "ui":
                                yield sse(
                                    {
                                        "type": "ui",
                                        "surfaceId": surface_id,
                                        "messages": parsed.messages,
                                        "done": parsed.done,
                                    }
                                )
                            else:
                                yield sse(
                                    {
                                        "type": "ui_error",
                                        "message": parsed.message,
                                        "source": "stream",
                                    }
                                )

                elif kind in {"agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"}:
                    yield sse(
                        {
                            "type": "tool",
                            "name": getattr(item, "name", "tool"),
                            "input": None,
                            "status": "running",
                        }
                    )

                elif kind in {"agent.tool_result", "agent.mcp_tool_result"}:
                    yield sse(
                        {
                            "type": "tool_result",
                            "name": getattr(item, "name", "tool"),
                            "result": None,
                            "isError": False,
                        }
                    )
                    for text in event_resource_texts(item):
                        try:
                            payload = json.loads(text)
                        except ValueError:
                            continue
                        if isinstance(payload, list) and payload:
                            yield sse(
                                {
                                    "type": "ui",
                                    "surfaceId": surface_id,
                                    "messages": payload,
                                    "done": True,
                                }
                            )

                elif kind == "session.status_idle":
                    for parsed in splitter.end():
                        if parsed.kind == "text":
                            yield sse({"type": "text", "delta": parsed.delta})
                        elif parsed.kind == "ui":
                            yield sse(
                                {
                                    "type": "ui",
                                    "surfaceId": surface_id,
                                    "messages": parsed.messages,
                                    "done": parsed.done,
                                }
                            )
                    yield sse({"type": "done", "stopReason": "idle"})
                    return

                elif kind == "session.status_terminated":
                    yield sse({"type": "done", "stopReason": "terminated"})
                    return

            yield sse({"type": "done", "stopReason": None})

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"cache-control": "no-store, no-transform", "x-accel-buffering": "no"},
        )

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="travel_agent.server", description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8788)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--compiler",
        choices=["auto", "sdk", "service"],
        default="auto",
        help="Which Express compiler to use. 'auto' prefers the a2ui SDK and "
        "falls back to the compile service when the installed SDK is too old.",
    )
    parser.add_argument("--compile-service", help="Override the compile service base URL.")
    args = parser.parse_args(argv)

    state = AgentState.load()
    if state is None:
        print(
            "No .agent.json found. Provision the agent first:\n"
            "  python -m travel_agent.setup_agent --mcp-url https://<your-worker>.workers.dev/mcp"
        )
        return 1

    service = args.compile_service or state.compile_service
    prefer = None if args.compiler == "auto" else args.compiler
    try:
        compiler = make_compiler(CATALOG, CATALOG_ID, prefer=prefer, service_url=service)
    except Exception as error:
        print(str(error))
        return 1

    import uvicorn

    print(f"Managed-agent backend on http://{args.host}:{args.port}")
    print(f"  agent       {state.agent_id} (version {state.agent_version})")
    print(f"  environment {state.environment_id}")
    print(f"  mcp server  {state.mcp_url}")
    print(f"  compiler    {compiler.name}" + (f" → {service}" if compiler.name == "service" else ""))
    print(f"\nPoint the web app at it: VITE_API_ORIGIN=http://{args.host}:{args.port} npm run dev:web")

    uvicorn.run(build_app(state, compiler), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
