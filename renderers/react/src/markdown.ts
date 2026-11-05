/**
 * Markdown for the SDK's `Text`.
 *
 * A2UI 1.0's `Text` is Markdown — a heading is `### Outbound`, not a variant —
 * and `@a2ui/react` renders it with whatever the app puts in `MarkdownContext`.
 * Raw HTML, images and links are off: the spec allows "simple Markdown
 * formatting … without HTML, images, or links", and text the agent writes is
 * not a place to load anything from.
 */

import MarkdownIt from 'markdown-it';

const md = new MarkdownIt({ html: false, linkify: false, typographer: true });
md.disable(['image', 'link', 'autolink']);

/** The SDK's `MarkdownRenderer` contract: Markdown in, HTML out, asynchronously. */
export async function renderMarkdown(source: string): Promise<string> {
  return md.render(source ?? '');
}
