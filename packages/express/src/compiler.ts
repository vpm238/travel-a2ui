/**
 * Compiles A2UI Express into A2UI wire messages.
 *
 * A port of the reference compiler in google/a2ui
 * (`inference_formats/experimental/express/compiler.py`). The parity suite in
 * `test/parity.test.ts` compiles the same sources with both implementations and
 * asserts the JSON matches, so behaviour here is pinned to that file rather
 * than to anyone's reading of the spec.
 *
 * The shape of the job: Express is a *nested* notation and A2UI is a *flat*
 * adjacency list. Compiling means giving every nested constructor an id,
 * hoisting it to the top level, and replacing it in its parent with that id.
 */

import {
  isCall,
  isCheck,
  isCheckExpression,
  isPath,
  isSkipped,
  isVariable,
  type AstCall,
  type AstStatement,
  type AstValue,
} from './ast.js';
import { CatalogHelper, compilerAllowsDatabinding, schemaExpectsOptionObjects } from './catalog.js';
import {
  ExpressDuplicateParamError,
  ExpressDuplicatePropertyError,
  ExpressForbiddenDatabindingError,
  ExpressInvalidEnumError,
  ExpressInvalidParamError,
  ExpressUndefinedRootError,
  ExpressUnknownComponentError,
  ExpressUnknownPropertyError,
} from './errors.js';
import { parse } from './parser.js';
import {
  A2UI_CLOSE,
  A2UI_OPEN,
  SurfaceOperation,
  type A2uiMessage,
  type CatalogSchema,
  type ComponentNode,
  type Json,
  type JsonObject,
  type ProtocolVersion,
} from './types.js';

export interface CompileOptions {
  surfaceId?: string;
  catalogId?: string;
  version?: ProtocolVersion;
  /**
   * False while the model is still streaming: syntax errors in the unfinished
   * tail are swallowed and the partial tree compiles anyway.
   */
  isFinal?: boolean;
}

/** Strips prose around `<a2ui>…</a2ui>`, keeping only Express source. */
export function extractExpressBlock(text: string): string {
  const hasSentinels = text.includes(A2UI_OPEN);
  const lines: string[] = [];
  let inside = !hasSentinels;

  for (let line of text.split('\n')) {
    let trimmed = line.trim();
    if (trimmed.includes(A2UI_OPEN)) {
      inside = true;
      line = line.replace(A2UI_OPEN, '');
      trimmed = line.trim();
    }
    if (trimmed.includes(A2UI_CLOSE)) {
      inside = false;
      line = line.split(A2UI_CLOSE)[0]!;
      if (line.trim()) lines.push(line);
      continue;
    }
    if (inside) lines.push(line);
  }
  return lines.join('\n');
}

/**
 * Calls the grammar defines rather than the catalog.
 *
 * They are legal in a declaration and produce no component, so they are the one
 * thing an unknown-component check must not flag.
 */
const BUILTIN_CALLS = new Set(['Event', '_template', SurfaceOperation.SURFACE, SurfaceOperation.DELETE]);

interface CompileContext {
  extraComponents: ComponentNode[];
  inlineCounter: number;
  activeValuePath: Json | null;
}

class SurfaceScope {
  readonly rawSymbols = new Map<string, AstValue>();
  readonly dataPathAssignments = new Map<string, AstValue>();
  constructor(
    readonly surfaceId: string,
    readonly catalogId: string,
  ) {}
}

function setNestedPath(target: JsonObject, pathString: string, value: Json): void {
  let clean = pathString;
  if (clean.startsWith('$/')) clean = clean.slice(2);
  else if (clean.startsWith('$')) clean = clean.slice(1);
  if (!clean) return;

  const keys = clean.split('/');
  let cursor: JsonObject = target;
  for (const key of keys.slice(0, -1)) {
    const existing = cursor[key];
    if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
      cursor[key] = {};
    }
    cursor = cursor[key] as JsonObject;
  }
  cursor[keys[keys.length - 1]!] = value;
}

/** True if a compiled value contains a `{ path }` binding anywhere inside it. */
function hasDatabinding(value: Json): boolean {
  if (Array.isArray(value)) return value.some(hasDatabinding);
  if (value && typeof value === 'object') {
    const node = value as JsonObject;
    // A call, an event or a function call is a *description* of behaviour; the
    // bindings inside it are arguments, not a dynamic value for this property.
    if ('call' in node || 'event' in node || 'functionCall' in node) return false;
    if ('path' in node && !('componentId' in node)) return true;
    return Object.values(node).some(hasDatabinding);
  }
  return false;
}

