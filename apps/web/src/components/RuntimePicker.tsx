/**
 * Picks which agent framework answers.
 *
 * Two of them ship, and they are not the same program with a different flag:
 *
 *   Cloudflare Worker   Gemini Interactions API. A request/response loop this
 *                       Worker drives at the edge, on the traveller's own key,
 *                       calling the travel tools directly. Typed.
 *
 *   Gemini Live         Gemini Live API. A bidirectional audio session Google
 *                       drives, relayed through the same session Durable
 *                       Object. Speak or type; it answers out loud.
 *
 * The claim this picker exists to test is that the interface layer is
 * independent of the runtime — one catalog, one set of components, one set of
 * skills, one wire protocol — so you can switch mid-conversation and watch the
 * same surfaces come back from a different machine on a different API.
 *
 * They share nothing. Different APIs, different conversation histories, and no
 * attempt to carry a half-decided trip across — so switching reloads the page
 * and starts the demo over, which is what a reload already means here. The
 * alternative was a caveat ("they share the trip but not the transcript") that
 * a demo should not have to explain, and a state-unwinding bug waiting to
 * happen.
 *
 * The `origin` field takes any backend answering the same `/api/chat` contract,
 * which is how a third framework would arrive.
 *
 * Switching probes the target first. A runtime that is not running says so here
 * rather than failing on the next message.
 */

import { useEffect, useState } from 'react';

import type { BackendId, BackendOption } from '../api.js';

export function RuntimePicker({
  backends,
  current,
  error,
  onChange,
}: {
  backends: BackendOption[];
  current: { id: BackendId; origin: string };
  error: string | null;
  onChange: (id: BackendId, origin: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [draftId, setDraftId] = useState<BackendId>(current.id);
  const [draftOrigin, setDraftOrigin] = useState(current.origin);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDraftId(current.id);
    setDraftOrigin(current.origin);
  }, [current.id, current.origin]);

  const active = backends.find((entry) => entry.id === current.id);
  const draft = backends.find((entry) => entry.id === draftId);

  /**
   * Where a framework lives, as the server advertises it. Empty is same-origin.
   *
   * This used to be `id !== 'worker'` — written when the only second runtime
   * was a managed agent at its own address. Gemini Live is served by this same
   * Worker, so that test made choosing it wait forever for a URL it does not
   * have: the entry highlighted, the picker stayed open, and nothing switched.
   * The server knows the answer, so ask the server.
   */
  const originOf = (id: BackendId) => backends.find((entry) => entry.id === id)?.origin ?? '';
  const needsOrigin = originOf(draftId) !== '';

  async function pick(id: BackendId) {
    setDraftId(id);
    const advertised = originOf(id);
    if (advertised === '') {
      setBusy(true);
      const ok = await onChange(id, '');
      setBusy(false);
      if (ok) setOpen(false);
      return;
    }
    setDraftOrigin(draftOrigin || advertised);
  }

  async function connect() {
    setBusy(true);
    const ok = await onChange(draftId, draftOrigin.trim());
    setBusy(false);
    if (ok) setOpen(false);
  }

  return (
    <div className="runtime">
      <button
        type="button"
        className="runtime__trigger"
        aria-expanded={open}
        title="Which agent runtime answers"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="runtime__label">Runtime</span>
        <span className="runtime__value">{active?.label ?? current.id}</span>
        <span className="runtime__caret" aria-hidden>
          ▾
        </span>
      </button>

      {open ? (
        <div className="runtime__menu" role="dialog" aria-label="Agent runtime">
          {backends.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={`runtime__option${entry.id === draftId ? ' is-active' : ''}`}
              aria-current={entry.id === current.id}
              onClick={() => void pick(entry.id)}
            >
              <strong>
                {entry.label}
                {entry.id === current.id ? <span className="runtime__now">in use</span> : null}
              </strong>
              <span>{entry.note}</span>
            </button>
          ))}

          {needsOrigin ? (
            <div className="runtime__connect">
              <label>
                <span>Where it is running</span>
                <input
                  type="url"
                  value={draftOrigin}
                  spellCheck={false}
                  placeholder="http://localhost:8000"
                  onChange={(event) => setDraftOrigin(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void connect();
                  }}
                />
              </label>
              <button type="button" disabled={busy || !draftOrigin.trim()} onClick={() => void connect()}>
                {busy ? 'Checking…' : 'Connect'}
              </button>
              <p>
                A runtime somewhere other than this Worker. Both of the built-in
                ones are served from here, so this is only for a backend you are
                running yourself.
              </p>
            </div>
          ) : null}

          {error ? <p className="runtime__error">{error}</p> : null}
          {!error && draft && draftId === current.id ? (
            <p className="runtime__note">
              Your key goes to whichever runtime is selected. Both call Gemini with it directly, and neither stores it.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
