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
  from `scripts/build_catalog.py`. `skills/` and the compiled examples come
  from the catalog. Edit the source, run `npm run generate`, and `npm run
  check` fails if they drift.
- **The UI is agent-driven.** What a surface shows is composed by the agent
  from the catalog. Do not hard-code screens in a client; add or change a
  catalog component instead.
- **The server's two halves.** `apps/server/src/travel_a2ui/brain/` decides
  what happens; `doors/` is transport (HTTP, SSE, the voice WebSocket). Doors
  import the brain, never each other.
- **Official SDKs.** Rendering is `@a2ui/react` and `@a2ui/web_core` on the
  web and `a2ui_flutter` in Flutter; compiling and validating is the A2UI
  Python agent SDK. Use them rather than reimplementing protocol logic.
- **Keys stay out of the repo.** A Gemini key belongs in the environment or
  the browser, never in a committed file.
