/**
 * A real Google map, from the same component Google publishes.
 *
 * `@googlemaps/a2ui` defines a `GoogleMap` component for A2UI, and this
 * catalog's `GoogleMap` has its schema property for property — `center`,
 * `zoom`, `tilt`, `heading`, `mode`, `anchorMarker`, `markers`, `origin`,
 * `destination`, `travelMode`, `routes`, with pins spelled `{lat, lng, label,
 * placeId?}`. A payload this app composes renders in their host, and one of
 * theirs renders here.
 *
 * What is *not* borrowed is their renderer. Their package ships the component
 * as a Lit element bound to `@a2ui/lit` — a second A2UI runtime, with its own
 * data model, mounted inside ours. Reading their source is what settled it:
 * their element's whole job is to turn resolved props into `<gmp-map-3d>`,
 * `<gmp-marker-3d>` and `<gmp-route-3d>`, which are framework-agnostic custom
 * elements published by the Maps JavaScript API itself. Our renderer already
 * resolves A2UI props. So this draws the same elements from the props we
 * already have, and the page keeps one data model instead of mirroring it into
 * a second one.
 *
 * The map draws and does not ask. Google's component dispatches no events —
 * no click, no selection, nothing — so by this app's own rules it is furniture,
 * in the same category as `StatTile`. That is why the surface briefs say to
 * pair it with the controls for the decision it illustrates, and never to let
 * it stand as the answer to a turn that needed to ask something.
 */

import { useEffect, useRef, useState } from 'react';
import type { Json } from '@travel-a2ui/express';

import { resolveNumber, resolveText } from '../binding.js';
import type { ComponentProps } from '../context.js';
import type { ResolveScope } from '../binding.js';

type Row = Record<string, Json>;

const rowsOf = (value: Json | undefined): Row[] =>
  Array.isArray(value) ? (value.filter((item) => item && typeof item === 'object') as Row[]) : [];

interface Pin {
  lat: number;
  lng: number;
  label: string;
}

/** A `{lat, lng}` object whose members may each be bound. */
function point(value: Json | undefined, scope: ResolveScope): { lat: number; lng: number } | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const row = value as Row;
  const lat = resolveNumber(row['lat'], scope);
  const lng = resolveNumber(row['lng'], scope);
  // Not `|| 0`. Null Island is in the Gulf of Guinea, and a map that silently
  // centres there for a missing binding looks like a bug in the map rather
  // than a gap in the data.
  if (lat === undefined || lng === undefined) return null;
  return { lat, lng };
}

function pin(value: Json | undefined, scope: ResolveScope): Pin | null {
  const at = point(value, scope);
  if (!at) return null;
  const row = value as Row;
  return { ...at, label: resolveText(row['label'], scope) };
}

/**
 * The Maps JavaScript API, loaded once per page and shared.
 *
 * `v=alpha` and the `maps3d` library, because `gmp-map-3d` lives there — this
 * is what Google's own sample loads, and the element simply does not upgrade
 * without it. The promise is cached on the module so eight maps on one home
 * screen are one script tag and one download.
 */
let loading: Promise<boolean> | null = null;

