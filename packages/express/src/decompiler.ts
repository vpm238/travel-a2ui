/**
 * Decompiles A2UI wire JSON back into Express.
 *
 * Three jobs, all of which pay for themselves:
 *
 *  1. **Prompt compression.** Few-shot examples authored as JSON get rewritten
 *     as Express before they reach the model, so the skill teaches the notation
 *     it asks for and costs a fraction of the tokens.
 *  2. **Round-tripping.** Compile → decompile → compile is a strong test that
 *     the compiler is not silently dropping information.
 *  3. **Legibility.** A surface on the wire is a flat adjacency list; the same
 *     surface in Express is readable in one screenful.
 *
 * A port of `inference_formats/experimental/express/decompiler.py`.
 */

import { CatalogHelper } from './catalog.js';
import { A2UI_CLOSE, A2UI_OPEN, SurfaceOperation, type CatalogSchema, type Json } from './types.js';

const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** Picks the least noisy string literal form that survives a round trip. */
export function decompileString(value: string): string {
  const hasNewline = value.includes('\n') || value.includes('\r');
  const hasTab = value.includes('\t');
  const hasQuote = value.includes('"');
  const hasBackslash = value.includes('\\');

  if ((hasQuote || hasNewline) && !value.endsWith('"') && !value.includes('"""')) {
    if (hasBackslash && !hasTab) return `r"""${value}"""`;
    const escaped = value.replace(/\\/g, '\\\\').replace(/\t/g, '\\t');
    return `"""${escaped}"""`;
  }

  if (hasBackslash && !hasNewline && !hasTab && !hasQuote) return `r"${value}"`;

  const escaped = value
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t');
  return `"${escaped}"`;
}

/** True when a property holds component ids rather than values. */
function isComponentReferenceProperty(schema: unknown): boolean {
  if (!schema || typeof schema !== 'object') return false;
  const node = schema as Record<string, unknown>;
  const ref = node['$ref'];
  if (typeof ref === 'string') {
    if (ref.includes('ComponentId') || ref.includes('Child') || ref.includes('ChildList')) {
      return true;
    }
  }
  for (const key of ['oneOf', 'anyOf', 'allOf'] as const) {
    const branch = node[key];
    if (Array.isArray(branch)) {
      for (const sub of branch) if (isComponentReferenceProperty(sub)) return true;
    }
  }
  if (node['type'] === 'array' && 'items' in node) {
    return isComponentReferenceProperty(node['items']);
  }
  return false;
}

/** Flattens `{a: {b: 1}}` into `[["/a/b", 1]]` — JSON Pointer leaves. */
function flattenDataModel(value: Json): Array<[string, Json]> {
  const out: Array<[string, Json]> = [];
  const walk = (current: Json, path: string): void => {
    if (current && typeof current === 'object' && !Array.isArray(current)) {
      const entries = Object.entries(current);
      if (entries.length > 0) {
        for (const [key, child] of entries) walk(child, `${path}/${key}`);
        return;
      }
    }
    out.push([path, current]);
  };
  walk(value, '');
  return out;
}

function capitalize(value: string): string {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

export interface DecompileOptions {
  /** Emit `prop=value` instead of positional arguments. Verbose but explicit. */
  useKeywordArgs?: boolean;
  /**
   * When decompiling a list, fold the messages that describe one surface back
   * into a single Express block. On by default, and you almost always want it:
   * in v0.9.1 a surface arrives as three messages (create, components, data),
   * and decompiling them separately emits `surface(...)` three times — which
   * recompiles into three surfaces, two of them empty. Set false only to see
   * the messages exactly as they are on the wire.
   */
  mergeSurfaces?: boolean;
}

/** Sets `value` at a JSON Pointer inside `target`, creating objects as needed. */
function setPointer(target: Record<string, Json>, pointer: string, value: Json): void {
  const segments = pointer.split('/').filter(Boolean);
  if (segments.length === 0) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.assign(target, value);
    }
    return;
  }
  let cursor = target;
  for (const segment of segments.slice(0, -1)) {
    const existing = cursor[segment];
    if (!existing || typeof existing !== 'object' || Array.isArray(existing)) cursor[segment] = {};
    cursor = cursor[segment] as Record<string, Json>;
  }
  cursor[segments[segments.length - 1]!] = value;
}

