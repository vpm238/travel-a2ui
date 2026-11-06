// The agent guide at its first published address, kept so links to it work.
// `agent.md` beside it is the canonical one.

import type { APIRoute } from 'astro';
import { tourPrompt } from '../../markdown';

export const GET: APIRoute = () =>
  new Response(tourPrompt, { headers: { 'content-type': 'text/markdown; charset=utf-8' } });
