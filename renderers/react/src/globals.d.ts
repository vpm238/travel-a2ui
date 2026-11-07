/**
 * What the page may put on `window` for the travel views.
 *
 * `google.maps` is the Maps JavaScript API once its script has loaded. The
 * key it is loaded with comes from `MapsKeyContext`, not from `window`.
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
  }
}