export class ExpressCompiler {
  readonly helper: CatalogHelper;

  constructor(
    catalog: CatalogSchema | CatalogHelper,
    private readonly defaultVersion: ProtocolVersion = 'v0.9.1',
  ) {
    this.helper = catalog instanceof CatalogHelper ? catalog : new CatalogHelper(catalog);
  }

  compile(source: string, options: CompileOptions = {}): A2uiMessage[] {
    const version = options.version ?? this.defaultVersion;
    const surfaceId = options.surfaceId ?? 'default_surface';
    const catalogId = options.catalogId ?? '';
    const isFinal = options.isFinal ?? true;

    const body = extractExpressBlock(source);
    const { statements, errors } = parse(body, { isFinal });
    if (isFinal && errors.length > 0) throw errors[0];

    return this.compileStatements(statements, { surfaceId, catalogId, version });
  }

  private compileStatements(
    statements: AstStatement[],
    options: { surfaceId: string; catalogId: string; version: ProtocolVersion },
  ): A2uiMessage[] {
    const { surfaceId, catalogId, version } = options;
    const ctx: CompileContext = { extraComponents: [], inlineCounter: 0, activeValuePath: null };

    const scopes: SurfaceScope[] = [];
    let currentScope: SurfaceScope | null = null;
    let deleteSurfaceId: string | null = null;
    const standaloneCalls: Array<{ call: AstCall; scope: SurfaceScope | null }> = [];

    for (const statement of statements) {
      if (statement.kind === 'EXPR') {
        const value = statement.value;
        if (!isCall(value)) continue;

        if (value.call === SurfaceOperation.SURFACE) {
          const kwargs = value.kwargs ?? {};
          const targetSurface =
            typeof kwargs['surfaceId'] === 'string'
              ? kwargs['surfaceId']
              : typeof value.args[0] === 'string'
                ? value.args[0]
                : surfaceId;
          const targetCatalog =
            typeof kwargs['catalogId'] === 'string'
              ? kwargs['catalogId']
              : typeof value.args[1] === 'string'
                ? value.args[1]
                : catalogId;
          currentScope = new SurfaceScope(targetSurface, targetCatalog);
          scopes.push(currentScope);
        } else if (value.call === SurfaceOperation.DELETE) {
          const kwargs = value.kwargs ?? {};
          if (typeof value.args[0] === 'string') deleteSurfaceId = value.args[0];
          else if (typeof kwargs['surfaceId'] === 'string') deleteSurfaceId = kwargs['surfaceId'];
        } else {
          standaloneCalls.push({ call: value, scope: currentScope });
        }
        continue;
      }

      if (!currentScope) {
        currentScope = new SurfaceScope(surfaceId, catalogId);
        scopes.push(currentScope);
      }
      if (statement.target.startsWith('$')) {
        currentScope.dataPathAssignments.set(statement.target, statement.value);
      } else {
        currentScope.rawSymbols.set(statement.target, statement.value);
      }
    }

    if (deleteSurfaceId !== null) {
      return [{ version, [SurfaceOperation.DELETE]: { surfaceId: deleteSurfaceId } } as A2uiMessage];
    }

    if (standaloneCalls.length > 0) {
      if (version === 'v0.9' || version === 'v0.9.1') {
        throw new Error(`Standalone function calls are not supported in A2UI ${version}`);
      }
      const first = standaloneCalls[0]!;
      ctx.inlineCounter += 1;
      const symbols = first.scope?.rawSymbols ?? new Map<string, AstValue>();
      const compiled = this.compileValue(first.call, symbols, ctx, false) as JsonObject;
      return [
        {
          version,
          functionCallId: `call_${ctx.inlineCounter}`,
          [SurfaceOperation.CALL_FUNC]: {
            call: compiled['call'] ?? null,
            args: compiled['args'] ?? {},
          },
        } as A2uiMessage,
      ];
    }

    if (scopes.length === 0) throw new ExpressUndefinedRootError();

    const messages: A2uiMessage[] = [];

    for (const scope of scopes) {
      const scopeCatalogId =
        scope.catalogId || catalogId || this.helper.catalog.catalogId || 'https://a2ui.org/catalog.json';

      const dataModel: JsonObject = {};
      for (const [pathName, node] of scope.dataPathAssignments) {
        setNestedPath(dataModel, pathName, this.compileValue(node, scope.rawSymbols, ctx, false));
      }
      const hasDataModel = Object.keys(dataModel).length > 0;

      if (!scope.rawSymbols.has('root')) {
        if (scope.dataPathAssignments.size > 0) {
          messages.push({
            version,
            [SurfaceOperation.UPDATE_DATA]: {
              surfaceId: scope.surfaceId,
              path: '/',
              value: dataModel,
            },
          } as A2uiMessage);
          continue;
        }
        throw new ExpressUndefinedRootError();
      }

      const components: ComponentNode[] = [];
      for (const [name, node] of scope.rawSymbols) {
        const compiled = this.compileComponent(name, node, scope.rawSymbols, ctx);
        if (compiled) {
          components.push(compiled);
          continue;
        }

        // A declaration that is a call to something the catalog has never heard
        // of produces no component, and without this it would vanish silently —
        // the model gets a blank surface and no reason for it. A model composing
        // a layout is exactly who invents a component name, so this has to say
        // so out loud and list what it could have used instead.
        if (isCall(node) && !this.helper.hasFunction(node.call) && !BUILTIN_CALLS.has(node.call)) {
          throw new ExpressUnknownComponentError(node.call, this.helper.componentNames());
        }
      }
      components.push(...ctx.extraComponents);
      ctx.extraComponents = [];

      if (version === 'v0.9' || version === 'v0.9.1') {
        messages.push(
          {
            version,
            [SurfaceOperation.CREATE]: { surfaceId: scope.surfaceId, catalogId: scopeCatalogId },
          } as A2uiMessage,
          {
            version,
            [SurfaceOperation.UPDATE_COMPONENTS]: { surfaceId: scope.surfaceId, components },
          } as A2uiMessage,
        );
        if (hasDataModel) {
          messages.push({
            version,
            [SurfaceOperation.UPDATE_DATA]: {
              surfaceId: scope.surfaceId,
              path: '/',
              value: dataModel,
            },
          } as A2uiMessage);
        }
      } else {
        const createSurface: JsonObject = {
          surfaceId: scope.surfaceId,
          catalogId: scopeCatalogId,
          components: components as unknown as Json,
        };
        if (hasDataModel) createSurface['dataModel'] = dataModel;
        messages.push({ version, [SurfaceOperation.CREATE]: createSurface } as A2uiMessage);
      }
    }

    return messages;
  }

