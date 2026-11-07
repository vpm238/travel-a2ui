# Working in this repository

Travel A2UI is a sample app built on [A2UI](https://a2ui.org): a trip planner
whose agent answers with an interface (flight cards, date pickers, a live trip
panel) drawn by a React client and a Flutter client from the same messages.

**If the person wants to learn A2UI or be shown around this code**, follow
the guided tour in [`docs/site/src/prompts/quickstart.md`](docs/site/src/prompts/quickstart.md).
It is written for a coding agent: one step at a time, running things and
explaining each A2UI concept where it can be seen working. It is also published
at https://travel-a2ui-vy7stnte2a-uc.a.run.app/docs/quickstart/agent.md.

## Set up, run, test

```bash
npm run setup                     # installs, regenerates, builds, tests; creates .venv
source .venv/bin/activate
uvicorn travel_a2ui.doors.http:app --port 8080 --app-dir apps/server/src
```

The app is at http://127.0.0.1:8080. With no Gemini key, the Catalog and Wire
tabs and the recorded sample trip still work. For a whole turn with no key, run
the scripted server: `GEMINI_API_KEY=scripted python tools/e2e/scripted_server.py 8130`.

| Check | Command |
| --- | --- |
| Server tests | `cd apps/server && python -m pytest -q` |
| Client tests | `npm test` |
| Types | `npm run typecheck` |
| Generated files are current | `npm run check` |
| Browser end-to-end (needs the scripted server) | `npm run e2e` |
| Flutter | `cd renderers/flutter && flutter analyze && flutter test` |
| The quickstart site | `cd docs/site && npm ci && npm run build` |

## Things to know before editing

- **Generated files are generated.** `catalogs/a2ui-travel/catalog.json` comes
  from `scripts/build_catalog.py`; `skills/` from `scripts/build_skills.py`
  (the SDK's `SkillGenerator` over the server's processor); the Catalog tab's
  reference and the Flutter test fixtures from `scripts/build_catalog_reference.py`
  and `scripts/build_fixtures.py`. Edit the source, run `npm run generate`, and
  `npm run check` fails if they drift.
- **The worked examples are source.** `catalogs/a2ui-travel/examples/*.json`
  are A2UI JSON, one turn per file; the SDK decompiles them for the prompt and
  the skills, and `apps/server/tests/test_examples.py` validates them.
- **The UI is agent-driven.** Every surface is composed by the model from the
  catalog and its macros (`brain/macros.py`, templates over data roots). The
  server only supplies data (`updateDataModel` for the roots a surface binds)
  and checks each message against a mirror of the renderer; a refused block
  goes back to the model, never rewritten. Do not hard-code screens in a client
  or compose surfaces on the server; add or change a catalog component or a
  macro instead.
- **Renderer → agent is A2UI v1.0.** Presses and errors are v1.0 action and
  error messages, and every request carries `a2uiRendererCapabilities` and
  `a2uiRendererDataModel`. The wire format is in `docs/transport.md`.
- **The server's two halves.** `apps/server/src/travel_a2ui/brain/` decides
  what happens; `doors/` is transport: the typed door (`http.py`, SSE, and
  `interactions/`) and the voice door (`live.py`, a WebSocket). Doors import
  the brain, never each other.
- **Official SDKs.** Rendering is `@a2ui/react` and `@a2ui/web_core` on the
  web and `a2ui_flutter` in Flutter; parsing, validating and generating skills
  is the A2UI Python agent SDK (`A2uiRequestProcessor`, `RendererState`,
  `SkillGenerator`). Use them rather than reimplementing protocol logic.
- **Keys stay out of the repo.** A Gemini key belongs in the environment or
  the browser, never in a committed file.
