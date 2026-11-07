/**
 * The app's surfaces, held by the A2UI SDK.
 *
 * One `MessageProcessor` from `@a2ui/web_core` for the whole conversation —
 * every inline card, the panel and the home dashboard — so pressing something
 * in one is answered in another. This file is the one place the app talks to
 * it, and it is deliberately thin: applying messages, listing surfaces, and
 * speaking A2UI v1.0 back to the agent. Everything a surface *does* (binding,
 * functions, checks, two-way input, actions) is the SDK's.
 *
 * What goes back to the agent with every request, all of it the SDK's own:
 *
 *   - `{version: "1.0", action}` for a press;
 *   - `{version: "1.0", error}` for every message the processor refused;
 *   - `a2uiRendererCapabilities`, from `getRendererCapabilities`, so the agent
 *     knows which catalogs this renderer draws;
 *   - `a2uiRendererDataModel`, from `getRendererDataModel`, the data model of
 *     every surface that asked to send one.
 */

import {
  MessageProcessor,
  peekValue,
  type ActionPayload,
  type RendererErrorMessage,
  type SurfaceModel,
} from '@a2ui/web_core/v1_0';
import type { ReactCatalogComponent } from '@a2ui/react';
import type { RendererMetadata } from './api.js';

export { actionMessage } from './api.js';
import { createTravelCatalog, type CatalogDocument } from '@travel-a2ui/renderer';

import catalogDocument from '../../../catalogs/a2ui-travel/catalog.json';

type Json = Record<string, unknown>;

/** One catalog for the app: built once, shared by every processor. */
let catalog: ReturnType<typeof createTravelCatalog> | null = null;
export function travelCatalog() {
  catalog ??= createTravelCatalog(catalogDocument as CatalogDocument);
  return catalog;
}

/** A press, as the SDK reports it. */
export type SurfacePress = ActionPayload;

/** What the processor refused, kept for the Wire view rather than thrown. */
export interface RejectedMessage {
  at: string;
  surfaceId?: string;
  message: string;
}

export class Surfaces {
  readonly processor: MessageProcessor<ReactCatalogComponent>;
  private listeners = new Set<() => void>();
  private pressListener: ((press: SurfacePress) => void) | null = null;
  private version = 0;
  readonly rejected: RejectedMessage[] = [];
  /** Errors not yet sent to the agent, as v1.0 renderer messages. */
  private unsent: RendererErrorMessage[] = [];

  constructor() {
    this.processor = new MessageProcessor<ReactCatalogComponent>([travelCatalog()], (action) => this.pressListener?.(action), {
      errorHandler: (error) => this.report(error),
    });
    this.processor.onSurfaceCreated(() => this.bump());
    this.processor.onSurfaceDeleted(() => this.bump());
  }

  /** Applies a batch, one message at a time, so one bad message costs only itself. */
  apply(messages: unknown[]): void {
    for (const message of messages) {
      for (const error of this.processor.processMessagesWithErrors([message])) this.report(error);
    }
    this.bump();
  }

  /** Everything the agent should hear about this renderer, for the next request. */
  metadata(): RendererMetadata {
    const dataModel = this.processor.getRendererDataModel('1.0');
    return {
      a2uiRendererCapabilities: this.processor.getRendererCapabilities({ versions: ['1.0'] }),
      ...(dataModel ? { a2uiRendererDataModel: dataModel } : {}),
    };
  }

  /** The errors to forward, once each. */
  takeErrors(): RendererErrorMessage[] {
    const out = this.unsent;
    this.unsent = [];
    return out;
  }

  ids(): string[] {
    return [...this.processor.getSurfaces().keys()];
  }

  get(id: string): SurfaceModel<ReactCatalogComponent> | undefined {
    return this.processor.getSurface(id);
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

  private report(error: RendererErrorMessage): void {
    if (this.unsent.includes(error)) return;
    this.unsent.push(error);
    if (this.unsent.length > 20) this.unsent.shift();
    this.rejected.push({ at: new Date().toISOString(), surfaceId: error.error.surfaceId, message: error.error.message });
    if (this.rejected.length > 50) this.rejected.shift();
    console.warn('[a2ui] rejected a message:', error.error.message);
  }

  private bump(): void {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}
