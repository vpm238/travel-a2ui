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

> A quickstart for A2UI on web and mobile, built on Travel A2UI: one Python agent server, a React web client and a Flutter mobile client that draw the same A2UI messages. It sets up each piece locally, server first, then React, then Flutter, explains the catalog, messages, data binding, renderers and actions as each starts working, and deploys to Cloud Run in one click. No API key is needed to begin.

If you are a coding agent asked to give someone the A2UI quickstart, fetch the agent guide below and follow it.

## Agent guide

- [A2UI quickstart: instructions for coding agents](${absolute(PROMPT_PATH)}): the steps to set up the Python server, the React client and the Flutter client, what to explain at each, and the one-click deploy

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
