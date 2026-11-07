/**
 * What the page may put on `window` for the travel views.
 *
 * `google.maps` is the Maps JavaScript API once its script has loaded, and
 * `__A2UI_MAPS_KEY` is the deployment's (public, referrer-restricted) Maps key,
 * set by the app from `/api/meta`.
 */
export {};

interface MapsLibraryLoader {
  // The library's classes (`Map`, `Marker`, …), typed by Google's own
  // `@types/google.maps`, which this package does not depend on.
  importLibrary(name: string): Promise<Record<string, any>>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

declare global {
  interface Window {
    google?: { maps?: MapsLibraryLoader };
    __A2UI_MAPS_KEY?: string;
  }
}
