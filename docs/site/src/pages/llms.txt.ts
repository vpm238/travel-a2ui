// `llms.txt`: the map of this site for a language model, per llmstxt.org.
// A title, a one-paragraph summary, then links to the Markdown versions.

import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { absolute, A2UI, PROMPT_MOBILE, PROMPT_PATH, PROMPT_WEB, REPO } from '../site';

export const GET: APIRoute = async () => {
  const pages = (await getCollection('docs'))
    .filter((entry) => entry.id !== 'index' && entry.id !== '')
    .sort((a, b) => (a.id === 'quickstart' ? -1 : b.id === 'quickstart' ? 1 : a.id.localeCompare(b.id)));

  const body = `# A2UI Quickstart

> A quickstart for A2UI on web and mobile, built on Travel A2UI: one Python agent server, a React web client and a Flutter mobile client that draw the same A2UI messages. It runs in three commands (Python + React for web, Python + Flutter for mobile, or both), or from one prompt to a coding agent. The step-by-step quickstart then explains, with screenshots and real output, the core pieces and parent and child components, which parts of the screen are A2UI and which are app code (the catalog), how agent skills are generated from the catalog, agent output (the Express DSL) versus A2UI messages and the MessageProcessor, and the renderers A2UI has.

If you are a coding agent asked to give someone the A2UI quickstart, fetch an agent guide below and follow it.

## Agent guides

- [Web app (Python + React)](${absolute(PROMPT_WEB)}): set it up in three commands, then explain how A2UI works with it open
- [Mobile app (Python + Flutter)](${absolute(PROMPT_MOBILE)}): the same, with the Flutter client
- [Either](${absolute(PROMPT_PATH)}): asks which app to set up first

## Pages

${pages.map((entry) => `- [${entry.data.title}](${absolute(`${entry.id}.md`)})${entry.data.description ? `: ${entry.data.description}` : ''}`).join('\n')}

## Source

- [Travel A2UI repository](${REPO}): the app the quickstart sets up
- [All pages in one file](${absolute('llms-full.txt')})

## Optional

- [A2UI documentation](${A2UI.home})
- [A2UI v1.0 specification](${A2UI.spec})
`;
  return new Response(body, { headers: { 'content-type': 'text/plain; charset=utf-8' } });
};