function loadMaps(apiKey: string): Promise<boolean> {
  if (loading) return loading;
  loading = new Promise<boolean>((resolve) => {
    if (typeof document === 'undefined' || !apiKey) return resolve(false);
    const existing = document.querySelector<HTMLScriptElement>('script[data-a2ui-maps]');
    if (existing) return resolve(true);
    const script = document.createElement('script');
    script.async = true;
    script.dataset.a2uiMaps = 'yes';
    // `loading=async` is Google's documented pattern and the library says so out
    // loud without it: "loaded directly without loading=async. This can result
    // in suboptimal performance." Without it the parser blocks on the bootstrap
    // while a surface is still streaming in beside it.
    script.src =
      'https://maps.googleapis.com/maps/api/js?v=alpha&loading=async' +
      '&libraries=maps3d,marker,places,routes' +
      `&key=${encodeURIComponent(apiKey)}`;
    script.onload = () => resolve(true);
    // A key that is rejected, a referrer that is not allowed, a network that is
    // not there. All of them end here, and none of them should take the
    // surface down with them — the caption still says where this is.
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
  return loading;
}

/**
 * Where the key comes from.
 *
 * Set on `window` by the app from `/api/meta`, which reads it from the
 * deployment's environment. A Maps key is meant to be public and restricted by
 * HTTP referrer, which is why this one is not typed in by the traveller the
 * way the Gemini key is: a demo that asks for a second key at the door loses
 * people before the first surface.
 */
function mapsKey(): string {
  if (typeof window === 'undefined') return '';
  return String((window as unknown as Record<string, unknown>)['__A2UI_MAPS_KEY'] ?? '');
}

export function GoogleMap({ node, scope }: ComponentProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const [ready, setReady] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const key = mapsKey();

  const centre = point(node['center'], scope);
  const zoom = resolveNumber(node['zoom'], scope) ?? 11;
  const mode = resolveText(node['mode'], scope) || 'roadmap';
  const heading = resolveNumber(node['heading'], scope) ?? 0;
  // Tilt only reads as anything in satellite, and Google's own component
  // zeroes it otherwise rather than tilting a flat roadmap into a lozenge.
  const tilt = mode === 'satellite' ? (resolveNumber(node['tilt'], scope) ?? 0) : 0;

  const anchor = pin(node['anchorMarker'], scope);
  const markers = rowsOf(node['markers'])
    .map((row) => pin(row, scope))
    .filter((item): item is Pin => item !== null);

  const legs = rowsOf(node['routes'])
    .map((row) => ({ from: pin(row['origin'], scope), to: pin(row['destination'], scope) }))
    .filter((leg): leg is { from: Pin; to: Pin } => leg.from !== null && leg.to !== null);

  // `origin`/`destination` are the one-leg spelling of the same thing, so they
  // become a leg rather than a second code path.
  const from = point(node['origin'], scope);
  const to = point(node['destination'], scope);
  if (from && to) legs.push({ from: { ...from, label: '' }, to: { ...to, label: '' } });

  useEffect(() => {
    let live = true;
    void loadMaps(key).then((ok) => {
      if (live) setReady(ok ? 'ready' : 'unavailable');
    });
    return () => {
      live = false;
    };
  }, [key]);

  useEffect(() => {
    if (ready !== 'ready' || !host.current || !centre) return;
    const element = host.current;
    element.replaceChildren();

    const map = document.createElement('gmp-map-3d');
    map.setAttribute('center', `${centre.lat},${centre.lng},0`);
    // The 3D element takes a range in metres rather than a tile zoom level, so
    // the same doubling a zoom level means is a halving here.
    map.setAttribute('range', String(Math.max(200, 40_000_000 / 2 ** Math.min(zoom, 16))));
    map.setAttribute('tilt', String(tilt));
    map.setAttribute('heading', String(heading));
    map.setAttribute('mode', mode === 'satellite' ? 'SATELLITE' : 'HYBRID');
    map.style.width = '100%';
    map.style.height = '100%';

    for (const place of anchor ? [anchor, ...markers] : markers) {
      const marker = document.createElement('gmp-marker-3d');
      marker.setAttribute('position', `${place.lat},${place.lng}`);
      if (place.label) marker.setAttribute('label', place.label);
      if (anchor && place === anchor) marker.setAttribute('altitude-mode', 'clamp-to-ground');
      map.appendChild(marker);
    }

    for (const leg of legs) {
      const route = document.createElement('gmp-route-3d');
      route.setAttribute('origin', `${leg.from.lat},${leg.from.lng}`);
      route.setAttribute('destination', `${leg.to.lat},${leg.to.lng}`);
      const travel = resolveText(node['travelMode'], scope);
      if (travel) route.setAttribute('travel-mode', travel.toUpperCase());
      map.appendChild(route);
    }

    element.appendChild(map);
    return () => element.replaceChildren();
    // Serialised rather than listed: `markers` and `routes` are fresh arrays on
    // every render, so a dependency on the arrays themselves would tear the map
    // down and rebuild it on each streamed token.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, JSON.stringify({ centre, zoom, mode, tilt, heading, anchor, markers, legs })]);

  const named = [anchor?.label, ...markers.map((m) => m.label)].filter(Boolean);
  const caption = named.length ? named.slice(0, 4).join(' · ') : '';

  if (!centre) {
    // No coordinates is a real answer, not a broken map: a generated city has
    // none on purpose. See the note in `destinations.json`.
    return (
      <div className="a2-map a2-map--empty" role="note">
        <p>No map for this one — there are no coordinates for it.</p>
      </div>
    );
  }

  return (
    <figure className="a2-map">
      <div className="a2-map__canvas" ref={host} aria-label={caption || 'Map'}>
        {ready !== 'ready' ? (
          <div className="a2-map__fallback">
            {ready === 'loading' ? (
              <p>Loading the map…</p>
            ) : (
              <p>
                The map could not load{key ? '' : ' — no Google Maps key is configured'}.
                {caption ? ` Showing: ${caption}.` : ''}
              </p>
            )}
          </div>
        ) : null}
      </div>
      {caption ? <figcaption className="a2-map__caption">{caption}</figcaption> : null}
    </figure>
  );
}
