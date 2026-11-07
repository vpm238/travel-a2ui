// What a coding agent follows to set up the mobile app (Python + Flutter).

import type { APIRoute } from 'astro';
import { guide } from '../../../prompts/guides';

export const GET: APIRoute = () =>
  new Response(guide('mobile'), { headers: { 'content-type': 'text/markdown; charset=utf-8' } });
