/**
 * Picks which agent runtime answers.
 *
 * The claim this app makes is that the interface layer is independent of the
 * runtime: one catalog, one set of components, one set of skills, one wire
 * protocol — and underneath, whoever you like running the loop. A dropdown is
 * the honest way to demonstrate that, because you can switch mid-conversation
 * and watch the same surfaces come back from a different machine.
 *
 * Two runtimes today:
 *
 *   Cloudflare Worker      the loop runs at the edge, in the Worker serving this
 *                          page. Same origin, one deploy, sessions in a Durable
 *                          Object. This is the default and needs nothing.
 *   Claude Managed Agent   Anthropic runs the loop and hosts the sandbox; the
 *                          Python backend in `backends/` provisions the agent
 *                          and relays the same events. It runs somewhere else,
 *                          so it needs an origin — hence the field.
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

  // The Worker is whatever origin served this page; only the managed agent has
  // an address worth asking about.
  const needsOrigin = draftId !== 'worker';

  async function pick(id: BackendId) {
    setDraftId(id);
    if (id === 'worker') {
      setBusy(true);
      const ok = await onChange('worker', '');
      setBusy(false);
      if (ok) setOpen(false);
      return;
    }
    const suggested = draftOrigin || backends.find((entry) => entry.id === id)?.origin || '';
    setDraftOrigin(suggested);
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
                Start it with <code>uvicorn travel_agent.server:app --port 8000</code> in{' '}
                <code>backends/claude-managed-agent</code>, after{' '}
                <code>python -m travel_agent.setup_agent</code>.
              </p>
            </div>
          ) : null}

          {error ? <p className="runtime__error">{error}</p> : null}
          {!error && draft && draftId === current.id ? (
            <p className="runtime__note">
              Your key goes to whichever runtime is selected. Both call Anthropic with it directly.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
