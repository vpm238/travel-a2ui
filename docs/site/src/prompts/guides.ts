// The agent guides, from one source.
//
// `quickstart.md` marks the parts that belong to one app with
// `<!-- only:web -->`, `<!-- only:mobile -->` or `<!-- only:any -->` (several
// may share a block, space separated), closed by `<!-- /only -->`. Each guide
// keeps the blocks that name it: `web`, `mobile`, or `any` for the general
// guide, which asks which app to set up.

import source from './quickstart.md?raw';

export type App = 'web' | 'mobile' | 'any';

const BLOCK = /<!-- only:([a-z ]+) -->\n([\s\S]*?)<!-- \/only -->\n?/g;

export function guide(app: App): string {
  return source
    .replace(BLOCK, (_match, apps: string, body: string) =>
      apps.split(' ').includes(app) ? body : '',
    )
    .replace(/\n{3,}/g, '\n\n');
}