  /** Turns one `name = Component(...)` binding into a flat component node. */
  private compileComponent(
    id: string,
    node: AstValue,
    symbols: Map<string, AstValue>,
    ctx: CompileContext,
  ): ComponentNode | null {
    if (!isCall(node)) return null;
    const componentName = node.call;
    if (!this.helper.hasComponent(componentName)) return null;

    const properties = this.helper.getComponentProperties(componentName);
    const positional = properties.filter((p) => p !== 'checks');
    const result: Record<string, Json> = { id, component: componentName };

    // `?rule` arguments are collected out-of-band: they never consume a
    // positional slot, wherever the model wrote them.
    const rawChecks: AstValue[] = [];
    const pairs: Array<[string, AstValue]> = [];
    let index = 0;

    for (const arg of node.args) {
      if (isCheckExpression(arg)) {
        if (Array.isArray(arg)) rawChecks.push(...arg);
        else rawChecks.push(arg);
        continue;
      }
      if (index < positional.length) {
        pairs.push([positional[index]!, arg]);
        index += 1;
      }
    }
    for (const [key, value] of Object.entries(node.kwargs ?? {})) {
      if (isCheckExpression(value)) {
        if (Array.isArray(value)) rawChecks.push(...value);
        else rawChecks.push(value);
        continue;
      }
      pairs.push([key, value]);
    }

    let siblingValuePath: Json | null = null;
    const seen = new Set<string>();

    for (const [property, arg] of pairs) {
      if (!properties.includes(property)) {
        throw new ExpressUnknownPropertyError(componentName, property, properties);
      }
      if (seen.has(property)) throw new ExpressDuplicatePropertyError(componentName, property);
      seen.add(property);

      if (isSkipped(arg)) {
        result[property] = null;
        continue;
      }

      let value = this.compileValue(
        arg,
        symbols,
        ctx,
        property === 'action' || property === 'submitAction',
      );

      const propertySchema = this.helper.getPropertySchema(componentName, property);
      if (propertySchema && !compilerAllowsDatabinding(propertySchema)) {
        if (hasDatabinding(value)) {
          throw new ExpressForbiddenDatabindingError(componentName, property);
        }
        if (Array.isArray(value) && schemaExpectsOptionObjects(propertySchema)) {
          value = value.map((option) =>
            typeof option === 'string' ? { label: option, value: option } : option,
          );
        }
      }

      const allowed = this.helper.getPropertyEnum(componentName, property);
      if (allowed && typeof value === 'string' && !allowed.includes(value)) {
        throw new ExpressInvalidEnumError(componentName, property, value, allowed);
      }

      result[property] = value;

      if (property === 'value' && value && typeof value === 'object' && 'path' in value) {
        siblingValuePath = value;
      }
    }

    // Checks compile second so they can borrow the component's own bound value
    // as their implicit target: `?required` on a field means "this field".
    ctx.activeValuePath = siblingValuePath;
    if (rawChecks.length > 0) {
      const checks: Json[] = [];
      for (const raw of rawChecks) {
        if (!isCheck(raw)) continue;
        const { args, message } = this.compileCheckArgs(
          raw.check,
          raw.args,
          symbols,
          ctx,
          siblingValuePath,
          { skippedBecomesNull: true, isAction: false },
        );
        checks.push({ condition: { call: raw.check, args }, message });
      }
      if (checks.length > 0) result['checks'] = checks;
    }
    ctx.activeValuePath = null;

    const cleaned: Record<string, Json> = {};
    for (const [key, value] of Object.entries(result)) {
      if (value !== null && value !== undefined) cleaned[key] = value;
    }
    return cleaned as ComponentNode;
  }

