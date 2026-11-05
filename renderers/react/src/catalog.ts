/**
 * The travel catalog, as the A2UI SDK renders it.
 *
 * This package used to be a renderer: its own message store, its own binding
 * resolver, its own function evaluator and check runner, and its own drawing of
 * every basic component — a reimplementation of `@a2ui/web_core`, which is what
 * the A2UI team's review called it. It drifted the way reimplementations do:
 * checks read `call` where 1.0 writes `@call` and so never ran, a pointer
 * writer would follow `__proto__`, and our basic `Text` accepted heading
 * variants v1.0 had removed.
 *
 * Now it is a catalog and nothing else:
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

import { Catalog, createFunctionImplementation } from '@a2ui/web_core/v1_0';
import { basicCatalog } from '@a2ui/web_core/catalogs/basic/v1';
import { createComponentImplementation } from '@a2ui/react/v0_9';

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
export function createTravelCatalog(document: CatalogDocument): Catalog<any, any> {
  const schemas = Catalog.fromJson(document) as unknown as Catalog<any, any>;
  const basic = basicCatalog as unknown as Catalog<any, any>;

  const components = [...schemas.components.entries()].map(([name, api]) => {
    const fromSdk = basic.components.get(name);
    if (fromSdk) return fromSdk;
    const view = TRAVEL_VIEWS[name];
    if (!view) throw new Error(`The catalog offers ${name}, and nothing here draws it.`);
    return createComponentImplementation(api, view as never);
  });

  const functions = [...schemas.functions.entries()].map(([name, api]) => {
    const fromSdk = basic.functions.get(name);
    if (fromSdk) return fromSdk;
    const execute = TRAVEL_FUNCTIONS[name];
    if (!execute) throw new Error(`The catalog offers ${name}(), and nothing here evaluates it.`);
    return createFunctionImplementation(api as never, ((args: AnyRecord) => execute(args)) as never);
  });

  return schemas.withEntries(components, functions);
}

/** Every component the travel catalog draws itself; the rest are the SDK's. */
export function travelComponentNames(): string[] {
  return Object.keys(TRAVEL_VIEWS);
}
