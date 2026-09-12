/**
 * `formatString`, as A2UI actually specifies it.
 *
 * The catalog's own description of the function is unambiguous: its `value` is
 * a string that may carry `${…}` expressions, where an expression is either a
 * JSON Pointer into the data model or a call to another catalog function whose
 * arguments are named — `${formatDate(value:${/currentDate}, format:'MM-dd')}`.
 * Literal `${` escapes as `\${`.
 *
 * None of that was implemented. `formatString` did `{}` and `{name}`
 * substitution against a `values` object, which is a different function that
 * happens to share a name, so a spec-correct template was returned verbatim and
 * a live run put this on screen under a date picker:
 *
 *     ${calcNights(start: ${/trip/startDate}, end: ${/trip/endDate})} nights
 *
 * The model was right and the renderer was wrong, which is worth saying because
 * the first fix attempted was to compute nights inside `DateRangePicker` — and
 * that would have deleted the one thing the feature exists to demonstrate. A
 * label bound to a function recomputes the instant a control moves, on every
 * renderer, with no turn and no tokens. It only had to work.
 *
 * Interpolation needs the data model, so it lives here rather than in
 * `functions.ts`, where a function only ever sees arguments already resolved.
 */

import type { Json, JsonObject } from '@travel-a2ui/express';

/** What an expression needs to resolve against: the model and a list scope. */
export interface Lookup {
  /** Reads a JSON Pointer, relative paths already made absolute. */
  readPath(path: string): Json | undefined;
  /** Evaluates a catalog function against resolved arguments. */
  call(name: string, args: JsonObject): Json;
}

const asText = (value: Json | undefined): string =>
  value === null || value === undefined
    ? ''
    : typeof value === 'object'
      ? ''
      : String(value);

/**
 * Splits a string into literal runs and `${…}` expressions.
 *
 * Brace depth is tracked rather than matched with a regex, because expressions
 * nest: the whole point of the syntax is that a function's arguments are
 * themselves expressions.
 */
function* segments(template: string): Generator<{ literal: string } | { expression: string }> {
  let literal = '';

  for (let index = 0; index < template.length; index += 1) {
    // `\${` is a literal `${`, and the only escape the spec defines.
    if (template[index] === '\\' && template.slice(index + 1, index + 3) === '${') {
      literal += '${';
      index += 2;
      continue;
    }

    if (template.slice(index, index + 2) !== '${') {
      literal += template[index];
      continue;
    }

    let depth = 1;
    let cursor = index + 2;
    let quote: string | null = null;
    while (cursor < template.length && depth > 0) {
      const char = template[cursor]!;
      if (quote) {
        if (char === quote) quote = null;
      } else if (char === "'" || char === '"') {
        quote = char;
      } else if (char === '{') {
        depth += 1;
      } else if (char === '}') {
        depth -= 1;
      }
      cursor += 1;
    }

    // Unclosed: a model still mid-stream. Emit what is there as text rather
    // than dropping the rest of the label.
    if (depth > 0) {
      literal += template.slice(index);
      break;
    }

    if (literal) {
      yield { literal };
      literal = '';
    }
    yield { expression: template.slice(index + 2, cursor - 1) };
    index = cursor - 1;
  }

  if (literal) yield { literal };
}

/** Splits on commas that are not inside brackets, braces or quotes. */
function topLevelSplit(source: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let current = '';

  for (const char of source) {
    if (quote) {
      current += char;
      if (char === quote) quote = null;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      current += char;
      continue;
    }
    if (char === '(' || char === '{' || char === '[') depth += 1;
    if (char === ')' || char === '}' || char === ']') depth -= 1;
    if (char === ',' && depth === 0) {
      parts.push(current);
      current = '';
      continue;
    }
    current += char;
  }
  if (current.trim()) parts.push(current);
  return parts;
}

/** One argument value: a nested expression, a quoted string, or a number. */
function argument(source: string, lookup: Lookup): Json {
  const text = source.trim();

  if (text.startsWith('${') && text.endsWith('}')) return evaluate(text.slice(2, -1), lookup);
  if (
    (text.startsWith("'") && text.endsWith("'")) ||
    (text.startsWith('"') && text.endsWith('"'))
  ) {
    return text.slice(1, -1);
  }
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (text !== '' && Number.isFinite(Number(text))) return Number(text);
  // A bare path, which the spec allows at the top level and models write inside
  // arguments too.
  if (text.startsWith('/')) return lookup.readPath(text) ?? null;
  return text;
}

/** Evaluates one expression's interior — what sat between `${` and `}`. */
function evaluate(source: string, lookup: Lookup): Json {
  const text = source.trim();
  if (!text) return '';

  const open = text.indexOf('(');
  if (open > 0 && text.endsWith(')')) {
    const name = text.slice(0, open).trim();
    // A name with a slash in it is a path that happens to contain a bracket,
    // not a call.
    if (/^[A-Za-z_]\w*$/.test(name)) {
      const args: JsonObject = {};
      for (const [position, part] of topLevelSplit(text.slice(open + 1, -1)).entries()) {
        const colon = splitName(part);
        // The spec says arguments must be named. Models occasionally write them
        // positionally anyway, and dropping the argument silently is worse than
        // guessing: an unnamed one is keyed by position so a wrong key is
        // visible rather than a missing value.
        if (colon) args[colon.name] = argument(colon.value, lookup);
        else args[`_${position}`] = argument(part, lookup);
      }
      return lookup.call(name, args);
    }
  }

  return lookup.readPath(text) ?? null;
}

/** `name: value`, split at the first colon that is not inside an expression. */
function splitName(part: string): { name: string; value: string } | null {
  const trimmed = part.trim();
  const match = /^([A-Za-z_]\w*)\s*:/.exec(trimmed);
  if (!match) return null;
  return { name: match[1]!, value: trimmed.slice(match[0].length) };
}

/** Resolves every `${…}` in a template against the data model. */
export function interpolate(template: string, lookup: Lookup): string {
  let out = '';
  for (const segment of segments(template)) {
    out += 'literal' in segment ? segment.literal : asText(evaluate(segment.expression, lookup));
  }
  return out;
}

/** True when a string has an expression worth resolving. */
export const hasExpression = (value: string): boolean => value.includes('${');