  /**
   * Maps a check's positional arguments onto its parameter names.
   *
   * Two conventions make checks terse enough to be worth writing:
   *   - the first parameter, when it is named `value`, is filled in from the
     *   host component's bound path instead of being written out; and
   *   - a trailing string where a number/boolean parameter was expected is the
   *     human-readable failure message, not a coerced argument.
   */
  private compileCheckArgs(
    name: string,
    rawArgs: AstValue[],
    symbols: Map<string, AstValue>,
    ctx: CompileContext,
    implicitValuePath: Json | null,
    mode: { skippedBecomesNull: boolean; isAction: boolean },
  ): { args: JsonObject; message: string } {
    const parameters = this.helper.getFunctionProperties(name);
    const args: JsonObject = {};
    let message = `${name.charAt(0).toUpperCase()}${name.slice(1)} check failed`;

    let injected = false;
    if (parameters[0] === 'value') {
      const firstIsPath = rawArgs.length > 0 && isPath(rawArgs[0]);
      if (!firstIsPath && implicitValuePath) {
        args['value'] = implicitValuePath;
        injected = true;
      }
    }

    const offset = injected ? 1 : 0;
    for (let i = 0; i < rawArgs.length; i++) {
      const target = i + offset;
      const arg = rawArgs[i]!;
      if (target < parameters.length) {
        const parameter = parameters[target]!;
        const schema = this.helper.getFunctionPropertySchema(name, parameter);
        const expected = schema?.['type'];
        const looksLikeMessage =
          typeof arg === 'string' &&
          (expected === 'integer' || expected === 'number' || expected === 'boolean');
        if (looksLikeMessage) {
          message = arg;
          break;
        }
        if (isSkipped(arg)) {
          if (mode.skippedBecomesNull) args[parameter] = null;
          continue;
        }
        args[parameter] = this.compileValue(arg, symbols, ctx, mode.isAction);
      } else if (typeof arg === 'string') {
        message = arg;
      }
    }

    return { args, message };
  }

