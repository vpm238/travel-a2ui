/**
 * A fingerprint of what a Gemini Live session gets bound to.
 *
 * The Live API has no server-side agent object to create and keep. A session is
 * whatever its opening `setup` frame says it is: a model, a system instruction
 * built from the catalog's skill, and a set of tool declarations. So
 * "instantiating the Live agent" is a real handshake — open the socket, send
 * that frame, wait for the API to accept it — and the thing worth remembering
 * afterwards is *which contract it accepted*.
 *
 * That is what this stamp is. It covers exactly the four things the setup frame
 * carries, and nothing else:
 *
 *   the catalog        what components exist
 *   the skill          how to compose them, generated from that catalog
 *   the tools          what the model may call
 *   the model id       who is answering
 *
 * Deliberately *not* the full system prompt: that one interpolates today's date
 * and the trip so far, so hashing it would expire every session and every
 * midnight, which teaches a user to click through the warning.
 *
 * Change any of the four and every client's stored instantiation stops matching
 * on its next `/api/meta`, and the traveller is asked to initialise again with
 * their key. Add a component tomorrow and yesterday's Live sessions do not
 * quietly keep composing against a catalog that no longer exists.
 */

import { CATALOG } from './agent.js';
import { skillText } from './skills.js';
import { VOICE_MODEL, voiceTools } from './voice.js';

/**
 * FNV-1a, 32-bit.
 *
 * Not a security boundary — nobody is attacking a cache key — so the bar is
 * "changes when the input changes", which this clears for inputs that differ
 * anywhere. The length is mixed in as well, since FNV alone is weakest against
 * inputs of the same shape, and a catalog edit that swaps two equal-length
 * strings is exactly that shape.
 */
function fingerprint(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  const digest = (hash >>> 0).toString(16).padStart(8, '0');
  return `${digest}${input.length.toString(36)}`;
}

let cached: string | null = null;

/**
 * The current contract stamp. Computed once — none of its inputs can change
 * without a new deployment, which is a new isolate.
 */
export function contractStamp(): string {
  if (cached) return cached;

  const parts = [
    JSON.stringify(CATALOG),
    // The voice relay builds its prompt from this variant, so these are the
    // instructions that actually reach a Live session.
    skillText('express-monolithic'),
    JSON.stringify(voiceTools()),
    VOICE_MODEL,
  ];

  cached = fingerprint(parts.join(''));
  return cached;
}

/**
 * How long an instantiation stays good, absent a contract change.
 *
 * A day. The stamp already catches the case that matters — the deployment's
 * contract moved underneath a stored session — so this is only a backstop for
 * the cases a stamp cannot see: a key revoked upstream, a quota that has since
 * run out, an account change. Long enough not to nag, short enough that a
 * session nobody has touched since yesterday is re-checked rather than assumed.
 */
export const INSTANTIATION_MAX_AGE_MS = 24 * 60 * 60 * 1000;
