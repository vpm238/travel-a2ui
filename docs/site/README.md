# The A2UI quickstart

A [Starlight](https://starlight.astro.build) site with one job: get someone
from nothing to understanding A2UI by running this repository. It is published
at https://travel-a2ui-vy7stnte2a-uc.a.run.app/docs/ by the same Cloud Run
service that runs the demo.

It is written to move into `docs/site` in the A2UI repository. Starlight is
what the A2UI docs use, so the move is a content file, a few components and
the links in `src/site.ts`.

## What is here

| Path | What it is |
| --- | --- |
| `src/prompts/quickstart.md` | **The tour prompt** a coding agent follows. The single source: the page links to it, and `/quickstart/agent.md` serves it raw (also at `/quickstart/prompt.md`, its first address). |
| `src/content/docs/quickstart.mdx` | The quickstart page: the prompt up top, then the same tour written out with screenshots |
| `src/content/docs/ecosystem/partners.mdx` | Where the quickstart ends. A placeholder for the A2UI partner and consultant demos page. |
| `src/components/AgentPrompt.astro` | The one-line prompt card: `Give me the A2UI quickstart: <agent.md URL>` |
| `src/components/PageTitle.astro` | Starlight's title plus Copy page, View as Markdown, Open in Claude and Open in ChatGPT |
| `src/markdown.ts`, `src/pages/*.ts` | Every page's Markdown twin (`/quickstart.md`), `llms.txt` and `llms-full.txt` |
| `src/site.ts` | Every URL the site hands out, including the links into the A2UI docs |

## Run it

```bash
npm ci
npm run dev        # http://localhost:4321/docs/
npm run build      # dist/, which the app server mounts at /docs
```

`DOCS_SITE` and `DOCS_BASE` set where it is served from. Agents are handed
absolute URLs, so they must match the deployment.

## Agent-friendly, concretely

- One line to paste into any coding agent, carrying one URL. Everything the
  agent needs (modes, learning outcomes, where each lives in the code) is
  behind that URL, so it improves without anyone re-copying a prompt.
- Every Markdown page opens with a note for agents pointing at the guide,
  `llms.txt` and `llms-full.txt`, as parallel.ai's docs do.
- Every page as clean Markdown at its own path plus `.md`, built from the
  page's source so the two cannot drift apart.
- `llms.txt` and `llms-full.txt` at the root of the site.
- The repository's `AGENTS.md` points an agent that opens the code at the same
  tour.
