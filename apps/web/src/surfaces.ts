/**
 * The app's surfaces, held by the A2UI SDK.
 *
 * One `MessageProcessor` from `@a2ui/web_core` for the whole conversation —
 * every inline card, the panel and the home dashboard — so pressing something
 * in one is answered in another. This file is the one place the app talks to
 * it, and it is deliberately thin: applying messages, listing surfaces, reading
 * a component for the transcript, and telling React when the set of surfaces
 * changed. Everything a surface *does* — binding, functions, checks, two-way
 * input, actions — is the SDK's.
 */

import { MessageProcessor, peekValue, type ActionPayload, type SurfaceModel } from '@a2ui/web_core/v1_0';
import { createTravelCatalog, type CatalogDocument } from '@travel-a2ui/renderer';

import catalogDocument from '../../../catalogs/a2ui-travel/catalog.json';

type Json = Record<string, unknown>;

/** One catalog for the app: built once, shared by every processor. */
let catalog: ReturnType<typeof createTravelCatalog> | null = null;
export function travelCatalog() {
  catalog ??= createTravelCatalog(catalogDocument as unknown as CatalogDocument);
  return catalog;
}

/** A press, as the app forwards it: the SDK's action plus the surface's values. */
export interface SurfacePress extends ActionPayload {
  dataModel: Json;
}

/** What the processor refused, kept for the Wire view rather than thrown. */
export interface RejectedMessage {
  at: string;
  surfaceId?: string;
  message: string;
}

export class Surfaces {
  readonly processor: MessageProcessor;
  private listeners = new Set<() => void>();
  private pressListener: ((press: SurfacePress) => void) | null = null;
  private version = 0;
  readonly rejected: RejectedMessage[] = [];

  constructor() {
    this.processor = new MessageProcessor([travelCatalog()], (action) => this.pressed(action));
    this.processor.onSurfaceCreated(() => this.bump());
    this.processor.onSurfaceDeleted(() => this.bump());
  }

  /** Applies a batch, one message at a time, so one bad message costs only itself. */
  apply(messages: unknown[]): void {
    for (const message of messages) {
      for (const error of this.processor.processMessagesWithErrors([message])) {
        const detail = (error as { error?: { message?: string; surfaceId?: string } }).error;
        this.rejected.push({
          at: new Date().toISOString(),
          surfaceId: detail?.surfaceId,
          message: detail?.message ?? JSON.stringify(error),
        });
        if (this.rejected.length > 50) this.rejected.shift();
        console.warn('[a2ui] rejected a message:', detail?.message ?? error);
      }
    }
    this.bump();
  }

  ids(): string[] {
    return [...this.processor.getSurfaces().keys()];
  }

  get(id: string): SurfaceModel | undefined {
    return this.processor.getSurface(id) as SurfaceModel | undefined;
  }

  has(id: string): boolean {
    return Boolean(this.get(id)?.componentsModel.has('root'));
  }

  /** A component's properties as the agent wrote them, for naming a press. */
  component(surfaceId: string, id: string): Json | undefined {
    const model = this.get(surfaceId)?.componentsModel.get(id);
    return model ? { component: model.type, ...model.properties } : undefined;
  }

  /** A surface's data model, as a plain object. */
  data(surfaceId: string): Json {
    const signal = this.get(surfaceId)?.dataModel.getSignal<Json>('/');
    const value = signal ? peekValue(signal) : undefined;
    return value && typeof value === 'object' ? (JSON.parse(JSON.stringify(value)) as Json) : {};
  }

  /** A surface as one `createSurface`, for the Wire view. */
  snapshot(surfaceId: string): Json | undefined {
    const surface = this.get(surfaceId);
    if (!surface) return undefined;
    const components = [...surface.componentsModel.getAll().values()].map((model) => ({
      id: model.id,
      component: model.type,
      ...model.properties,
    }));
    const dataModel = this.data(surfaceId);
    return {
      surfaceId,
      catalogId: surface.catalog?.id ?? '',
      components,
      ...(Object.keys(dataModel).length ? { dataModel } : {}),
    };
  }

  clear(): void {
    for (const id of this.ids()) this.processor.processMessages([{ version: '1.0', deleteSurface: { surfaceId: id } }]);
    this.bump();
  }

  onPress(listener: ((press: SurfacePress) => void) | null): void {
    this.pressListener = listener;
  }

  // React's external-store contract: a stable subscribe and a cheap snapshot.
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getVersion = (): number => this.version;

  /**
   * A press, with the surface's values when the surface asked for them.
   *
   * `createSurface.sendDataModel` is how an agent asks for every value on a
   * surface with each action; the server sets it on every surface, and reads
   * the trip from it. A surface that did not ask is sent only the action.
   */
  private pressed(action: ActionPayload): void {
    const wants = this.get(action.surfaceId)?.sendDataModel === true;
    this.pressListener?.({ ...action, dataModel: wants ? this.data(action.surfaceId) : {} });
  }

  private bump(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}
