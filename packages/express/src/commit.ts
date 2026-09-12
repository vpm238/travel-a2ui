/**
 * Making "one surface, one button, everything sent together" a guarantee.
 *
 * A2UI already has the canonical mechanism for submitting a form: a button
 * whose action declares a *context* of bound paths, which every renderer —
 * Web, Swift, Kotlin, Flutter — resolves against the data model and posts back.
 * Nothing client-side is needed to make that work, which is exactly why it is
 * the right mechanism: a host that diffs its own data model to work out what
 * changed has invented a second protocol that only it speaks.
 *
 * The catch is that it depends on the model remembering to bind every field it
 * asked about. Forget one, and the traveler's answer is silently dropped — the
 * hardest class of bug to see, because the surface looks right and the trip is
 * merely wrong.
 *
 * So this closes it server-side. After a surface compiles, the paths its editors
 * write to are known exactly; any commit button missing one gets it. The model
 * is still asked to bind them (it produces better key names than this does), but
 * the correctness no longer depends on the asking.
 *
 * This runs on the server, once, before the messages ever go out — so a thin
 * client gets a surface that is already right, and gains no logic to make it so.
 */

import type { A2uiMessage, ComponentNode, Json, JsonObject } from './types.js';

/**
 * Components that compose an answer rather than commit one.
 *
 * The distinction is the whole interaction model: dragging a slider or typing a
 * name is someone still answering, and only a button means they are done. These
 * are the components whose bound paths a commit button must therefore carry.
 */
export const VALUE_EDITORS: ReadonlySet<string> = new Set([
  'TextField',
  'CheckBox',
  'ChoicePicker',
  'Slider',
  'DateTimeInput',
  'DateRangePicker',
  'TravelerCounter',
]);

/** Every `{ path }` binding anywhere inside a component's properties. */
function boundPaths(node: ComponentNode): string[] {
  const found: string[] = [];

  const walk = (value: Json): void => {
    if (Array.isArray(value)) {
      for (const item of value) walk(item);
      return;
    }
    if (!value || typeof value !== 'object') return;
    const record = value as JsonObject;
    // A child-list template's `path` points at a collection to repeat over, not
    // at a value someone edited.
    if (typeof record['path'] === 'string' && record['componentId'] === undefined) {
      found.push(record['path'] as string);
    }
    for (const [key, nested] of Object.entries(record)) {
      if (key === 'path') continue;
      walk(nested);
    }
  };

  for (const [key, value] of Object.entries(node)) {
    if (key === 'id' || key === 'component') continue;
    walk(value);
  }
  return found;
}