/**
 * Folds the v0.9.1 three-message form of a surface back into one envelope.
 *
 * `createSurface` + `updateComponents` + `updateDataModel` for the same
 * surfaceId become a single `createSurface` carrying components and dataModel —
 * the shape v1.0 sends natively, and the shape one Express block describes.
 * Messages for other operations pass through untouched, in order.
 */
function mergeSurfaceMessages(
  messages: Array<Record<string, Json>>,
): Array<Record<string, Json>> {
  const out: Array<Record<string, Json>> = [];
  const bySurface = new Map<string, Record<string, Json>>();

  const surfaceFor = (id: string, catalogId: string): Record<string, Json> => {
    let entry = bySurface.get(id);
    if (!entry) {
      const created: Record<string, Json> = { surfaceId: id, catalogId };
      entry = { [SurfaceOperation.CREATE]: created };
      bySurface.set(id, entry);
      out.push(entry);
    } else if (catalogId) {
      const created = entry[SurfaceOperation.CREATE] as Record<string, Json>;
      if (!created['catalogId']) created['catalogId'] = catalogId;
    }
    return entry[SurfaceOperation.CREATE] as Record<string, Json>;
  };

  for (const message of messages) {
    if (SurfaceOperation.CREATE in message) {
      const op = message[SurfaceOperation.CREATE] as Record<string, Json>;
      const created = surfaceFor(String(op['surfaceId'] ?? ''), String(op['catalogId'] ?? ''));
      if (Array.isArray(op['components'])) created['components'] = op['components'];
      const dataModel = op['dataModel'];
      if (dataModel && typeof dataModel === 'object') {
        const target = (created['dataModel'] ??= {}) as Record<string, Json>;
        setPointer(target, '', dataModel as Json);
      }
      continue;
    }

    if (SurfaceOperation.UPDATE_COMPONENTS in message) {
      const op = message[SurfaceOperation.UPDATE_COMPONENTS] as Record<string, Json>;
      const created = surfaceFor(String(op['surfaceId'] ?? ''), '');
      const existing = (created['components'] ?? []) as Json[];
      created['components'] = [...existing, ...((op['components'] ?? []) as Json[])];
      continue;
    }

    if (SurfaceOperation.UPDATE_DATA in message) {
      const op = message[SurfaceOperation.UPDATE_DATA] as Record<string, Json>;
      const id = String(op['surfaceId'] ?? '');
      // A data update for a surface we have not seen is standalone: it belongs
      // in its own block rather than inventing an empty surface for it.
      if (!bySurface.has(id)) {
        out.push(message);
        continue;
      }
      const created = surfaceFor(id, '');
      const target = (created['dataModel'] ??= {}) as Record<string, Json>;
      setPointer(target, String(op['path'] ?? '/'), (op['value'] ?? null) as Json);
      continue;
    }

    out.push(message);
  }

  return out;
}

export class ExpressDecompiler {
  readonly helper: CatalogHelper;

  constructor(catalog: CatalogSchema | CatalogHelper) {
    this.helper = catalog instanceof CatalogHelper ? catalog : new CatalogHelper(catalog);
  }

  /** Wraps decompiled blocks in the sentinel tags a model is taught to emit. */
  wrapBlocks(blocks: string[]): string {
    return `${A2UI_OPEN}\n${blocks.join('\n')}\n${A2UI_CLOSE}`;
  }

