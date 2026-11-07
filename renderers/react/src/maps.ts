/**
 * The Google Maps settings a host gives the travel map views.
 *
 * A context rather than a global: the `GoogleMap` the agent composes is a leaf
 * of a tree no app code builds, so its settings cannot arrive as props; a
 * provider around the surfaces reaches every map in them.
 *
 *     <MapsKeyContext.Provider value={mapsApiKey}>…surfaces…</MapsKeyContext.Provider>
 *
 * The key is the deployment's public, referrer-restricted Maps JavaScript API
 * key. Without one, a map says it cannot load rather than failing silently.
 */

import { createContext } from 'react';

export const MapsKeyContext = createContext<string>('');
