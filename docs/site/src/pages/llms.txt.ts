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

> A quickstart for A2UI on web and mobile, built on Travel A2UI: a Python agent server with a React web client and a Flutter mobile client. It teaches the core pieces of A2UI, what is A2UI versus deterministic code (the catalog and macros), how agent skills are generated from the catalog, how agent output (the Express DSL) becomes A2UI messages applied by a MessageProcessor, and which renderers exist. It runs on Gemini by default, on a built-in mock with no key, or explains the code without running it.

If you are a coding agent asked to give someone the A2UI quickstart, fetch the agent guide below and follow it.

## Agent guide

- [A2UI quickstart: instructions for coding agents](${absolute(PROMPT_PATH)}): how to guide a developer through cloning, running and explaining the demo, with the modes, the learning outcomes and where each lives in the code

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
