/**
 * Bring your own key.
 *
 * The key stays in this browser's localStorage and is sent as a header with each
 * request; the server passes it to Anthropic and forgets it. That is worth
 * saying on screen rather than burying in a README, because the person pasting a
 * credential into a web page deserves to know where it goes before they do it,
 * not after.
 */

import { useState, type FormEvent } from 'react';

export function KeyGate({
  onSave,
  onDismiss,
  existing,
}: {
  onSave: (key: string) => void;
  onDismiss?: () => void;
  existing?: string;
}) {
  const [value, setValue] = useState(existing ?? '');
  const [touched, setTouched] = useState(false);

  const trimmed = value.trim();
  // A soft check: the point is to catch a pasted placeholder, not to police the
  // key format, which Anthropic is free to change.
  const looksWrong = touched && trimmed.length > 0 && !trimmed.startsWith('sk-ant-');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed) return;
    onSave(trimmed);
  };

  return (
    <div className="gate" role="dialog" aria-modal aria-labelledby="gate-title">
      <form className="gate__panel" onSubmit={submit}>
        <h2 id="gate-title">Add your Anthropic API key</h2>
        <p>
          This app calls Claude with <em>your</em> key, so nothing here is metered against anyone
          else. It is stored in this browser and sent with each request — never written to the
          server, never logged, never in a URL.
        </p>

        <label className="gate__field">
          <span>API key</span>
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="sk-ant-…"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onBlur={() => setTouched(true)}
            autoFocus
          />
        </label>

        {looksWrong ? (
          <p className="gate__warn">Anthropic keys usually start with <code>sk-ant-</code>.</p>
        ) : null}

        <div className="gate__actions">
          <button type="submit" className="button button--primary" disabled={!trimmed}>
            Start planning
          </button>
          {onDismiss ? (
            <button type="button" className="button" onClick={onDismiss}>
              Cancel
            </button>
          ) : null}
        </div>

        <p className="gate__foot">
          Get a key at{' '}
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
            console.anthropic.com
          </a>
          . Clearing it is one click in the header.
        </p>
      </form>
    </div>
  );
}
