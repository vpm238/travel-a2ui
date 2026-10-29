/**
 * Resolving values: bindings, dynamic function calls, and list scopes.
 *
 * A component property in A2UI is one of four things, and telling them apart is
 * most of what rendering is:
 *
 *   "Madrid"                               a literal
 *   {"@path": "/trip/city"}                a binding into the data model
 *   {"@call": "formatCurrency", args: {…}} a dynamic value, computed at render
 *   {"event": {…}} / {"functionCall": {…}}  an action, handled on interaction
 *
 * The `@` is A2UI 1.0's reserved prefix, and it exists so that a plain object
 * with a `path` key is ordinary data rather than a directive — which, before
 * 1.0, it could not be. Both spellings are read here: a renderer that only
 * understood the new one would draw nothing at all from a 0.9 agent, and
 * saying "this is a binding" is cheap enough to do twice.
 *
 * Two keys deliberately keep their unprefixed spelling, and the protocol says
 * so: a child-list template's `path` (it sits beside `componentId`, and means
 * "repeat over this" rather than "read this"), and `updateDataModel`'s own
 * `path`, which is a message parameter rather than a binding.
 *
 * Inside a list template, a relative path (`$name` → `{"path": "name"}`)
 * resolves against the current item rather than the model root. That is the
 * only stateful thing about resolution, and it is carried in `scope`.
 */

import type { Json, JsonObject } from '@travel-a2ui/express';

import { readPointer } from './store.js';
import { callFunction } from './functions.js';
import { hasExpression, interpolate, type Lookup } from './interpolate.js';

export interface ResolveScope {
  /** The surface's data model. */
  model: JsonObject;
  /** Pointer to the current list item, or '' at the surface root. */
  itemPointer: string;
}

/** Both spellings of a data binding, newest first. */
const PATH_KEYS = ['@path', 'path'] as const;

/** The pointer a binding names, whichever spelling it arrived in. */
export function pathOf(value: Json | undefined): string | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  for (const key of PATH_KEYS) {
    const found = (value as Record<string, Json>)[key];
    if (typeof found === 'string') return found;
  }
  return undefined;
}

export function isBinding(value: Json | undefined): boolean {
  return pathOf(value) !== undefined && !(value as object & { componentId?: unknown }).componentId;
}

export function isTemplate(
  value: Json | undefined,
): value is { path: string; componentId: string } {
  return (
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    pathOf(value) !== undefined &&
    'componentId' in value
  );
}

export function isCallExpression(value: Json | undefined): value is { call: string; args: Json } {
  return (
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    ('@call' in value || 'call' in value)
  );
}

/** The function a dynamic value names, whichever spelling it arrived in. */
export function callOf(value: Json | undefined): string | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const record = value as Record<string, Json>;
  const named = record['@call'] ?? record['call'];
  return typeof named === 'string' ? named : undefined;
}

export function isAction(
  value: Json | undefined,
): value is { event?: { name: string; context?: JsonObject }; functionCall?: { call: string; args: JsonObject } } {
  return (
    !!value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    ('event' in value || 'functionCall' in value)
  );
}

/** Turns a possibly-relative A2UI path into an absolute JSON Pointer. */
export function absolutePointer(path: string, scope: ResolveScope): string {
  if (path.startsWith('/')) return path;
  if (!path) return scope.itemPointer;
  return scope.itemPointer ? `${scope.itemPointer}/${path}` : `/${path}`;
}

/** Resolves any property value to a concrete one. */
export function resolve(value: Json | undefined, scope: ResolveScope): Json | undefined {
  if (value === null || value === undefined) return value;

  if (Array.isArray(value)) return value.map((item) => resolve(item, scope) ?? null);

  if (typeof value === 'object') {
    const bound = pathOf(value);
    if (bound !== undefined && !(value as { componentId?: unknown }).componentId) {
      return readPointer(scope.model, absolutePointer(bound, scope));
    }
    if (isCallExpression(value)) {
      const args = (value.args ?? {}) as JsonObject;
      const resolved: JsonObject = {};
      for (const [key, argument] of Object.entries(args)) {
        resolved[key] = resolve(argument, scope) ?? null;
      }
      // `formatString` is the one function whose argument is a *template*, not
      // a value: its `${…}` expressions read the data model and call other
      // functions, so it is resolved here, where the model is in scope, rather
      // than in `functions.ts`, which only ever sees resolved arguments.
      const template = resolved['value'] ?? resolved['template'];
      const named = callOf(value) ?? '';
      if (named === 'formatString' && typeof template === 'string' && hasExpression(template)) {
        return interpolate(template, lookupFor(scope));
      }
      return callFunction(named, resolved);
    }
    const out: JsonObject = {};
    for (const [key, item] of Object.entries(value as JsonObject)) {
      out[key] = resolve(item, scope) ?? null;
    }
    return out;
  }

  return value;
}

/** The data model and the catalog functions, as an expression sees them. */
function lookupFor(scope: ResolveScope): Lookup {
  return {
    readPath: (path) => readPointer(scope.model, absolutePointer(path, scope)),
    call: (name, args) => callFunction(name, args),
  };
}

/** Resolves to a display string, which is what most props actually want. */
export function resolveText(value: Json | undefined, scope: ResolveScope): string {
  const resolved = resolve(value, scope);
  if (resolved === null || resolved === undefined) return '';
  if (typeof resolved === 'string') return resolved;
  if (typeof resolved === 'number' || typeof resolved === 'boolean') return String(resolved);
  return '';
}

/**
 * Whether a binding is waiting for data rather than holding none.
 *
 * The difference matters as soon as a surface is drawn before the data that
 * fills it. A component bound to `$/flights/0/price` on a row the server has
 * created but not yet filled should show that something is coming; the same
 * component bound to a field that genuinely has no value should show nothing.
 *
 * The rule is the one the data model already gives for free: **a path that does
 * not resolve is pending, a path that resolves to an empty string is empty.**
 * Nothing new has to be sent to say so — seeding `/flights` with blank rows and
 * filling them later is enough, which is why this needs no protocol of its own.
 *
 * A literal is never pending: text written into the component by the model is
 * as arrived as it will ever be.
 */
export function isPending(value: Json | undefined, scope: ResolveScope): boolean {
  if (!isBinding(value)) return false;
  const resolved = resolve(value, scope);
  return resolved === null || resolved === undefined;
}

export function resolveNumber(value: Json | undefined, scope: ResolveScope): number | undefined {
  const resolved = resolve(value, scope);
  if (typeof resolved === 'number') return resolved;
  if (typeof resolved === 'string' && resolved.trim() !== '') {
    const parsed = Number(resolved);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function resolveBoolean(value: Json | undefined, scope: ResolveScope): boolean {
  const resolved = resolve(value, scope);
  if (typeof resolved === 'boolean') return resolved;
  if (typeof resolved === 'string') return resolved === 'true';
  if (typeof resolved === 'number') return resolved !== 0;
  return false;
}

/** The pointer a control writes back to, or undefined if it is not bound. */
export function bindingPointer(value: Json | undefined, scope: ResolveScope): string | undefined {
  const bound = pathOf(value);
  return bound !== undefined ? absolutePointer(bound, scope) : undefined;
}
