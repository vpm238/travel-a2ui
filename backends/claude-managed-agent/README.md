# The managed-agent backend (Python)

The same travel agent, run as an Anthropic-hosted
[Managed Agent](https://platform.claude.com/docs/en/managed-agents) instead of a
Cloudflare Worker, and written in Python. It speaks the same wire protocol, so
the web app cannot tell the difference — which is the point being made.

```bash
cd backends/claude-managed-agent
pip install -e '.[sdk,dev]'
export ANTHROPIC_API_KEY=sk-ant-...

# The agent's tools are this project's MCP server, so Anthropic needs a public
# URL to call. Deploy the Worker first.
python -m travel_agent.setup_agent --mcp-url https://<your-worker>.workers.dev/mcp
python -m travel_agent.server            # http://127.0.0.1:8788
```

Then point the front end at it:

```bash
VITE_API_ORIGIN=http://127.0.0.1:8788 npm run dev:web
```

## What is actually different

|  | `apps/worker` | here |
|---|---|---|
| The tool loop | we run it | Anthropic runs it |
| The system prompt | assembled per request | uploaded once, versioned |
| Conversation state | a Durable Object per trip | the managed session |
| Tools | execute inside the Worker | the MCP server, called by Anthropic |
| Language | TypeScript | Python |
| Where it runs | Cloudflare's edge | anywhere Python 3.10+ runs |

Everything above the loop is identical. Text arrives, the stream splitter
separates prose from `<a2ui>` blocks, a compiler turns those into surfaces. That
is a property of the model's output, not of where the loop runs — which is why
`express.py` is a close mirror of the TypeScript `ExpressStreamParser`.

## About the compiler

This is the part worth reading before you assume the Python path is the simple
one.

The obvious choice is Google's own `a2ui-agent-sdk`, and this backend will use
it. But the **published wheel is behind the current Express grammar**: 0.5.0
rejects `Text("Hi", variant="h3")` — keyword arguments — which is exactly what
the generated skills teach and what a current model writes. It also returns a
single v1.0 envelope rather than the v0.9.1 message list this project uses.

So `express.py` has two implementations and picks between them:

| Backend | What it is | When it is used |
|---|---|---|
| `sdk` | `a2ui-agent-sdk`, called directly | when it compiles a keyword-argument program — probed at startup, not guessed from a version number |
| `service` | `POST /api/compile` on the deployed Worker | otherwise |

The `service` path is not a fallback to something lesser: it is the TypeScript
compiler this project ships, which the parity suite diffs against the reference
implementation on twenty cases. "Not the SDK" does not mean "not the reference
behaviour".

Force one with `--compiler sdk` or `--compiler service`. When Google publishes a
current wheel, `auto` will start choosing `sdk` on its own and this section gets
shorter.

```bash
python -m travel_agent.server --compiler service --compile-service https://<your-worker>.workers.dev
```

## Agent once, session per run

An agent is a persisted, versioned object: sessions pin to a version, so
changing the prompt is an **update** that bumps the version, not a new agent.

```bash
python -m travel_agent.setup_agent --update
python -m travel_agent.setup_agent --skill express-modular --update
```

`setup_agent.py` is the only module that calls `agents.create`; `server.py` only
ever reads the id out of `.agent.json` (gitignored).

## The loop this closes

The agent's only tools are the `travel-a2ui` MCP server this repository deploys:

```
browser → server.py → Anthropic (runs the loop)
                          │
                          └── MCP call → the deployed Worker → A2UI payload
                          ↓
                   agent.mcp_tool_result
                          ↓
                   server.py → browser → rendered
```

Surfaces arrive two ways and both are handled: as an A2UI payload inside an MCP
tool result, and as Express inside the model's own prose when it uses
`render_a2ui_express`.

The sandbox toolset (`agent_toolset_20260401` — bash, file operations) is
deliberately **not** configured. This agent has no reason to run code, and a
tool an agent cannot reach is a tool it cannot misuse.

## The compiler, as a service

This backend also exposes the endpoints it consumes, so anything that can POST
can speak Express without shipping a parser:

```bash
curl -s localhost:8788/api/compile -H 'content-type: application/json' \
  -d '{"source":"root = Text(\"Hi\", variant=\"h3\")","surfaceId":"demo"}'

curl -s localhost:8788/api/decompile -H 'content-type: application/json' \
  -d '{"messages":[ … ]}'
```

The Worker exposes the same two routes. Same contract, two implementations.

## The API key

Same policy as the Worker: the `x-anthropic-key` header if the browser sent one,
otherwise `ANTHROPIC_API_KEY`. Never stored, never logged, never in a URL.

## Tests

```bash
python -m pytest tests -q

# Also exercise the compile service against a running Worker:
COMPILE_SERVICE=http://127.0.0.1:8787 python -m pytest tests -q
```

The streaming splitter is tested hard, because it is the only substantial logic
here that is not delegated: sentinels split across chunks, partial trees, a
truncated tail swallowed mid-stream and reported at the end, and the batching a
network-backed compiler needs.

## Limits worth knowing

- The conversation-id → session-id map is in memory. The durable half already
  lives in the managed session; persist this map if a conversation should
  survive a restart of *this* process.
- There is no `usage` event — the managed session reports cost through its own
  APIs rather than per turn, so the app's token counter stays at zero here.
- `.agent.json` is per checkout. In a real deployment, put the agent id in
  configuration and provision it from a version-controlled manifest with the
  `ant` CLI.
