/**
 * What a component needs to render itself, and how it talks back.
 */

import type { ComponentNode, Json, JsonObject } from '@travel-a2ui/express';
import type { ReactNode } from 'react';

import { isAction, resolve, type ResolveScope } from './binding.js';
import { callFunction } from './functions.js';

/** An interaction on a surface, on its way back to the agent. */
export interface A2uiEvent {
  surfaceId: string;
  name: string;
  /** The action's context, with every binding already resolved. */
  context: JsonObject;
  /** The surface's whole data model at the moment of the interaction. */
  dataModel: JsonObject;
  /**
   * Which component fired it.
   *
   * A host needs this to tell an edit from a decision. Dragging a slider and
   * pressing Apply both arrive here as events, and only one of them is the
   * traveler saying something — the sidebar's whole behaviour depends on being
   * able to distinguish them.
   */
  source?: { id: string; component: string };
  timestamp: number;
}

export interface RenderContext {
  surfaceId: string;
  components: Map<string, ComponentNode>;
  emit(event: A2uiEvent): void;
  setValue(pointer: string, value: Json): void;
  dataModel: JsonObject;
  renderChild(id: Json | undefined, scope: ResolveScope): ReactNode;
  renderChildren(value: Json | undefined, scope: ResolveScope): ReactNode[];
  /** Marks a bound field as touched, so its validation errors may show. */
  touch(pointer: string): void;
  isTouched(pointer: string): boolean;
}

export interface ComponentProps {
  node: ComponentNode;
  scope: ResolveScope;
  ctx: RenderContext;
}

/**
 * Runs an action: dispatch an event to the agent, or call a client function.
 *
 * Returns true if anything happened, so a component can render itself as
 * inert when it was handed nothing to do.
 */
export function runAction(
  action: Json | undefined,
  scope: ResolveScope,
  ctx: RenderContext,
  /** The component the action hangs off, so the event can name its source. */
  node?: ComponentNode,
): boolean {
  if (!isAction(action)) return false;

  if (action.functionCall) {
    const args = (action.functionCall.args ?? {}) as JsonObject;
    const resolved: JsonObject = {};
    for (const [key, value] of Object.entries(args)) resolved[key] = resolve(value, scope) ?? null;
    callFunction(action.functionCall.call, resolved);
    return true;
  }

  if (action.event) {
    const context: JsonObject = {};
    for (const [key, value] of Object.entries(action.event.context ?? {})) {
      context[key] = resolve(value, scope) ?? null;
    }
    ctx.emit({
      surfaceId: ctx.surfaceId,
      name: action.event.name,
      context,
      dataModel: ctx.dataModel,
      ...(node
        ? { source: { id: String(node['id'] ?? ''), component: String(node['component'] ?? '') } }
        : {}),
      timestamp: Date.now(),
    });
    return true;
  }

  return false;
}
