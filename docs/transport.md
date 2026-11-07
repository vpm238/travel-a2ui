# Transport

What goes over the wire between a client (the React app, the Flutter app, or
anything else that renders A2UI) and this agent.

A2UI defines the **messages**: agent→renderer (`createSurface`,
`updateComponents`, `updateDataModel`, `deleteSurface`) and renderer→agent
(an action, an error, the renderer's capabilities and its data model). It does
not define how they travel. This app carries them two ways:

| Door | Transport | Why |
| --- | --- | --- |
| Typed turn | `POST /api/chat`, answered as server-sent events | a turn is one request and a stream of answers |
| Voice call | WebSocket at `/api/voice` | a call is bidirectional for its whole length |

Both carry the same A2UI v1.0 messages in both directions. Nothing in either
transport is a private protocol layered over A2UI: a press is an A2UI action,
an error is an A2UI error, and what a surface holds is an A2UI data model.

---

## Renderer → agent

Every request (and the voice `start` and `press` frames) can carry three
fields beside anything the traveller typed. The server reads them in
[`brain/inbound.py`](../apps/server/src/travel_a2ui/brain/inbound.py) and
validates each one with the A2UI SDK's own v1.0 models
(`a2ui.core.schema.v1_0`). Nothing is defaulted or guessed: a message that does
not validate is reported back as a `warning` event, and the rest of the
request goes ahead.

### `a2ui`: renderer-to-agent messages

A list of A2UI v1.0 messages, each validated as one of:

```jsonc
// A press — `A2uiRendererActionMessage`
{
  "version": "1.0",
  "action": {
    "name": "select_flight",
    "surfaceId": "inline-2",
    "sourceComponentId": "fare-TP2077",
    "timestamp": "2027-04-02T10:14:03.120Z",
    "context": { "id": "TP2077", "price": 412 },
    "userMessage": "TAP Air Portugal TP2077, $412"   // optional
  }
}

// Something the renderer refused — `A2uiRendererErrorMessage`
{
  "version": "1.0",
  "error": {
    "code": "VALIDATION_FAILED",
    "surfaceId": "inline-2",
    "path": "/components/3",
    "message": "…"
  }
}
```

`surfaceId` is required and never filled in by the server. The last action in
the list is the press the turn answers. Errors are told to the model, once, as
`[renderer] <code> on surface "<id>" at <path>: <message>`, so it can redraw
what the renderer could not show.

The web client builds these with `@a2ui/web_core`'s `MessageProcessor`
(`actionHandler` and `errorHandler`). The Flutter client builds them with
`a2ui_core`'s `ActionMessage` and `ErrorMessage`.

### `metadata`: capabilities and the data model

```jsonc
{
  "a2uiRendererCapabilities": {          // A2uiRendererCapabilities
    "1.0": { "supportedCatalogIds": ["https://…/a2ui-travel/catalog.json"] }
  },
  "a2uiRendererDataModel": {             // A2uiRendererDataModel
    "version": "1.0",
    "surfaces": {
      "inline-1": { "trip": { "origin": "LIS", "startDate": "2027-04-12", "travelers": 2 } }
    }
  }
}
```

Both are sent on **every** request, not only with a press, and both come from
the SDK: `getRendererCapabilities({versions: ['1.0']})` and
`getRendererDataModel('1.0')` in `@a2ui/web_core`, and
`getRendererCapabilities(…)` and `getRendererDataModel(version: …)` in
`a2ui_core`.

- **Capabilities** decide which catalogs the agent may draw with: the SDK's
  `resolve_catalogs`, through `Canvas.negotiate`. A renderer that supports
  none of this agent's catalogs gets an `error` event (a voice call gets an
  `error` frame and is closed) rather than a surface it cannot show.
- **The data model** holds only surfaces created with `sendDataModel: true`,
  which is every surface that asks the traveller something. The server diffs
  the reported `trip` against its mirror of what it sent
  (`Canvas.edits`), and what the traveller changed is recorded on the trip
  before the model is asked anything. A press therefore needs no special
  "commit" payload: the answer is already in the data model.

### `surfaces`: what the renderer holds

The surface ids currently on screen. The server keeps a mirror of every
surface it has sent (`brain/ui.py`, `Canvas`), and reconciles it against this
list at the start of each request: a surface the client no longer holds is
forgotten, and a standing surface (`sidebar`, `home`) the client holds but the
server has never drawn is deleted with `deleteSurface`. Inline cards get fresh
ids (`inline-1`, `inline-2`, …) numbered past the highest one held.

---

## The typed turn: `POST /api/chat`

### Request

```jsonc
{
  "sessionId": "s-…",
  "message": "Lisbon to Madrid, first week of April, two of us",  // omitted for a press
  "a2ui": [ /* renderer-to-agent messages, above */ ],
  "metadata": { /* capabilities and data model, above */ },
  "surfaces": ["inline-1", "sidebar"],
  "surface": "inline",               // or "sidebar" / "home": which surface this turn draws
  "resume": { "interactionId": "…", "trip": { … }, "setup": "…" },
  "client": { "today": "2027-04-01", "locale": "en-GB" }
}
```

