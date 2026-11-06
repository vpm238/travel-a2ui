// The tour prompt, raw, at a stable URL: what a coding agent is pointed at.

import type { APIRoute } from 'astro';
import { tourPrompt } from '../../markdown';

export const GET: APIRoute = () =>
  new Response(tourPrompt, { headers: { 'content-type': 'text/markdown; charset=utf-8' } });
