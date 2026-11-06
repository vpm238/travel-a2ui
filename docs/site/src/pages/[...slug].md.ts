// Every page's Markdown twin, at the page's own path with `.md` on the end:
// `/quickstart/` is also `/quickstart.md`. This is what "Copy page" and
// "View as Markdown" serve, and what `llms.txt` lists.

import type { APIRoute, GetStaticPaths } from 'astro';
import { getCollection, type CollectionEntry } from 'astro:content';
import { toMarkdown } from '../markdown';

export const getStaticPaths: GetStaticPaths = async () =>
  (await getCollection('docs')).map((entry) => ({
    params: { slug: entry.id === '' ? 'index' : entry.id },
    props: { entry },
  }));

export const GET: APIRoute = ({ props }) => {
  const { entry } = props as { entry: CollectionEntry<'docs'> };
  return new Response(toMarkdown(entry.data.title, entry.data.description, entry.body ?? ''), {
    headers: { 'content-type': 'text/markdown; charset=utf-8' },
  });
};
