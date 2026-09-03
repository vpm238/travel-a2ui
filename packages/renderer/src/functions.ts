/**
 * The catalog's client-side functions, implemented by the host.
 *
 * These are the functions the model may call in a value position
 * (`formatCurrency($/total, "EUR")`) or in a check (`?regex(...)`). Two rules
 * shape every implementation here:
 *
 * 1. **Never throw.** A malformed argument from a model mid-stream must degrade
 *    to something renderable, not blow up the surface it appears in.
 * 2. **Never do anything unsafe.** `openUrl` is the only one that touches the
 *    outside world, and it refuses anything that is not http(s) or mailto — a
 *    catalog function is model-controlled input, and `javascript:` in an href
 *    is a script injection with extra steps.
 */

import type { Json, JsonObject } from '@travel-a2ui/express';

type Args = JsonObject;

const SAFE_URL_SCHEMES = new Set(['http:', 'https:', 'mailto:', 'tel:']);

/** True when a URL is safe to put in an href or open. */
export function isSafeUrl(raw: unknown): raw is string {
  if (typeof raw !== 'string') return false;
  const trimmed = raw.trim();
  if (trimmed.startsWith('/') || trimmed.startsWith('#')) return true;
  try {
    return SAFE_URL_SCHEMES.has(new URL(trimmed).protocol);
  } catch {
    return false;
  }
}

function asString(value: Json | undefined): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function asNumber(value: Json | undefined): number | undefined {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function truthy(value: Json | undefined): boolean {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') return value.length > 0 && value !== 'false';
  if (typeof value === 'number') return value !== 0;
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === 'object') return Object.keys(value).length > 0;
  return false;
}

/** Evaluates one catalog function against already-resolved arguments. */
export function callFunction(name: string, args: Args): Json {
  try {
    switch (name) {
      // -- formatting ----------------------------------------------------
      case 'formatString': {
        const template = asString(args['template'] ?? args['value']);
        const values = args['values'];
        if (Array.isArray(values)) {
          let index = 0;
          return template.replace(/\{\}/g, () => asString(values[index++] ?? ''));
        }
        if (values && typeof values === 'object') {
          return template.replace(/\{(\w+)\}/g, (_match, key: string) =>
            asString((values as JsonObject)[key]),
          );
        }
        return template;
      }

      case 'formatNumber': {
        const value = asNumber(args['value']);
        if (value === undefined) return asString(args['value']);
        const decimals = asNumber(args['decimals']);
        return new Intl.NumberFormat(undefined, {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
          useGrouping: args['grouping'] === undefined ? true : truthy(args['grouping']),
        }).format(value);
      }

      case 'formatCurrency': {
        const value = asNumber(args['value']);
        const currency = asString(args['currency']) || 'USD';
        if (value === undefined) return asString(args['value']);
        const decimals = asNumber(args['decimals']);
        try {
          return new Intl.NumberFormat(undefined, {
            style: 'currency',
            currency,
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
            useGrouping: args['grouping'] === undefined ? true : truthy(args['grouping']),
          }).format(value);
        } catch {
          return `${currency} ${value}`;
        }
      }

      case 'formatDate': {
        const raw = asString(args['value']);
        const date = new Date(raw);
        if (Number.isNaN(date.getTime())) return raw;
        const format = asString(args['format']);
        if (format === 'time') {
          return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        }
        if (format === 'full' || format === 'long') {
          return date.toLocaleDateString(undefined, { dateStyle: 'long' } as never);
        }
        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
      }

      case 'pluralize': {
        const count = asNumber(args['count'] ?? args['value']) ?? 0;
        const one = asString(args['one'] ?? args['singular']);
        const other = asString(args['other'] ?? args['plural']);
        return count === 1 ? one : other;
      }

      // -- validation ----------------------------------------------------
      case 'required':
        return truthy(args['value']);

      case 'regex': {
        const value = asString(args['value']);
        const pattern = asString(args['pattern']);
        if (!pattern) return true;
        try {
          return new RegExp(pattern).test(value);
        } catch {
          return true; // an unparseable pattern must not fail a valid field
        }
      }

      case 'length': {
        const value = asString(args['value']);
        const min = asNumber(args['min']);
        const max = asNumber(args['max']);
        if (min !== undefined && value.length < min) return false;
        if (max !== undefined && value.length > max) return false;
        return true;
      }

      case 'numeric': {
        const value = asNumber(args['value']);
        if (value === undefined) return false;
        const min = asNumber(args['min']);
        const max = asNumber(args['max']);
        if (min !== undefined && value < min) return false;
        if (max !== undefined && value > max) return false;
        return true;
      }

      case 'email': {
        const value = asString(args['value']);
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
      }

      case 'and': {
        const values = args['values'] ?? args['conditions'];
        return Array.isArray(values) ? values.every(truthy) : truthy(values);
      }

      case 'or': {
        const values = args['values'] ?? args['conditions'];
        return Array.isArray(values) ? values.some(truthy) : truthy(values);
      }

      case 'not':
        return !truthy(args['value'] ?? args['condition']);

      // -- side effects --------------------------------------------------
      case 'openUrl': {
        const url = args['url'];
        if (isSafeUrl(url) && typeof window !== 'undefined') {
          window.open(url, '_blank', 'noopener,noreferrer');
        }
        return null;
      }

      default:
        return null;
    }
  } catch {
    return null;
  }
}
