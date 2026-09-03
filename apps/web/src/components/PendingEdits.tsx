/**
 * The bar that appears when a surface is holding an answer nobody has sent.
 *
 * Editing a control no longer starts a turn — three choices on one card are one
 * answer, not three. That is right, but it leaves a gap: having changed
 * something, how does the traveler know anything is waiting, and what do they
 * press?
 *
 * Usually the agent's own commit button ("Apply", "Update the trip"), and when
 * one is there this bar is just the reminder that it has not been pressed. When
 * the agent forgot to draw one, the bar's own button is the way out — otherwise
 * a card of sliders is a dead end, and the traveler's answer is trapped inside
 * a surface that will never send it.
 *
 * "Changed" means the surface's data model differs from the one it arrived
 * with, so a value dragged and dragged back to where it started correctly
 * reports nothing pending.
 */

import { useEffect, useRef, useState } from 'react';
import type { SurfaceStore } from '@travel-a2ui/renderer';

/** Field names that changed since the surface was drawn, at any depth. */
function changedPaths(before: unknown, after: unknown, prefix = ''): string[] {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];

  const isObject = (value: unknown): value is Record<string, unknown> =>
    Boolean(value) && typeof value === 'object' && !Array.isArray(value);

  if (!isObject(before) || !isObject(after)) return [prefix || 'value'];

  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  return [...keys].flatMap((key) =>
    changedPaths(before[key], after[key], prefix ? `${prefix}/${key}` : key),
  );
}

export function PendingEdits({
  store,
  surfaceId,
  busy,
  onSubmit,
}: {
  store: SurfaceStore;
  surfaceId: string;
  busy: boolean;
  onSubmit: (surfaceId: string) => void;
}) {
  const [baseline, setBaseline] = useState(() => store.snapshot(surfaceId));
  const [changed, setChanged] = useState<string[]>([]);
  // The version the baseline was taken at, so a surface the agent replaces
  // resets rather than reporting the previous panel's edits as pending.
  const seen = useRef(store.getVersion());

  useEffect(() => {
    const check = () => {
      const next = store.snapshot(surfaceId);
      setChanged(changedPaths(baseline, next));
    };
    check();
    return store.subscribe(check);
  }, [baseline, store, surfaceId]);

  // A rebuilt surface is a new question; whatever was pending answered the old
  // one. `components` identity changes when the agent replaces the surface.
  const surface = store.get(surfaceId);
  const fingerprint = surface ? [...surface.components.keys()].join(',') : '';
  const lastFingerprint = useRef(fingerprint);
  useEffect(() => {
    if (lastFingerprint.current === fingerprint) return;
    lastFingerprint.current = fingerprint;
    seen.current = store.getVersion();
    setBaseline(store.snapshot(surfaceId));
    setChanged([]);
  }, [fingerprint, store, surfaceId]);

  if (changed.length === 0 || busy) return null;

  const names = changed.map((path) => path.split('/').pop() ?? path);
  const listed = names.slice(0, 3).join(', ');

  return (
    <div className="pending" role="status">
      <span>
        <strong>{changed.length}</strong> unsent {changed.length === 1 ? 'change' : 'changes'}
        <span className="pending__fields"> · {listed}{names.length > 3 ? '…' : ''}</span>
      </span>
      <button
        type="button"
        onClick={() => {
          setBaseline(store.snapshot(surfaceId));
          setChanged([]);
          onSubmit(surfaceId);
        }}
      >
        Send
      </button>
    </div>
  );
}
