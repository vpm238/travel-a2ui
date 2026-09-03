/**
 * Getting the API key in, including from the URL.
 *
 * The convenient thing is `https://…/#key=sk-ant-…` — open the link and start
 * using it, no form. The dangerous thing is that URLs are the least private
 * place to put a credential: they go in browser history, in bookmarks, in the
 * `Referer` header, and — for a query string — in every access log between the
 * browser and the server.
 *
 * So both forms are accepted and treated differently:
 *
 *   #key=sk-ant-…    the fragment. **Never sent to any server**, by definition.
 *                    This is the form to use and the one the app hands out.
 *   ?key=sk-ant-…    the query string. Works, because people will paste it, but
 *                    the server *did* see it and the app says so once.
 *
 * Either way the key is pulled out and the address bar is rewritten
 * immediately, so a screenshot, a shared tab or a bookmark does not carry it.
 * That is a mitigation, not a fix: a key that has been in a query string should
 * be treated as a key that has been logged.
 */

const KEY_PARAM = 'key';

export interface UrlKey {
  key: string;
  /** True when it arrived in the query string, which the server saw. */
  exposed: boolean;
}

/**
 * Takes the key out of the URL, if there is one, and scrubs the address bar.
 *
 * Call it once, before anything reads `location`. It rewrites history with
 * `replaceState`, so there is no entry to go "back" to.
 */
export function consumeKeyFromUrl(): UrlKey | null {
  if (typeof window === 'undefined') return null;

  const url = new URL(window.location.href);

  // The fragment first: it is the safe form, and if someone sends both we
  // should prefer the one that did not travel to a server.
  const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
  const fromFragment = fragment.get(KEY_PARAM)?.trim();
  const fromQuery = url.searchParams.get(KEY_PARAM)?.trim();

  if (!fromFragment && !fromQuery) return null;

  fragment.delete(KEY_PARAM);
  url.searchParams.delete(KEY_PARAM);
  const rest = fragment.toString();
  url.hash = rest ? `#${rest}` : '';

  try {
    window.history.replaceState(null, '', url.toString());
  } catch {
    /* a sandboxed frame may refuse; the key is still consumed */
  }

  const key = fromFragment || fromQuery!;
  return { key, exposed: !fromFragment && Boolean(fromQuery) };
}

/** Builds the shareable form of a key link — always the fragment. */
export function keyLink(origin: string, key: string): string {
  return `${origin.replace(/\/$/, '')}/#${KEY_PARAM}=${encodeURIComponent(key)}`;
}
