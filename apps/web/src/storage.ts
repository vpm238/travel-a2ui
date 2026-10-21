/**
 * What the browser remembers between visits, and what it is allowed to forget.
 *
 * Four keys and three functions. Every read and write is wrapped, because
 * `localStorage` throws rather than returning null in a private window with
 * storage disabled, and an app that cannot remember a preference should still
 * answer questions about flights.
 */

export const API_KEY = 'travel-a2ui:key';
// Bumped when a default changes in a way a stored preference would hide. The
// effort default moved from `low` to `minimal` — worth about thirteen seconds a
// turn — and anyone who had already loaded the app once would have kept `low`
// forever without ever having chosen it.
export const PREFS_KEY = 'travel-a2ui:prefs2';
export const BACKEND_KEY = 'travel-a2ui:backend';
export const LIVE_KEY = 'travel-a2ui:live';

/**
 * What the app remembers about instantiating the Live agent.
 *
 * The Live API has no agent object to look up, so the client keeps the receipt:
 * which contract the handshake bound to, which model answered, and when.
 */
export interface LiveRecord {
  contract: string;
  model: string;
  at: number;
}

export type LiveStatus =
  /** No key yet, or never instantiated. */
  | 'absent'
  /** Handshaking now. */
  | 'instantiating'
  /** Bound to the contract this deployment is currently serving. */
  | 'ready'
  /** Bound to something this deployment no longer serves, or bound too long ago. */
  | 'stale'
  /** The handshake was refused — usually the key. */
  | 'failed';

export function readLiveRecord(): LiveRecord | null {
  try {
    const stored = readStored(LIVE_KEY);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as LiveRecord;
    return typeof parsed?.contract === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* private browsing, or storage disabled — the app still works this session */
  }
}

export function newSessionId(): string {
  return `s_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
}
