// `llms.txt`: the map of this site for a language model, per llmstxt.org.
// A title, a one-paragraph summary, then links to the Markdown versions.

import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { absolute, A2UI, PROMPT_PATH, REPO } from '../site';

export const GET: APIRoute = async () => {
  const pages = (await getCollection('docs'))
    .filter((entry) => entry.id !== 'index' && entry.id !== '')
    .sort((a, b) => (a.id === 'quickstart' ? -1 : b.id === 'quickstart' ? 1 : a.id.localeCompare(b.id)));

  const body = `# A2UI Quickstart

> A guided tour of Travel A2UI, a working A2UI app: clone it, run it, watch its A2UI messages on the wire, and learn catalogs, messages, data binding, actions and functions, inference formats and renderers in its code. Most of it needs no API key.

If you are a coding agent asked to give someone the A2UI quickstart, fetch the tour prompt and follow it step by step.

## Tour

- [Tour prompt for coding agents](${absolute(PROMPT_PATH)}): step-by-step instructions for guiding a developer through cloning, running and touring the demo

## Pages

${pages.map((entry) => `- [${entry.data.title}](${absolute(`${entry.id}.md`)})${entry.data.description ? `: ${entry.data.description}` : ''}`).join('\n')}

## Source

- [Travel A2UI repository](${REPO}): the app the tour runs
- [All pages in one file](${absolute('llms-full.txt')})

## Optional

- [A2UI documentation](${A2UI.home})
- [A2UI v1.0 specification](${A2UI.spec})
`;
  return new Response(body, { headers: { 'content-type': 'text/plain; charset=utf-8' } });
};