  decompile(
    envelope: Record<string, Json> | Array<Record<string, Json>>,
    options: DecompileOptions = {},
  ): string {
    if (Array.isArray(envelope)) {
      const messages = envelope.filter(Boolean);
      const merged = options.mergeSurfaces === false ? messages : mergeSurfaceMessages(messages);
      return merged
        .map((item) => this.decompile(item, options))
        .filter((block) => block.length > 0)
        .join('\n');
    }

    if (SurfaceOperation.DELETE in envelope) {
      const op = envelope[SurfaceOperation.DELETE] as Record<string, Json>;
      return `deleteSurface("${String(op?.['surfaceId'] ?? '')}")`;
    }

    if (SurfaceOperation.UPDATE_DATA in envelope) {
      const op = envelope[SurfaceOperation.UPDATE_DATA] as Record<string, Json>;
      const value = (op?.['value'] ?? {}) as Json;
      const lines: string[] = [];
      if (value && typeof value === 'object' && Object.keys(value).length > 0) {
        for (const [path, leaf] of flattenDataModel(value).sort((a, b) =>
          a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0,
        )) {
          lines.push(`$${path} = ${this.decompileValue(leaf, new Set(), false)}`);
        }
      }
      return lines.join('\n');
    }

    if (SurfaceOperation.CALL_FUNC in envelope) {
      const op = (envelope[SurfaceOperation.CALL_FUNC] ?? {}) as Record<string, Json>;
      const name = String(op['call'] ?? '');
      const args = op['args'];
      const reprs: string[] = [];
      if (this.helper.hasFunction(name)) {
        const parameters = this.helper.getFunctionProperties(name);
        if (args && typeof args === 'object' && !Array.isArray(args)) {
          for (const parameter of parameters) {
            reprs.push(
              parameter in args
                ? this.decompileValue((args as Record<string, Json>)[parameter]!, new Set(), false)
                : '_',
            );
          }
        } else if (Array.isArray(args)) {
          parameters.forEach((_parameter, index) => {
            reprs.push(index < args.length ? this.decompileValue(args[index]!, new Set(), false) : '_');
          });
        }
      } else if (Array.isArray(args)) {
        for (const arg of args) reprs.push(this.decompileValue(arg, new Set(), false));
      } else if (args && typeof args === 'object') {
        for (const arg of Object.values(args)) reprs.push(this.decompileValue(arg, new Set(), false));
      }
      while (reprs.length > 0 && reprs[reprs.length - 1] === '_') reprs.pop();
      return `${name}(${reprs.join(', ')})`;
    }

    let surface = (envelope[SurfaceOperation.CREATE] ?? {}) as Record<string, Json>;
    if (
      (!surface || Object.keys(surface).length === 0) &&
      SurfaceOperation.UPDATE_COMPONENTS in envelope
    ) {
      surface = envelope[SurfaceOperation.UPDATE_COMPONENTS] as Record<string, Json>;
    }

    const surfaceId = String(surface['surfaceId'] ?? '');
    const catalogId = String(surface['catalogId'] ?? '');
    const components = (surface['components'] ?? []) as Array<Record<string, Json>>;
    const dataModel = (surface['dataModel'] ?? {}) as Json;
    const defaultCatalogId = this.helper.catalog.catalogId || 'https://a2ui.org/catalog.json';

    const lines: string[] = [];
    if (surfaceId && surfaceId !== 'default_surface') {
      if (catalogId && catalogId !== defaultCatalogId) {
        lines.push(`surface("${surfaceId}", catalogId="${catalogId}")`);
      } else {
        lines.push(`surface("${surfaceId}")`);
      }
    }

    const componentIds = new Set(components.map((c) => String(c['id'])));

    if (dataModel && typeof dataModel === 'object' && Object.keys(dataModel).length > 0) {
      for (const [path, leaf] of flattenDataModel(dataModel).sort((a, b) =>
        a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0,
      )) {
        lines.push(`$${path} = ${this.decompileValue(leaf, componentIds, false)}`);
      }
    }

    for (const component of components) {
      const id = String(component['id']);
      const name = String(component['component']);
      if (!this.helper.hasComponent(name)) continue;

      const properties = this.helper.getComponentProperties(name);
      const reprs: string[] = [];

      properties.forEach((property, index) => {
        if (property === 'checks') {
          const checks = component['checks'];
          if (!Array.isArray(checks) || checks.length === 0) {
            reprs.push('_');
            return;
          }
          const rendered = checks.map((raw) => this.decompileCheck(raw as Json, componentIds));
          reprs.push(rendered.length === 1 ? rendered[0]! : `[${rendered.join(', ')}]`);
          return;
        }

        if (property in component) {
          const schema = this.helper.getPropertySchema(name, property);
          const rendered = this.decompileValue(
            component[property]!,
            componentIds,
            isComponentReferenceProperty(schema),
          );
          reprs.push(options.useKeywordArgs ? `${property}=${rendered}` : rendered);
          return;
        }

        if (!options.useKeywordArgs) {
          // A gap only needs a placeholder when a later property is filled in.
          const hasLaterValue = properties
            .slice(index + 1)
            .some((later) => later !== 'checks' && later in component);
          if (hasLaterValue) reprs.push('_');
        }
      });

      while (reprs.length > 0 && reprs[reprs.length - 1] === '_') reprs.pop();
      lines.push(`${id} = ${name}(${reprs.join(', ')})`);
    }

    return lines.join('\n');
  }

