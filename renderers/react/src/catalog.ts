/**
 * The travel catalog, as the A2UI SDK renders it.
 *
 * It is a catalog and nothing else — no message store, binding resolver or
 * function evaluator of its own, because those are `@a2ui/web_core`'s:
 *
 *   - the **schema** is ours, `catalogs/a2ui-travel/catalog.json`, loaded with
 *     `Catalog.fromJson` — the same document the server compiles against;
 *   - the **basic components and functions** are the SDK's own v1.0
 *     implementations, taken by name from `basicCatalog`;
 *   - the **travel components** are React, bound by the SDK's generic binder
 *     (`createComponentImplementation`), and the two client-side functions,
 *     `calcNights` and `equals`, are `createFunctionImplementation`s.
 *
 * Messages, state, bindings, checks and actions are all `@a2ui/web_core`'s.
 */

import {
  Catalog,
  createFunctionImplementation,
  type CatalogApi,
  type ComponentApi,
  type FunctionApi,
  type FunctionImplementation,
} from '@a2ui/web_core/v1_0';
import { basicCatalog } from '@a2ui/web_core/catalogs/basic/v1';
import { createComponentImplementation, type ReactCatalogComponent } from '@a2ui/react';

import { calcNights, equals } from './functions.js';
import { TRAVEL_VIEWS } from './components/travel.js';

type AnyRecord = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** What a catalog document looks like, as far as this file needs to know. */
export interface CatalogDocument {
  catalogId: string;
  protocolVersion?: string;
  components: AnyRecord;
  functions?: AnyRecord;
  [key: string]: unknown;
}

/** The client-side functions this catalog adds to the basic ones. */
const TRAVEL_FUNCTIONS: Record<string, (args: AnyRecord) => unknown> = { calcNights, equals };

/**
 * The catalog a `MessageProcessor` renders the travel app with.
 *
 * Throws if the document names a component or function nothing here can draw
 * or evaluate, because a catalog that offers the agent something the renderer
 * cannot show is the one mistake a catalog must not make.
 */
export function createTravelCatalog(
  document: CatalogDocument,
): Catalog<ReactCatalogComponent, FunctionImplementation> {
  const schemas: CatalogApi = Catalog.fromJson(document);

  const components: ReactCatalogComponent[] = [...schemas.components.entries()].map(([name, api]) => {
    const fromSdk = basicCatalog.components.get(name);
    if (fromSdk) return fromSdk;
    const view = TRAVEL_VIEWS[name];
    if (!view) throw new Error(`The catalog offers ${name}, and nothing here draws it.`);
    return createComponentImplementation(api, view);
  });

  const functions: FunctionImplementation[] = [...schemas.functions.entries()].map(([name, api]) => {
    const fromSdk = basicCatalog.functions.get(name);
    if (fromSdk) return fromSdk;
    const execute = TRAVEL_FUNCTIONS[name];
    if (!execute) throw new Error(`The catalog offers ${name}(), and nothing here evaluates it.`);
    return createFunctionImplementation(api, (args: AnyRecord) => execute(args));
  });

  // `fromJson` types its entries as schemas (`ComponentApi`, `FunctionApi`),
  // and `withEntries` keeps the type it was called on. The entries handed to it
  // are implementations, which is what this narrows to.
  return (schemas as Catalog<ComponentApi, FunctionApi>).withEntries(
    components,
    functions,
  ) as unknown as Catalog<ReactCatalogComponent, FunctionImplementation>;
}

/** Every component the travel catalog draws itself; the rest are the SDK's. */
export function travelComponentNames(): string[] {
  return Object.keys(TRAVEL_VIEWS);
}
