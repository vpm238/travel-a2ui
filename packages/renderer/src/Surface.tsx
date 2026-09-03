/**
 * The host: turns a surface in the store into React elements.
 *
 * Rendering an adjacency list means following ids, and ids come from a model,
 * so two guards are not optional:
 *
 *   - a **depth cap**, because `a → b → a` is one bad token away, and a
 *     stack overflow takes the whole page with it; and
 *   - a **visited set per path**, so a component that lists itself as its own
 *     child renders once and stops rather than looping.
 *
 * Everything else is dispatch: look the component up in the registry, hand it
 * the node, the scope and the context, and let it read its own props.
 */

import { useCallback, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import type { ComponentNode, Json, JsonObject } from '@travel-a2ui/express';

import { isTemplate, type ResolveScope } from './binding.js';
import type { A2uiEvent, ComponentProps, RenderContext } from './context.js';
import { readPointer, type Surface, type SurfaceStore } from './store.js';
import * as basic from './components/basic.js';
import * as travel from './components/travel.js';

const MAX_DEPTH = 24;

type Renderer = (props: ComponentProps) => ReactNode;

const REGISTRY: Record<string, Renderer> = {
  // basic catalog
  Text: basic.Text,
  Image: basic.ImageComponent,
  Icon: basic.IconComponent,
  Video: basic.VideoComponent,
  AudioPlayer: basic.AudioComponent,
  Row: basic.Row,
  Column: basic.Column,
  List: basic.List,
  Card: basic.Card,
  Tabs: basic.Tabs,
  Modal: basic.Modal,
  Divider: basic.Divider,
  Button: basic.Button,
  TextField: basic.TextField,
  CheckBox: basic.CheckBox,
  ChoicePicker: basic.ChoicePicker,
  Slider: basic.Slider,
  DateTimeInput: basic.DateTimeInput,

  // travel catalog
  FlightOption: travel.FlightOption,
  HotelCard: travel.HotelCard,
  ItineraryDay: travel.ItineraryDay,
  ActivityItem: travel.ActivityItem,
  MapPreview: travel.MapPreview,
  PriceSummary: travel.PriceSummary,
  DateRangePicker: travel.DateRangePicker,
  TravelerCounter: travel.TravelerCounter,
  StatTile: travel.StatTile,
  ProgressMeter: travel.ProgressMeter,
  WeatherStrip: travel.WeatherStrip,
  ExpenseSplit: travel.ExpenseSplit,
};

/** Component names this host can draw — what a catalog compatibility check reads. */
export function supportedComponents(): string[] {
  return Object.keys(REGISTRY);
}

/** Subscribes to one surface in the store. */
export function useSurface(store: SurfaceStore, surfaceId: string): Surface | undefined {
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store]);
  const version = useSyncExternalStore(
    subscribe,
    () => store.getVersion(),
    () => store.getVersion(),
  );
  return useMemo(() => store.get(surfaceId), [store, surfaceId, version]);
}

export interface A2uiSurfaceProps {
  store: SurfaceStore;
  surfaceId: string;
  onEvent?: (event: A2uiEvent) => void;
  /** Rendered when the surface does not exist yet. */
  fallback?: ReactNode;
  className?: string;
  /**
   * Whether the surface still accepts input. Default true.
   *
   * A card answers the message it was drawn under. Once the conversation has
   * moved past it, clicking it re-answers a question that was already settled —
   * and the surface it belongs to no longer describes where the trip is. So a
   * spent surface stays readable, as the record of what was chosen, and stops
   * being operable. `inert` takes it out of the tab order too, which a dimmed
   * div would not.
   */
  interactive?: boolean;
}

export function A2uiSurface({
  store,
  surfaceId,
  onEvent,
  fallback = null,
  className,
  interactive = true,
}: A2uiSurfaceProps) {
  const surface = useSurface(store, surfaceId);
  const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set());
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  // A ref so toggling interactivity does not rebuild the whole render context.
  const interactiveRef = useRef(interactive);
  interactiveRef.current = interactive;

  const ctx = useMemo<RenderContext | null>(() => {
    if (!surface) return null;

    const context: RenderContext = {
      surfaceId,
      components: surface.components,
      dataModel: surface.dataModel,
      emit: (event: A2uiEvent) => {
        if (!interactiveRef.current) return;
        onEventRef.current?.(event);
      },
      setValue: (pointer, value) => store.setValue(surfaceId, pointer, value),
      touch: (pointer) =>
        setTouched((previous) => {
          if (previous.has(pointer)) return previous;
          const next = new Set(previous);
          next.add(pointer);
          return next;
        }),
      isTouched: (pointer) => touched.has(pointer),
      renderChild: () => null,
      renderChildren: () => [],
    };

    const render = (id: Json | undefined, scope: ResolveScope, depth: number, seen: ReadonlySet<string>): ReactNode => {
      if (typeof id !== 'string' || depth > MAX_DEPTH || seen.has(id)) return null;
      const node = surface.components.get(id);
      if (!node) return null;

      const Component = REGISTRY[String(node['component'])] ?? basic.Unknown;
      const nextSeen = new Set(seen);
      nextSeen.add(id);

      const scoped: RenderContext = {
        ...context,
        renderChild: (childId, childScope) => render(childId, childScope, depth + 1, nextSeen),
        renderChildren: (value, childScope) =>
          renderChildren(value, childScope, depth + 1, nextSeen),
      };

      return <Component key={`${id}:${scope.itemPointer}`} node={node as ComponentNode} scope={scope} ctx={scoped} />;
    };

    const renderChildren = (
      value: Json | undefined,
      scope: ResolveScope,
      depth: number,
      seen: ReadonlySet<string>,
    ): ReactNode[] => {
      if (Array.isArray(value)) {
        return value.map((id) => render(id, scope, depth, seen));
      }
      if (isTemplate(value)) {
        // A list template: render the template component once per item, with
        // relative paths resolving inside that item.
        const pointer = value.path.startsWith('/')
          ? value.path
          : scope.itemPointer
            ? `${scope.itemPointer}/${value.path}`
            : `/${value.path}`;
        const items = readPointer(scope.model, pointer);
        if (!Array.isArray(items)) return [];
        return items.map((_item, index) =>
          render(value.componentId, { model: scope.model, itemPointer: `${pointer}/${index}` }, depth, seen),
        );
      }
      if (typeof value === 'string') return [render(value, scope, depth, seen)];
      return [];
    };

    context.renderChild = (id, scope) => render(id, scope, 0, new Set());
    context.renderChildren = (value, scope) => renderChildren(value, scope, 0, new Set());
    return context;
    // `touched` participates so validation messages appear on blur.
  }, [store, surface, surfaceId, touched]);

  if (!surface || !ctx) return <>{fallback}</>;

  const scope: ResolveScope = { model: surface.dataModel as JsonObject, itemPointer: '' };
  const root = ctx.renderChild('root', scope);

  return (
    <div
      className={['a2-surface', interactive ? null : 'a2-surface--spent', className]
        .filter(Boolean)
        .join(' ')}
      data-surface={surfaceId}
      inert={interactive ? undefined : true}
    >
      {root ?? fallback}
    </div>
  );
}
