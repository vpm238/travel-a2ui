"""The doors: the same brain, reachable four ways.

Each module here is one way in. They share the brain entirely — the same
skills, the same tools, the same trip record, the same surface passes — and
differ only in how a request arrives and how the answer is streamed back.

  `interactions`  the Gemini Interactions API. A typed conversation: a message
                  or a press arrives, the loop runs, A2UI streams out over SSE.
                  The reference door, and the one the web app opens by default.
  `live`          the Gemini Live API. A bidirectional audio session Google
                  drives; the traveller can speak or type, and it answers out
                  loud while drawing the same surfaces from the same catalog.
  `plugin`        MCP. Every call is self-contained — no conversation to
                  continue — so a host like Claude can call the travel tools and
                  render the same surfaces inside its own chrome.
  `http`          the FastAPI app that mounts the other three, serves the built
                  clients, and answers `/api/meta` with what this deployment is.

A door owns transport and nothing else. When one of them starts wanting to know
what a trip is, that knowledge belongs in `brain` and the door should be asking
for it.
"""
