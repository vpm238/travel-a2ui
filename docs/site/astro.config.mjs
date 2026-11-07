// The A2UI quickstart, as a Starlight site.
//
// Starlight because that is what the A2UI documentation is built with, so this
// page can move into `docs/site` in the A2UI repository as a content file and
// a handful of components, with nothing to translate.
//
// Where it is served from is configuration, not code:
//
//   DOCS_SITE  the origin, used for every absolute link an agent is handed
//   DOCS_BASE  the path it is mounted under
//
// The defaults are this repository's deployment, where the Cloud Run service
// that runs the demo also serves the quickstart at /docs.

import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const site = process.env.DOCS_SITE ?? 'https://travel-a2ui-vy7stnte2a-uc.a.run.app';
const base = process.env.DOCS_BASE ?? '/docs';

export default defineConfig({
  site,
  base,
  trailingSlash: 'ignore',
  integrations: [
    starlight({
      title: 'A2UI Quickstart',
      description:
        'Run a real A2UI app, watch its messages on the wire, and learn the core concepts in working code, with your coding agent or on your own.',
      logo: { src: './src/assets/logo.svg', replacesTitle: false },
      social: [
        { icon: 'github', label: 'Travel A2UI on GitHub', href: 'https://github.com/vpm238/travel-a2ui' },
      ],
      customCss: ['./src/styles/custom.css'],
      components: {
        // The title, plus the actions an agent-friendly docs page carries:
        // copy the page as Markdown, view it raw, open it in a chat assistant.
        PageTitle: './src/components/PageTitle.astro',
      },
      head: [
        // Where an agent finds the machine-readable version of the site.
        { tag: 'link', attrs: { rel: 'help', type: 'text/plain', href: `${base}/llms.txt` } },
      ],
      sidebar: [
        {
          label: 'Get started',
          items: [
            { label: 'Quickstart', slug: 'quickstart' },
            { label: 'Python + React', slug: 'quickstart/react' },
            { label: 'Python + Flutter', slug: 'quickstart/flutter' },
            { label: 'Python + React + Flutter', slug: 'quickstart/both' },
          ],
        },
        { label: 'Learn', items: [{ label: 'How A2UI works', slug: 'concepts' }] },
        { label: 'Keep going', items: [{ label: 'Partner & consultant demos', slug: 'ecosystem/partners' }] },
      ],
      lastUpdated: false,
      pagination: true,
    }),
  ],
});
