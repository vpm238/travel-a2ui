// Every page and the tour prompt in one file, for an agent that would rather
// read once than follow links.

import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { toMarkdown, tourPrompt } from '../markdown';

export const GET: APIRoute = async () => {
  const pages = (await getCollection('docs'))
    .filter((entry) => entry.id !== 'index' && entry.id !== '')
    .sort((a, b) => (a.id === 'quickstart' ? -1 : b.id === 'quickstart' ? 1 : a.id.localeCompare(b.id)));
  const body = [
    ...pages.map((entry) => toMarkdown(entry.data.title, entry.data.description, entry.body ?? '')),
    tourPrompt,
  ].join('\n\n---\n\n');
  return new Response(body, { headers: { 'content-type': 'text/plain; charset=utf-8' } });
};
