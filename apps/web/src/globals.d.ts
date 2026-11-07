/** The deployment's Maps key, set from `/api/meta` for the travel map views. */
export {};

declare global {
  interface Window {
    __A2UI_MAPS_KEY?: string;
  }
}
