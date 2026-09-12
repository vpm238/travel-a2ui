/**
 * The surface store: what the host knows about the UI the agent has drawn.
 *
 * A2UI arrives as messages, not as a tree. `createSurface` opens one,
 * `updateComponents` fills it with a flat adjacency list, `updateDataModel`
 * seeds the values components bind to, `deleteSurface` closes it. The store's
 * job is to fold that stream into something React can render, and to send the
 * user's edits back the other way.
 *
 * Two design choices worth stating:
 *
 * - **Components are replaced per id, not appended.** An agent revising one
 *   card should not have to re-send the surface, and a streaming compile that
 *   re-emits the whole tree every few tokens should not accumulate duplicates.
 * - **The data model is the only mutable state.** Components are declarative
 *   and stateless; a checkbox's checked-ness lives at its bound path, which is
 *   also exactly what the next agent turn reads. There is no second source of
 *   truth to get out of sync.
 */

import type { A2uiMessage, ComponentNode, Json, JsonObject } from '@travel-a2ui/express';

export interface Surface {
  id: string;
  catalogId: string;
  /** Component nodes by id, in the order they were first seen. */
  components: Map<string, ComponentNode>;
  dataModel: JsonObject;
  /** Bumped on every change, so React can compare cheaply. */
  revision: number;
  createdAt: number;
}

export type SurfaceListener = () => void;

function clone<T extends Json>(value: T): T {
  return (typeof structuredClone === 'function'
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value))) as T;
}

/** Reads a JSON Pointer out of an object, returning undefined for a miss. */
export function readPointer(root: Json | undefined, pointer: string): Json | undefined {
  if (root === undefined || root === null) return undefined;
  const segments = pointer.split('/').filter(Boolean);
  let cursor: Json | undefined = root;
  for (const segment of segments) {
    if (cursor === null || cursor === undefined) return undefined;
    if (Array.isArray(cursor)) {
      const index = Number(segment);
      if (!Number.isInteger(index)) return undefined;
      cursor = cursor[index];
    } else if (typeof cursor === 'object') {
      cursor = (cursor as JsonObject)[segment];
    } else {
      return undefined;
    }
  }
  return cursor;
}

/**
 * Writes a JSON Pointer, creating containers on the way down.
 *
 * A numeric segment creates an array, so a model that writes `/packing/0/item`
 * gets a list rather than an object with a `"0"` key — which is what every
 * list template downstream is expecting to iterate.
 */
export function writePointer(root: JsonObject, pointer: string, value: Json): void {
  const segments = pointer.split('/').filter(Boolean);
  if (segments.length === 0) return;

  let cursor: Json = root;
  for (let index = 0; index < segments.length - 1; index++) {
    const segment = segments[index]!;
    const nextIsIndex = /^\d+$/.test(segments[index + 1]!);
    const container = cursor as JsonObject | Json[];

    const existing = Array.isArray(container)
      ? container[Number(segment)]
      : (container as JsonObject)[segment];

    let next: Json;
    if (existing && typeof existing === 'object') {
      next = existing;
    } else {
      next = nextIsIndex ? [] : {};
      if (Array.isArray(container)) container[Number(segment)] = next;
      else (container as JsonObject)[segment] = next;
    }
    cursor = next;
  }

  const last = segments[segments.length - 1]!;
  if (Array.isArray(cursor)) cursor[Number(last)] = value;
  else (cursor as JsonObject)[last] = value;
}

export class SurfaceStore {
  private surfaces = new Map<string, Surface>();
  private listeners = new Set<SurfaceListener>();
  private version = 0;