/** `/trip/startDate` → `startDate`, kept unique against what is already there. */
function keyFor(path: string, taken: ReadonlySet<string>): string {
  const segments = path.split('/').filter(Boolean);
  const base = segments[segments.length - 1] || 'value';
  if (!taken.has(base)) return base;
  // `/trip/origin` colliding with `/leg/origin` becomes `tripOrigin`.
  for (let depth = 2; depth <= segments.length; depth += 1) {
    const parts = segments.slice(-depth);
    const candidate =
      parts[0] + parts.slice(1).map((p) => p[0]!.toUpperCase() + p.slice(1)).join('');
    if (!taken.has(candidate)) return candidate;
  }
  let n = 2;
  while (taken.has(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

/**
 * The container everything else hangs off.
 *
 * `root` by convention — the Express examples and the generated skill both use
 * it — and otherwise the one component nothing else lists as a child, which is
 * the same thing said structurally.
 */
function rootOf(components: ComponentNode[]): ComponentNode | null {
  const named = components.find((node) => node.id === 'root');
  if (named) return named;

  const claimed = new Set<string>();
  for (const node of components) {
    const children = node['children'];
    if (Array.isArray(children)) {
      for (const child of children) if (typeof child === 'string') claimed.add(child);
    }
  }
  return components.find((node) => !claimed.has(node.id)) ?? null;
}

/** The `action.event` object on a component, when it has one. */
function eventOf(node: ComponentNode): JsonObject | null {
  const action = node['action'];
  if (!action || typeof action !== 'object' || Array.isArray(action)) return null;
  const event = (action as JsonObject)['event'];
  if (!event || typeof event !== 'object' || Array.isArray(event)) return null;
  return event as JsonObject;
}

/**
 * Adds every editable path on a surface to that surface's commit buttons.
 *
 * A surface with two buttons gets both filled: which one the traveler presses
 * decides what the agent *does*, not how much of their answer survives the trip
 * back.
 *
 * Paths the model already bound are left exactly as they are, under whatever key
 * it chose — it names things better than an algorithm splitting on slashes, and
 * a context that changes shape between turns is worse than an ugly key.
 */
export function bindCommitContext(messages: A2uiMessage[]): A2uiMessage[] {
  // Components arrive across several messages for one surface, and a button can
  // be created before the field it must carry. So: collect per surface first.
  const editable = new Map<string, Set<string>>();
  const buttons = new Map<string, ComponentNode[]>();

  const visit = (surfaceId: string, components: ComponentNode[] | undefined): void => {
    for (const node of components ?? []) {
      if (VALUE_EDITORS.has(node.component)) {
        const paths = editable.get(surfaceId) ?? new Set<string>();
        for (const path of boundPaths(node)) paths.add(path);
        editable.set(surfaceId, paths);
      }
      if (eventOf(node)) {
        buttons.set(surfaceId, [...(buttons.get(surfaceId) ?? []), node]);
      }
    }
  };

  for (const message of messages) {
    if ('createSurface' in message) {
      visit(message.createSurface.surfaceId, message.createSurface.components);
    } else if ('updateComponents' in message) {
      visit(message.updateComponents.surfaceId, message.updateComponents.components);
    }
  }

  // A surface of editors with nothing to press is a dead end: the traveler has
  // composed an answer and there is no way to send it. The skill says to draw
  // the button, and mostly it does; this is the case where it did not.
  //
  // Adding one here rather than in the browser is what keeps the guarantee
  // portable. The old fix was a bar the React app drew for itself, which meant
  // an iOS client shipped the dead end.
  for (const [surfaceId, paths] of editable) {
    if (paths.size === 0 || (buttons.get(surfaceId)?.length ?? 0) > 0) continue;

    // The components are wherever they actually are: `createSurface` carries
    // them in v1.0 and often nothing in v0.9.1, where they arrive in a following
    // `updateComponents`. Taking the first message for the surface would find an
    // empty one and give up.
    let components: ComponentNode[] | null = null;
    let root: ComponentNode | null = null;
    for (const message of messages) {
      const candidate =
        'createSurface' in message && message.createSurface.surfaceId === surfaceId
          ? message.createSurface.components
          : 'updateComponents' in message && message.updateComponents.surfaceId === surfaceId
            ? message.updateComponents.components
            : undefined;
      if (!candidate?.length) continue;
      const found = rootOf(candidate);
      if (found && Array.isArray(found['children'])) {
        components = candidate;
        root = found;
      }
    }
    if (!components || !root) continue;

    const commit: ComponentNode = {
      id: '__commit',
      component: 'Button',
      label: 'Send',
      action: { event: { name: 'commit_surface', context: {} } },
    };
    components.push(commit);
    (root['children'] as Json[]).push(commit.id);
    buttons.set(surfaceId, [commit]);
  }

  for (const [surfaceId, paths] of editable) {
    if (paths.size === 0) continue;
    for (const node of buttons.get(surfaceId) ?? []) {
      const event = eventOf(node);
      if (!event) continue;

      const existing =
        event['context'] && typeof event['context'] === 'object' && !Array.isArray(event['context'])
          ? { ...(event['context'] as JsonObject) }
          : {};

      const alreadyBound = new Set(
        Object.values(existing)
          .map((value) =>
            value && typeof value === 'object' && !Array.isArray(value)
              ? (value as JsonObject)['path']
              : undefined,
          )
          .filter((path): path is string => typeof path === 'string'),
      );

      const keys = new Set(Object.keys(existing));
      for (const path of paths) {
        if (alreadyBound.has(path)) continue;
        const key = keyFor(path, keys);
        keys.add(key);
        existing[key] = { path };
      }

      event['context'] = existing;
    }
  }

  return messages;
}

/**
 * Night counts the model wrote as text, replaced by the call that computes them.
 *
 * The interesting failure is not the one that looks broken. A model that writes
 * `nightsLabel="7 nights"` produces a label that is correct in the screenshot
 * and a lie the moment the traveler moves a date — and nothing downstream ever
 * notices, because a string is a string.
 *
 * A2UI already has the answer: a `formatString` whose template carries
 * `${calcNights(...)}` is resolved by every renderer against the live data
 * model, so the label recomputes as the picker moves, with no turn in between.
 * The skill asks for exactly that, and mostly gets it. This is the case where
 * it did not.
 *
 * The model keeps any label a function could not have written — a picker
 * captioned "including the wedding night" is its call. Only a bare count is
 * taken over.
 */
export function bindDerivedLabels(messages: A2uiMessage[]): A2uiMessage[] {
  const visit = (components: ComponentNode[] | undefined): void => {
    for (const node of components ?? []) {
      if (node.component !== 'DateRangePicker') continue;

      const start = node['start'];
      const end = node['end'];
      // Only when both ends are bound: a picker holding literal dates has
      // nothing to recompute against.
      if (!isPathBinding(start) || !isPathBinding(end)) continue;
      if (!isCountOfNights(node['nightsLabel'])) continue;

      node['nightsLabel'] = {
        call: 'formatString',
        args: {
          value:
            `\${calcNights(start:\${${pathOf(start)}}, end:\${${pathOf(end)}})} ` +
            'nights',
        } as JsonObject,
      };
    }
  };

  for (const message of messages) {
    if ('createSurface' in message) visit(message.createSurface.components);
    else if ('updateComponents' in message) visit(message.updateComponents.components);
  }

  return messages;
}

const isPathBinding = (value: Json | undefined): boolean =>
  Boolean(value) &&
  typeof value === 'object' &&
  !Array.isArray(value) &&
  typeof (value as JsonObject)['path'] === 'string';

const pathOf = (value: Json | undefined): string => String((value as JsonObject)['path']);

/**
 * True for a label that is only trying to say how many nights it is.
 *
 * Missing entirely, or a bare count the model worked out this turn. A template
 * is left alone — that is the right answer already, and rewriting it would
 * throw away wording the model chose.
 */
function isCountOfNights(value: Json | undefined): boolean {
  if (value === undefined || value === null) return true;
  if (typeof value !== 'string') return false;
  const text = value.trim();
  if (text === '') return true;
  if (text.includes('${')) return false;
  return /^\d+\s*nights?$/i.test(text);
}

/**
 * Keeps the panel's one interaction out of the conversation.
 *
 * The split this whole app is built on is that the conversation is where you
 * decide and the panel is where decisions live — so the panel is read-only
 * except for one thing, a `change` that re-opens a settled decision back in the
 * conversation. That direction is enforced: editors drawn on a panel are
 * ignored by the host.
 *
 * The other direction was only asked for, and a live run shows it being
 * ignored: under a card asking for dates, the model drew the panel's own record
 * again — "Your trip · Route · SFO → ORD → JFK · Change" — so the same decision
 * had two Change buttons on screen at once, in two places, one of them inside
 * the surface the traveler was still filling in.
 *
 * A `change` event is the panel's alone. Anywhere else it is a control that
 * either does nothing or competes with the one that works, so it is removed
 * here, along with any container left holding nothing.
 */
export function stripPanelActions(
  messages: A2uiMessage[],
  standingSurfaces: readonly string[],
): A2uiMessage[] {
  const standing = new Set(standingSurfaces);

  const prune = (surfaceId: string, components: ComponentNode[] | undefined): ComponentNode[] | undefined => {
    if (!components || standing.has(surfaceId)) return components;

    const dropped = new Set<string>();
    for (const node of components) {
      const event = eventOf(node);
      if (event && event['name'] === 'change') dropped.add(String(node.id));
    }
    if (dropped.size === 0) return components;

    // Repeated, because dropping a button can empty the row that held it, and
    // an empty row is a gap on screen that nothing explains.
    let kept = components.filter((node) => !dropped.has(String(node.id)));
    for (let pass = 0; pass < 5; pass += 1) {
      let changed = false;
      for (const node of kept) {
        if (!Array.isArray(node['children'])) continue;
        const children = (node['children'] as Json[]).filter(
          (child) => typeof child !== 'string' || !dropped.has(child),
        );
        if (children.length !== (node['children'] as Json[]).length) {
          node['children'] = children;
          changed = true;
        }
        // A container that only ever held the button, and is not the root.
        if (children.length === 0 && node.id !== 'root' && !dropped.has(String(node.id))) {
          dropped.add(String(node.id));
          changed = true;
        }
      }
      if (!changed) break;
      kept = kept.filter((node) => !dropped.has(String(node.id)));
    }
    return kept;
  };

  for (const message of messages) {
    if ('createSurface' in message) {
      const pruned = prune(message.createSurface.surfaceId, message.createSurface.components);
      if (pruned) message.createSurface.components = pruned;
    } else if ('updateComponents' in message) {
      message.updateComponents.components =
        prune(message.updateComponents.surfaceId, message.updateComponents.components) ?? [];
    }
  }

  return messages;
}
