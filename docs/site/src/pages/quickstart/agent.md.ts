// The agent guide, raw: the one URL the quickstart prompt hands an agent.

import type { APIRoute } from 'astro';
import { tourPrompt } from '../../markdown';

export const GET: APIRoute = () =>
  new Response(tourPrompt, { headers: { 'content-type': 'text/markdown; charset=utf-8' } });
