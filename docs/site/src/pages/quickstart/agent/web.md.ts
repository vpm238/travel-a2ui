// What a coding agent follows to set up the web app (Python + React).

import type { APIRoute } from 'astro';
import { guide } from '../../../prompts/guides';

export const GET: APIRoute = () =>
  new Response(guide('web'), { headers: { 'content-type': 'text/markdown; charset=utf-8' } });
