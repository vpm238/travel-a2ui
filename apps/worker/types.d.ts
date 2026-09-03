/** Markdown and HTML imports arrive as text — see the `rules` block in wrangler.jsonc. */
declare module '*.md' {
  const content: string;
  export default content;
}

declare module '*.html' {
  const content: string;
  export default content;
}
