/**
 * One component, on its own, at `/catalog/<Name>`.
 *
 * What the component reference (`docs/catalog.md`) photographs, and a link
 * anyone can share to a single component, drawn from the same build-time
 * reference and the same SDK renderer as everything else.
 */

import { useMemo } from 'react';

import reference from '../generated/catalog-reference.json';
import { Surfaces } from '../surfaces.js';
import { SurfaceView } from './SurfaceView.js';

export function Specimen({ name }: { name: string }) {
  const component = (
    reference.components as Array<{ name: string; messages?: unknown[]; error?: string }>
  ).find((entry) => entry.name === name);
  const surfaces = useMemo(() => {
    if (!component?.messages) return null;
    const one = new Surfaces();
    one.apply(component.messages);
    return one;
  }, [component]);
  const surfaceId = surfaces?.ids()[0];

  return (
    <main className="specimen">
      {surfaces && surfaceId ? (
        <div className="specimen__surface" data-component={name}>
          <SurfaceView surfaces={surfaces} surfaceId={surfaceId} />
        </div>
      ) : (
        <p className="specimen__missing">{component?.error ?? `No component called ${name}.`}</p>
      )}
    </main>
  );
}
