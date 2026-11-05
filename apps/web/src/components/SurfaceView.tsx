/**
 * One surface on screen, drawn by `@a2ui/react`.
 *
 * Subscribes only to whether the surface exists; what is inside it is the
 * SDK's to keep current, and it updates exactly the components a message
 * touched. Markdown is supplied here because A2UI 1.0's `Text` is Markdown —
 * a heading is `### Outbound` — and the SDK renders it with what the app gives.
 */

import { useSyncExternalStore } from 'react';
import { A2uiSurface, MarkdownContext } from '@a2ui/react/v0_9';
import { renderMarkdown } from '@travel-a2ui/renderer';

import type { Surfaces } from '../surfaces.js';

export function useSurfaces(surfaces: Surfaces): number {
  return useSyncExternalStore(surfaces.subscribe, surfaces.getVersion, surfaces.getVersion);
}

/**
 * `interactive={false}` makes the whole surface inert: an answered card is a
 * record of the answer, and `inert` stops clicks and focus for everything in
 * it — the SDK's own web components included — with nothing to re-implement.
 */
export function SurfaceView({
  surfaces,
  surfaceId,
  interactive = true,
}: {
  surfaces: Surfaces;
  surfaceId: string;
  interactive?: boolean;
}) {
  useSurfaces(surfaces);
  const surface = surfaces.get(surfaceId);
  if (!surface) return null;
  return (
    <MarkdownContext.Provider value={renderMarkdown}>
      <div className="a2-surface" data-surface={surfaceId} inert={!interactive}>
        <A2uiSurface surface={surface as never} />
      </div>
    </MarkdownContext.Provider>
  );
}
