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
 * their element's whole job is to turn resolved props into Maps JavaScript API
 * primitives. Our renderer already resolves A2UI props, so it draws those
 * primitives from the props we already have, and the page keeps one data model
 * instead of mirroring it into a second one.
 *
 * Where this deliberately differs: Google's component draws `<gmp-map-3d>`,
 * and the 3D map has no flat road map — its two modes are HYBRID and
 * SATELLITE, both of them photographic. Tried on a real trip, satellite
 * imagery turned out to be the wrong surface for a decision: it is beautiful
 * and it is hard to read, and a traveller comparing two hotels wants streets
 * and labels, not roofs. So this draws the 2D `google.maps.Map`, where
 * `roadmap` means a road map and `satellite` still means satellite.
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
 * The stable channel and the `maps` library, and nothing else. Every extra
 * library is a separate API somebody has to enable: `places` and `routes` were
 * in this URL for components we never built, and a deployment with only the
 * Maps JavaScript API switched on would have paid for them with an error.
 *
 * The promise is cached on the module so eight maps on one home screen are one
 * script tag and one download.
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
      'https://maps.googleapis.com/maps/api/js?loading=async&libraries=maps' +
      `&key=${encodeURIComponent(apiKey)}`;
    // `loading=async` means the tag fires `onload` when the *bootstrap* is
    // parsed, not when `google.maps` exists — which is the whole point of it.
    // Resolving on `onload` alone handed the component an API that was not
    // there yet: the effect returned early, `ready` never changed again, and
    // the card sat as an empty rectangle with nothing in the console. So wait
    // for the thing we actually need.
    script.onload = () => {
      const started = Date.now();
      const settle = () => {
        const maps = (window as unknown as Record<string, any>)['google']?.maps;
        if (typeof maps?.importLibrary === 'function') return resolve(true);
        if (Date.now() - started > 15_000) return resolve(false);
        setTimeout(settle, 50);
      };
      settle();
    };
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
    let cancelled = false;

    void (async () => {
      const maps = (window as unknown as Record<string, any>)['google']?.maps;
      if (!maps?.importLibrary) return;
      // Three libraries, because the modular loader puts them in three places
      // and getting that wrong fails silently: `LatLngBounds` is in `core` and
      // `Marker` is in `marker`, so reaching for them on `google.maps` after
      // importing only `maps` throws inside this async function, where nothing
      // is listening, and the card renders an empty box with no error anywhere.
      const [{ Map, Polyline }, { LatLngBounds }, { Marker }] = await Promise.all([
        maps.importLibrary('maps'),
        maps.importLibrary('core'),
        maps.importLibrary('marker'),
      ]);
      if (cancelled) return;
      element.replaceChildren();

      const canvas = document.createElement('div');
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      element.appendChild(canvas);

      const map = new Map(canvas, {
        center: centre,
        zoom,
        mapTypeId: mode === 'satellite' ? 'satellite' : 'roadmap',
        heading,
        tilt,
        // The chrome a traveller does not need on a card inside a chat. The map
        // is here to be read, not operated: no Street View peg, no map-type
        // switcher, no fullscreen. Panning and zooming stay, because "what is
        // near this" is a question people answer by dragging.
        disableDefaultUI: true,
        zoomControl: true,
        keyboardShortcuts: false,
      });

      const bounds = new LatLngBounds();
      let points = 0;

      for (const place of anchor ? [anchor, ...markers] : markers) {
        // `Marker` rather than `AdvancedMarkerElement`, which needs a Map ID
        // configured in the cloud console. This component works with nothing
        // but a key, and a pin that needs a second piece of setup is a pin that
        // is missing on somebody's deployment.
        new Marker({
          map,
          position: { lat: place.lat, lng: place.lng },
          title: place.label,
          ...(anchor && place === anchor
            ? { zIndex: 10, label: { text: '★', color: '#fff', fontSize: '14px' } }
            : {}),
        });
        bounds.extend({ lat: place.lat, lng: place.lng });
        points += 1;
      }

      for (const leg of legs) {
        new Polyline({
          map,
          path: [
            { lat: leg.from.lat, lng: leg.from.lng },
            { lat: leg.to.lat, lng: leg.to.lng },
          ],
          geodesic: true,
          strokeOpacity: 0.9,
          strokeWeight: 3,
        });
        for (const end of [leg.from, leg.to]) {
          bounds.extend({ lat: end.lat, lng: end.lng });
          points += 1;
        }
      }

      // More than one place means the interesting thing is the *span* — how far
      // the hotel is from the museum, whether the route doubles back. A centre
      // and a zoom cannot express that without the agent doing trigonometry, so
      // the host fits the map to what is on it and the agent's `zoom` becomes
      // the answer for the single-pin case, where it is exactly right.
      if (points > 1) map.fitBounds(bounds, 48);
    })().catch((problem) => {
      // Otherwise this is a silent empty rectangle: the promise is detached, so
      // a throw in here reaches no one. It cost an afternoon once.
      console.error('[a2ui] the map could not be drawn', problem);
      if (!cancelled) setReady('unavailable');
    });

    return () => {
      cancelled = true;
      element.replaceChildren();
    };
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