  private decompileCheck(raw: Json, componentIds: Set<string>): string {
    const rule = (raw ?? {}) as Record<string, Json>;
    const condition = (rule['condition'] ?? {}) as Record<string, Json>;
    const message = typeof rule['message'] === 'string' ? rule['message'] : '';
    const name = String(condition['call'] ?? '');
    const args = (condition['args'] ?? {}) as Record<string, Json>;

    const parameters = this.helper.getFunctionProperties(name);
    const reprs: string[] = [];
    // The first parameter is the implicit subject when it is called `value`.
    const start = parameters[0] === 'value' ? 1 : 0;
    for (let index = start; index < parameters.length; index++) {
      const parameter = parameters[index]!;
      if (parameter in args) reprs.push(this.decompileValue(args[parameter]!, componentIds, false));
    }
    if (name && message && message !== `${capitalize(name)} check failed`) {
      reprs.push(decompileString(message));
    }
    return reprs.length > 0 ? `?${name}(${reprs.join(', ')})` : `?${name}`;
  }

  private decompileValue(value: Json, componentIds: Set<string>, isRef: boolean): string {
    if (Array.isArray(value)) {
      return `[${value.map((item) => this.decompileValue(item, componentIds, isRef)).join(', ')}]`;
    }

    if (value !== null && typeof value === 'object') {
      const node = value as Record<string, Json>;

      if ('path' in node) {
        if ('componentId' in node) {
          const path = this.decompileValue({ path: node['path']! }, componentIds, false);
          return `_template(${path}, ${String(node['componentId'])})`;
        }
        const path = String(node['path']);
        return path.startsWith('/') ? `$/${path.slice(1)}` : `$${path}`;
      }

      if ('event' in node) {
        const event = (node['event'] ?? {}) as Record<string, Json>;
        const name = String(event['name'] ?? '');
        const context = (event['context'] ?? {}) as Record<string, Json>;
        const entries = Object.entries(context).map(
          ([key, item]) => `${key}: ${this.decompileValue(item, componentIds, false)}`,
        );
        return entries.length > 0 ? `Event("${name}", {${entries.join(', ')}})` : `Event("${name}")`;
      }

      if ('functionCall' in node) {
        const fn = (node['functionCall'] ?? {}) as Record<string, Json>;
        const name = String(fn['call']);
        const args = (fn['args'] ?? {}) as Record<string, Json>;
        const reprs = this.helper
          .getFunctionProperties(name)
          .map((parameter) =>
            parameter in args ? this.decompileValue(args[parameter]!, componentIds, false) : '_',
          );
        while (reprs.length > 0 && reprs[reprs.length - 1] === '_') reprs.pop();
        return `${name}(${reprs.join(', ')})`;
      }

      if ('call' in node) {
        const name = String(node['call']);
        const args = node['args'];
        let reprs: string[] = [];
        if (this.helper.hasFunction(name)) {
          reprs = this.helper
            .getFunctionProperties(name)
            .map((parameter) =>
              args && typeof args === 'object' && !Array.isArray(args) && parameter in args
                ? this.decompileValue((args as Record<string, Json>)[parameter]!, componentIds, false)
                : '_',
            );
        } else if (Array.isArray(args)) {
          reprs = args.map((arg) => this.decompileValue(arg, componentIds, false));
        } else if (args && typeof args === 'object') {
          reprs = Object.values(args).map((arg) => this.decompileValue(arg, componentIds, false));
        }
        while (reprs.length > 0 && reprs[reprs.length - 1] === '_') reprs.pop();
        return `${name}(${reprs.join(', ')})`;
      }

      const entries = Object.entries(node).map(([key, item]) => {
        const keyRepr = IDENTIFIER_RE.test(key) ? key : decompileString(key);
        const childIsRef = isRef || key === 'child' || key === 'componentId';
        return `${keyRepr}: ${this.decompileValue(item, componentIds, childIsRef)}`;
      });
      return `{${entries.join(', ')}}`;
    }

    if (typeof value === 'string') {
      if (isRef && componentIds.has(value)) return value;
      return decompileString(value);
    }

    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (value === null) return 'null';
    return String(value);
  }
}