  /** Applies A2UI messages, returning the surface ids they touched. */
  apply(messages: A2uiMessage[] | A2uiMessage): string[] {
    const list = Array.isArray(messages) ? messages : [messages];
    const touched = new Set<string>();

    for (const message of list) {
      if ('createSurface' in message) {
        const op = message.createSurface;
        const surface = this.ensure(op.surfaceId, op.catalogId);
        if (op.components) this.mergeComponents(surface, op.components);
        if (op.dataModel) this.mergeData(surface, '/', op.dataModel);
        surface.revision += 1;
        touched.add(op.surfaceId);
        continue;
      }

      if ('updateComponents' in message) {
        const op = message.updateComponents;
        const surface = this.ensure(op.surfaceId, '');
        this.mergeComponents(surface, op.components);
        surface.revision += 1;
        touched.add(op.surfaceId);
        continue;
      }

      if ('updateDataModel' in message) {
        const op = message.updateDataModel;
        const surface = this.ensure(op.surfaceId, '');
        this.mergeData(surface, op.path ?? '/', op.value);
        surface.revision += 1;
        touched.add(op.surfaceId);
        continue;
      }

      if ('deleteSurface' in message) {
        this.surfaces.delete(message.deleteSurface.surfaceId);
        touched.add(message.deleteSurface.surfaceId);
      }
    }

    if (touched.size > 0) this.emit();
    return [...touched];
  }

  private ensure(id: string, catalogId: string): Surface {
    let surface = this.surfaces.get(id);
    if (!surface) {
      surface = {
        id,
        catalogId,
        components: new Map(),
        dataModel: {},
        revision: 0,
        createdAt: Date.now(),
      };
      this.surfaces.set(id, surface);
    } else if (catalogId && !surface.catalogId) {
      surface.catalogId = catalogId;
    }
    return surface;
  }

  private mergeComponents(surface: Surface, components: ComponentNode[]): void {
    // A re-sent component replaces the old one in place, keeping its position.
    // This is what makes re-compiling on every streamed token cheap: the tree
    // converges instead of growing.
    for (const component of components) surface.components.set(component.id, component);
  }

  private mergeData(surface: Surface, pointer: string, value: Json): void {
    const clean = pointer === '' ? '/' : pointer;
    if (clean === '/') {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        // Merge rather than replace: a surface that seeds `/trip` and later
        // seeds `/filters` should end up with both.
        surface.dataModel = deepMerge(surface.dataModel, clone(value as JsonObject));
      }
      return;
    }
    writePointer(surface.dataModel, clean, clone(value));
  }

  /** Writes a user edit back to the data model at `pointer`. */
  setValue(surfaceId: string, pointer: string, value: Json): void {
    const surface = this.surfaces.get(surfaceId);
    if (!surface) return;
    surface.dataModel = { ...surface.dataModel };
    writePointer(surface.dataModel, pointer, value);
    surface.revision += 1;
    this.emit();
  }

  get(id: string): Surface | undefined {
    return this.surfaces.get(id);
  }

  has(id: string): boolean {
    return this.surfaces.has(id);
  }

  ids(): string[] {
    return [...this.surfaces.keys()];
  }

  remove(id: string): void {
    if (this.surfaces.delete(id)) this.emit();
  }

  clear(): void {
    if (this.surfaces.size === 0) return;
    this.surfaces.clear();
    this.emit();
  }

  /** Snapshot of a surface's data model — what an agent turn should read back. */
  snapshot(id: string): JsonObject {
    const surface = this.surfaces.get(id);
    return surface ? clone(surface.dataModel) : {};
  }

  subscribe(listener: SurfaceListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Monotonic counter for `useSyncExternalStore`. */
  getVersion(): number {
    return this.version;
  }

  private emit(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}

function deepMerge(base: JsonObject, incoming: JsonObject): JsonObject {
  const out: JsonObject = { ...base };
  for (const [key, value] of Object.entries(incoming)) {
    const existing = out[key];
    if (
      existing &&
      typeof existing === 'object' &&
      !Array.isArray(existing) &&
      value &&
      typeof value === 'object' &&
      !Array.isArray(value)
    ) {
      out[key] = deepMerge(existing as JsonObject, value as JsonObject);
    } else {
      out[key] = value;
    }
  }
  return out;
}
