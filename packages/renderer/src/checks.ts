/**
 * Client-side validation.
 *
 * A check is `{condition: {call, args}, message}` hanging off the component it
 * guards. The host runs it locally so the user finds out about a bad email
 * before a round trip to the model, not after.
 *
 * Errors are computed on every render but only *shown* once a field has been
 * touched — telling someone their empty form is invalid before they have typed
 * anything is noise, not help.
 */

import type { Json, JsonObject } from '@travel-a2ui/express';

import { resolve, type ResolveScope } from './binding.js';
import { callFunction } from './functions.js';

export interface CheckResult {
  ok: boolean;
  errors: string[];
}

const EMPTY: CheckResult = { ok: true, errors: [] };

export function evaluateChecks(checks: Json | undefined, scope: ResolveScope): CheckResult {
  if (!Array.isArray(checks) || checks.length === 0) return EMPTY;

  const errors: string[] = [];
  for (const raw of checks) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const rule = raw as JsonObject;
    const condition = rule['condition'];
    if (!condition || typeof condition !== 'object' || Array.isArray(condition)) continue;

    const call = (condition as JsonObject)['call'];
    if (typeof call !== 'string') continue;

    const args = ((condition as JsonObject)['args'] ?? {}) as JsonObject;
    const resolved: JsonObject = {};
    for (const [key, value] of Object.entries(args)) resolved[key] = resolve(value, scope) ?? null;

    if (callFunction(call, resolved) !== true) {
      const message = rule['message'];
      errors.push(typeof message === 'string' && message ? message : `${call} check failed`);
    }
  }

  return errors.length === 0 ? EMPTY : { ok: false, errors };
}
