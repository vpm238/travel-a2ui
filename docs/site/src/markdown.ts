// Every page, as Markdown an agent can read.
//
// The pages are MDX: Markdown plus a few Starlight components. An agent
// handed the source would read import lines and JSX; an agent handed the HTML
// would read the navigation and the theme picker. So each page is turned back
// into plain Markdown from its own source, here, at build time. The page and
// its Markdown twin cannot drift apart, because there is only one of them.
//
// This handles exactly the components these pages use. A page that uses a new
// one fails the build (see `leftover` below) instead of shipping raw JSX.

import * as site from './site';
import { guide } from './prompts/guides';

const { absolute, PROMPT_PATH } = site;

/** The screenshots, by file name, as the URLs the build gave them. */
const images = Object.fromEntries(
  Object.entries(
    import.meta.glob<{ default: { src: string } }>('./assets/**/*.{png,jpg,svg}', { eager: true }),
  ).map(([path, module]) => [path.split('/').pop()!, module.default.src]),
);

const origin = (import.meta.env.SITE ?? '').replace(/\/$/, '');

/** `A2UI.messages`, `PARTNERS`: an identifier from `site.ts`, resolved. */
function resolve(expression: string): string {
  const value = expression
    .trim()
    .split('.')
    .reduce<unknown>((object, key) => (object as Record<string, unknown>)?.[key], site);
  if (typeof value !== 'string') throw new Error(`Cannot resolve {${expression}} in a page.`);
  return value.startsWith('/') ? `${origin}${value}` : value;
}

/** An attribute's value, whether written `name="text"` or `name={IDENT}`. */
function attribute(tag: string, name: string): string | undefined {
  const quoted = tag.match(new RegExp(`${name}="([^"]*)"`));
  if (quoted) return quoted[1];
  const expression = tag.match(new RegExp(`${name}=\\{([^}]*)\\}`));
  return expression ? resolve(expression[1]) : undefined;
}

const AGENT_PROMPT = `## Quickstart with your coding agent

Copy one prompt into Claude Code, Gemini CLI, Codex, Cursor or any agent that can read a web page. The link holds the full instructions: your agent runs three commands, then explains how A2UI works with the app open.

${site.QUICKSTART_PROMPTS.map((entry) => `**${entry.app} (${entry.stack})**\n\n\`\`\`text\n${entry.prompt}\n\`\`\``).join('\n\n')}`;

const ARCHITECTURE = `\`\`\`text
 React client (web)                 Flutter client (mobile)
 @a2ui/react · @a2ui/web_core       a2ui_flutter · a2ui_core
 renderers/react/ · apps/web/       renderers/flutter/
              \\                      /
   A2UI messages over SSE ↓      ↑ actions
                \\                  /
            Python agent server  (apps/server/src/travel_a2ui/)
            agent loop, tools, trip, macros, A2UI agent SDK
                         |
                       Gemini
\`\`\``;

/** What every Markdown page tells an agent first, as parallel.ai's docs do. */
const FOR_AGENTS = `> For AI agents: to give someone the A2UI quickstart, follow ${absolute(PROMPT_PATH)}. A documentation index is at ${absolute('llms.txt')}, and the full text of every page is at ${absolute('llms-full.txt')}. Any page is available as Markdown by adding \`.md\` to its URL.`;

const TURN_FLOW = `1. **You** type a message, or press something on a surface.
2. **The agent's model** decides what to show and writes it in A2UI Express, taught by skills generated from the catalog.
3. **The A2UI SDK** compiles the Express to A2UI JSON and checks it against the catalog, while the model is still writing.
4. **The renderer** (React or Flutter) draws each component with its own widgets, bound to the surface's data model.

A press on what the renderer drew goes back to the agent as an \`action\`, which starts the next turn.`;

export function toMarkdown(title: string, description: string | undefined, body: string): string {
  let text = body
    // Imports are for the page, not the reader.
    .replace(/^import .*$\n?/gm, '')
    .replace(/<AgentPrompt\s*\/>/g, AGENT_PROMPT)
    .replace(/<TurnFlow\s*\/>/g, TURN_FLOW)
    .replace(/<ArchDiagram\s*\/>/g, ARCHITECTURE)
    // Asides become block quotes with their title in bold.
    .replace(/<Aside([^>]*)>([\s\S]*?)<\/Aside>/g, (_, attrs: string, inner: string) => {
      const heading = attribute(attrs, 'title');
      const lines = [heading ? `**${heading}**` : '', ...inner.trim().split('\n').map((l) => l.trim())];
      return lines.filter((l, i) => i > 0 || l).map((l) => `> ${l}`.trimEnd()).join('\n');
    })
    // Cards become headings; link cards become links.
    .replace(/^[ \t]*<Card(\s[^>]*)>([\s\S]*?)<\/Card>/gm, (_, attrs: string, inner: string) =>
      `\n### ${attribute(attrs, 'title')}\n\n${inner.trim().replace(/\n\s+/g, '\n')}\n`,
    )
    .replace(/<LinkCard([\s\S]*?)\/>/g, (_, attrs: string) => {
      const description = attribute(attrs, 'description');
      return `- [${attribute(attrs, 'title')}](${attribute(attrs, 'href')})${description ? `: ${description}` : ''}`;
    })
    // A caption is an italic line; a link inside it is a Markdown link.
    .replace(/<p class="shot-caption">([\s\S]*?)<\/p>/g, (_, inner: string) =>
      `*${inner.trim().replace(/\s*\n\s*/g, ' ')}*`,
    )
    .replace(/<code>([^<]*)<\/code>/g, '`$1`')
    .replace(/<a href=\{([^}]*)\}>([^<]*)<\/a>/g, (_, href: string, label: string) => `[${label}](${resolve(href)})`)
    .replace(/<a href="([^"]*)">([^<]*)<\/a>/g, '[$2]($1)')
    // Wrappers that only arrange things on screen. Each leaves a blank line,
    // so what was inside stays its own paragraph.
    .replace(/^[ \t]*<\/?(Steps|CardGrid|Tabs)>[ \t]*$/gm, '\n')
    .replace(/^[ \t]*<div class="shots">[ \t]*$|^[ \t]*<\/div>[ \t]*$/gm, '\n')
    .replace(/^[ \t]+(- \[)/gm, '$1')
    // Screenshots point at the published image.
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt: string, src: string) => {
      const file = src.split('/').pop()!;
      return images[file] ? `![${alt}](${origin}${images[file]})` : match;
    })
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  const leftover = text.match(/<[A-Z][A-Za-z]*[\s/>]/);
  if (leftover) throw new Error(`"${title}" uses a component the Markdown export does not handle: ${leftover[0]}`);

  return `${FOR_AGENTS}\n\n# ${title}\n\n${description ? `> ${description}\n\n` : ''}${text}\n`;
}

/** The general agent guide, which asks which app to set up. */
export const tourPrompt = guide('any');
