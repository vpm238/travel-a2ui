// Every URL the quickstart hands out, in one place.
//
// Agents are given absolute URLs (a prompt pasted into a terminal has no page
// to be relative to), so they are built from the configured site and base.
// The links into the A2UI documentation are here too, so moving this page into
// the A2UI repository means editing this file, not hunting through prose.

const site = (import.meta.env.SITE ?? '').replace(/\/$/, '');
const base = (import.meta.env.BASE_URL ?? '/').replace(/\/$/, '');

/** A path inside this site, as an absolute URL. */
export const absolute = (path: string) => `${site}${base}/${path.replace(/^\//, '')}`;

/** A path inside this site, relative to the origin. */
export const local = (path: string) => `${base}/${path.replace(/^\//, '')}`;

export const REPO = 'https://github.com/vpm238/travel-a2ui';
export const LIVE_DEMO = 'https://travel-a2ui-vy7stnte2a-uc.a.run.app';

/** The prompt a coding agent follows, served raw. */
export const PROMPT_PATH = 'quickstart/prompt.md';

/** Where the quickstart ends: the partner and consultant demos. */
export const PARTNERS_PATH = 'ecosystem/partners/';
export const PARTNERS = local(PARTNERS_PATH);

export const BUILD_YOUR_OWN = `${REPO}#build-one-of-your-own`;
export const FLUTTER_DEMO = `${LIVE_DEMO}/flutter/`;

/** The A2UI documentation, one entry per concept the tour teaches. */
export const A2UI = {
  home: 'https://a2ui.org',
  overview: 'https://a2ui.org/concepts/overview/',
  messages: 'https://a2ui.org/reference/messages/',
  catalogs: 'https://a2ui.org/concepts/catalogs/',
  ownCatalog: 'https://a2ui.org/guides/defining-your-own-catalog/',
  dataBinding: 'https://a2ui.org/concepts/data-binding/',
  actions: 'https://a2ui.org/concepts/actions/',
  spec: 'https://a2ui.org/specification/v1.0-a2ui/',
  renderers: 'https://a2ui.org/ecosystem/renderers/',
  glossary: 'https://a2ui.org/concepts/glossary/',
};

/** The one-line prompt to paste into any agent that can fetch a URL. */
export const bootstrapPrompt = () =>
  `Fetch ${absolute(PROMPT_PATH)} and follow it: guide me step by step through cloning, running and touring the Travel A2UI demo, and explain A2UI's core concepts as we go.`;