  /** Compiles any value position: literals, bindings, references, calls. */
  private compileValue(
    value: AstValue,
    symbols: Map<string, AstValue>,
    ctx: CompileContext,
    isAction: boolean,
  ): Json {
    if (Array.isArray(value)) {
      return value.map((item) => this.compileValue(item, symbols, ctx, isAction));
    }

    if (value === null || typeof value !== 'object') return value as Json;

    if (isPath(value)) return { ...value } as Json;

    if (isVariable(value)) {
      const referenced = symbols.get(value.variable);
      if (referenced !== undefined) {
        // A reference to a component variable becomes that component's id;
        // a reference to a plain value is inlined.
        if (isCall(referenced) && this.helper.hasComponent(referenced.call)) {
          return value.variable;
        }
        return this.compileValue(referenced, symbols, ctx, isAction);
      }
      return value.variable;
    }

    if (isCheck(value)) {
      const { args } = this.compileCheckArgs(
        value.check,
        value.args,
        symbols,
        ctx,
        ctx.activeValuePath,
        { skippedBecomesNull: false, isAction },
      );
      return { call: value.check, args };
    }

    if (isCall(value)) return this.compileCall(value, symbols, ctx, isAction);

    if (isSkipped(value)) return null;

    const out: JsonObject = {};
    for (const [key, item] of Object.entries(value as Record<string, AstValue>)) {
      out[key] = this.compileValue(item, symbols, ctx, isAction);
    }
    return out;
  }

  private compileCall(
    node: AstCall,
    symbols: Map<string, AstValue>,
    ctx: CompileContext,
    isAction: boolean,
  ): Json {
    const name = node.call;
    const args = node.args;

    // An inline constructor: hoist it to the top level and leave its id behind.
    if (this.helper.hasComponent(name)) {
      ctx.inlineCounter += 1;
      const inlineId = `_inline_${ctx.inlineCounter}`;
      const compiled = this.compileComponent(inlineId, node, symbols, ctx);
      if (compiled) ctx.extraComponents.push(compiled);
      return inlineId;
    }

    if (name === '_template') {
      if (args.length < 2) {
        throw new Error(
          '_template requires 2 arguments: the list path and the template component.',
        );
      }
      const pathValue = this.compileValue(args[0]!, symbols, ctx, isAction);
      if (!pathValue || typeof pathValue !== 'object' || !('path' in pathValue)) {
        throw new Error(
          "_template's first argument must be a '$' data binding path, e.g. _template($/items, row).",
        );
      }
      const componentId = this.compileValue(args[1]!, symbols, ctx, isAction);
      return { path: (pathValue as { path: string }).path, componentId };
    }

    if (name === 'Event') {
      const eventName = args.length > 0 ? this.compileValue(args[0]!, symbols, ctx, isAction) : '';
      const rawContext = args.length > 1 ? this.compileValue(args[1]!, symbols, ctx, isAction) : {};
      const context: JsonObject = {};
      if (Array.isArray(rawContext)) {
        for (const item of rawContext) {
          if (item && typeof item === 'object' && !Array.isArray(item)) Object.assign(context, item);
        }
      } else if (rawContext && typeof rawContext === 'object') {
        Object.assign(context, rawContext);
      }
      return { event: { name: eventName, context } };
    }

    if (this.helper.hasFunction(name)) {
      const parameters = this.helper.getFunctionProperties(name);
      const compiledArgs: JsonObject = {};
      for (let i = 0; i < args.length; i++) {
        if (i >= parameters.length) break;
        const arg = args[i]!;
        if (isSkipped(arg)) continue;
        const compiled = this.compileValue(arg, symbols, ctx, isAction);
        if (compiled !== null) compiledArgs[parameters[i]!] = compiled;
      }
      for (const [key, raw] of Object.entries(node.kwargs ?? {})) {
        if (!parameters.includes(key)) throw new ExpressInvalidParamError(name, key, parameters);
        if (key in compiledArgs) throw new ExpressDuplicateParamError(name, key);
        if (isSkipped(raw)) continue;
        const compiled = this.compileValue(raw, symbols, ctx, isAction);
        if (compiled !== null) compiledArgs[key] = compiled;
      }
      // Inside an action slot a function call is a *handler*; elsewhere it is a
      // dynamic value expression. Same call, two envelopes.
      if (isAction) return { functionCall: { call: name, args: compiledArgs } };
      return { call: name, args: compiledArgs };
    }

    return {
      call: name,
      args: args.map((arg) => this.compileValue(arg, symbols, ctx, isAction)),
    };
  }
}
