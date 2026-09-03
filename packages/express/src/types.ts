/**
 * Wire types for A2UI v0.9.1 and the catalog shapes the Express compiler reads.
 *
 * These mirror `specification/v0_9_1` in google/a2ui. They are deliberately
 * loose about component property values: a catalog is data, and the compiler's
 * job is to place values the catalog's schema permits, not to re-type them.
 */

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
export type JsonObject = { [k: string]: Json };

/** A JSON Schema fragment, crawled rather than fully resolved. */
export type SchemaNode = { [k: string]: unknown };

/** A2UI catalog: the registry of components and functions a host can render. */
export interface CatalogSchema {
  catalogId?: string;
  $id?: string;
  title?: string;
  description?: string;
  /** Free-text catalog guidance surfaced into generated prompts and skills. */
  instructions?: string;
  components: Record<string, SchemaNode>;
  functions?: Record<string, SchemaNode>;
  $defs?: Record<string, SchemaNode>;
  [k: string]: unknown;
}

/** A data binding: `{ path: "/trip/adults" }`. */
export interface DataBinding {
  path: string;
  [k: string]: Json;
}

/** A child-list template: `{ path: "/flights", componentId: "flightRow" }`. */
export interface ChildTemplate {
  path: string;
  componentId: Json;
}

/** A compiled component node inside `updateComponents`. */
export interface ComponentNode {
  id: string;
  component: string;
  [prop: string]: Json;
}

export type ProtocolVersion = 'v0.9' | 'v0.9.1' | 'v1.0';

export interface CreateSurfaceMessage {
  version: ProtocolVersion;
  createSurface: {
    surfaceId: string;
    catalogId: string;
    components?: ComponentNode[];
    dataModel?: JsonObject;
  };
}

export interface UpdateComponentsMessage {
  version: ProtocolVersion;
  updateComponents: { surfaceId: string; components: ComponentNode[] };
}

export interface UpdateDataModelMessage {
  version: ProtocolVersion;
  updateDataModel: { surfaceId: string; path: string; value: Json };
}

export interface DeleteSurfaceMessage {
  version: ProtocolVersion;
  deleteSurface: { surfaceId: string };
}

export interface CallFunctionMessage {
  version: ProtocolVersion;
  functionCallId: string;
  callFunction: { call: Json; args: Json };
}

export type A2uiMessage =
  | CreateSurfaceMessage
  | UpdateComponentsMessage
  | UpdateDataModelMessage
  | DeleteSurfaceMessage
  | CallFunctionMessage;

/** Envelope keys, kept in one place so a version bump is a single edit. */
export const SurfaceOperation = {
  CREATE: 'createSurface',
  UPDATE_COMPONENTS: 'updateComponents',
  DELETE: 'deleteSurface',
  UPDATE_DATA: 'updateDataModel',
  CALL_FUNC: 'callFunction',
  SURFACE: 'surface',
} as const;

/** The sentinel tags that fence an Express block inside model prose. */
export const A2UI_OPEN = '<a2ui>';
export const A2UI_CLOSE = '</a2ui>';