The Gemini key goes in the `x-goog-api-key` header, or the server uses its own
`GEMINI_API_KEY`. It is never stored.

- `resume` is the receipt from the last turn's `resume` event, handed back
  unread. The client is the one party present for every turn, so it carries
  the thread, and any server instance can answer it.
- `client.today` is the traveller's calendar day. The server runs in UTC and
  "tomorrow" is the traveller's tomorrow. Where they fly from is asked in a
  surface, never inferred from a locale or a time zone.

### Response: server-sent events

Each event is one `data: {json}` frame. In the order they usually arrive:

| `type` | Fields | Meaning |
| --- | --- | --- |
| `session` | `sessionId` | the session this turn belongs to |
| `warning` | `message` | something in the request was not read (see above) |
| `start` | `model`, `surfaceId` | the turn has started; `surfaceId` is the inline card it may create |
| `text` | `delta`, `round` | prose, streamed |
| `ui` | `surfaceId`, `messages`, `done` | A2UI v1.0 agent-to-renderer messages, one per event, for `MessageProcessor.processMessages` |
| `ui_error` | `message`, `source`, `express?` | a block the server could not accept; the model is told and redraws it |
| `retry` | `reason` | the model is being asked once more (a rejected block, an unanswerable surface, a promise with nothing drawn) |
| `served_by` | `model` | the chosen model was busy and another answered |
| `restart` | `reason` | the stream failed part-way and the turn is starting over on the standby model |
| `tool` | `name`, `input`, `status` | a lookup started |
| `tool_result` | `name`, `result`, `isError` | its result (what the model sees; rows reach the screen as data) |
| `trip` | `trip` | the trip record after this step |
| `usage` | token counts | per model round |
| `resume` | `interactionId`, `trip`, `setup` | the receipt to send back next turn |
| `timing` | `ms` | where the time went (`firstSurface`, `firstWord`, `tool:<name>`) |
| `error` | `message`, `retryable` | the turn failed |
| `done` | `stopReason` | the turn is over (`"host"` when the server answered a press itself) |

`ui` events are A2UI exactly as the renderer takes it. Every message has
already been applied to the server's mirror of the renderer
(`a2ui.utils.RendererState`, through the SDK's `validate_payload`), so a
message that would not apply is never sent.

What the model writes and what goes over the wire differ in one way: the
model writes **A2UI Express** with this app's macros (`Flights(...)`,
`Trip(...)`), and the server expands them with the SDK's `MacroExpander`
into the full catalog before sending. The renderer only ever sees plain
v1.0 components from the catalog it negotiated.

After a turn that settles a destination, if the client holds no `sidebar`,
the same stream carries a short panel turn: the model draws the panel once, and
from then on it is kept current by `updateDataModel` alone.

---

## The voice call: WebSocket `/api/voice?sessionId=…`

The session id goes on the URL. A call is the same conversation as the typed
one: the same trip, the same mirror of the renderer, the same panel.

### Client → server

| `type` | Fields | Meaning |
| --- | --- | --- |
| `start` | `apiKey?`, `client`, `surfaces`, `metadata`, `model?`, `voice?` | first frame; binds the call. `surfaces` and `metadata` are as above |
| `audio` | `data` | base64 PCM, 16 kHz mono, from the microphone |
| `audio_end` | — | the microphone stopped; the model answers now rather than waiting for silence |
| `text` | `text` | something typed during the call |
| `press` | `a2ui`, `metadata` | a press during the call: the same v1.0 action message and metadata a typed turn carries |
| `end` | — | hang up |

### Server → client

| `type` | Fields | Meaning |
| --- | --- | --- |
| `ready` | `model`, `contract` | the Live API accepted the setup; sent only then, so a bad key never looks bound |
| `audio` | `data` | base64 PCM from the model |
| `transcript` | `text`, `who` | what was heard (`you`) or said (`agent`) |
| `tool` | `name`, `input` | a tool call, including `render_a2ui_express` |
| `ui` | `surfaceId`, `messages`, `done` | A2UI v1.0 messages, as in a typed turn |
| `trip` | `trip` | the trip after a change |
| `interrupted` | — | the traveller talked over the model |
| `turn_end` | — | the model finished its turn |
| `error` | `message` | what the upstream said, so a rejected key reads as one |

In a call the model draws through a tool, `render_a2ui_express`, because the
Live API has no text channel to stream Express on. Each call to it is read by
the same SDK processor and the same mirror as a typed turn, and each block
with no `surface(...)` line becomes a new `voice-N` card. A press is recorded
on the trip before the model hears about it, exactly as in a typed turn, and is
then told to the model as a line of text, because the Live API has no
equivalent of an A2UI action.

---

## Other endpoints

| Endpoint | What it returns |
| --- | --- |
| `GET /api/meta` | models, skills, catalog id, whether the server holds a key |
| `GET /api/catalog` | the travel catalog, as served to renderers |
| `POST /api/express` | `{messages}` → `{express}`: A2UI decompiled to Express by the SDK, for the Wire tab |
| `POST /api/warm` | starts the conversation before the first message, so the first surface is not the slow one |
| `GET /api/session`, `POST /api/session/reset` | the session's trip, and starting over |
| `GET /healthz` | liveness |
