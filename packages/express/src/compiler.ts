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
  ExpressUnknownCatalogError,
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
  isV1,
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

/** An inline constructor waiting to be compiled, under the id it was given. */
interface PendingComponent {
  id: string;
  node: AstValue;
  symbols: Map<string, AstValue>;
}

interface CompileContext {
  /**
   * Inline constructors hoisted out of the component being compiled, in the
   * order they were met.
   *
   * A queue and not a recursion. `Card(Column([Text(…), Button(…)]))` is four
   * components deep, and the reference compiler emits them a level at a time —
   * `root`, `root_child`, then that column's two children — because each one is
   * only queued while its owner is being written, and drained afterwards.
   * Compiling them inline instead reverses that: the deepest finishes first and
   * is pushed first, so a renderer reading the list in order met every child
   * before the parent that names it.
   */
  pending: PendingComponent[];
  activeValuePath: Json | null;
  /**
   * The component currently being written, and which of its properties.
   *
   * Only here so a hoisted inline can be *named*: the reference calls it after
   * where it was found — `root_child`, `save_child`,
   * `root_child_children_1_child` — rather than by a running counter. The name
   * is part of the wire, since it is what the owner's property points at, so a
   * client's golden files disagree with the server's over nothing else.
   */
  owner: string | null;
  ownerProperty: string | null;
  /** Which protocol is being written, because 1.0 spells bindings `@path`. */
  version: ProtocolVersion;
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
  for (let at = 0; at < keys.length - 1; at++) {
    const key = keys[at]!;
    // A numeric segment means the *next* level down is a list, because that is
    // what `$/flights/0/airline` says: index 0 of flights. Built as an object
    // it came out `{"flights": {"0": {…}}}`, which a `_template` over
    // `/flights` then iterated zero times — the rows silently never drew.
    const wantsList = isIndex(keys[at + 1]!);
    const existing = cursor[key];
    if (!existing || typeof existing !== 'object' || Array.isArray(existing) !== wantsList) {
      cursor[key] = (wantsList ? [] : {}) as Json;
    }
    cursor = cursor[key] as JsonObject;
  }
  cursor[keys[keys.length - 1]!] = value;
}

/** Whether a path segment is a list index rather than a property name. */
function isIndex(segment: string): boolean {
  return /^(0|[1-9][0-9]*)$/.test(segment);
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
    const ctx: CompileContext = {
      pending: [],
      activeValuePath: null,
      owner: null,
      ownerProperty: null,
      version,
    };

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
      const symbols = first.scope?.rawSymbols ?? new Map<string, AstValue>();
      const compiled = this.compileValue(first.call, symbols, ctx, false) as JsonObject;
      // Read back under whichever key was just written, rather than under
      // `call`: at 1.0 `compileValue` produces `@call`, so the old read found
      // nothing and sent `"call": null` — a message naming no function.
      const called = compiled['@call'] ?? compiled['call'] ?? null;
      return [
        {
          version,
          functionCallId: 'call_1',
          [SurfaceOperation.CALL_FUNC]: {
            ...(this.callFor(called as string, compiled['args'] ?? {}, ctx) as JsonObject),
          },
        } as A2uiMessage,
      ];
    }

    if (scopes.length === 0) throw new ExpressUndefinedRootError();

    const messages: A2uiMessage[] = [];

    for (const scope of scopes) {
      const scopeCatalogId =
        scope.catalogId || catalogId || this.helper.catalog.catalogId || 'https://a2ui.org/catalog.json';

      // A catalog named on the `surface()` line has to be one we hold. The
      // reference refuses an unknown one; this accepted anything and passed it
      // straight through to `createSurface`, so the only parity gap the
      // goldens cannot show — what the two compilers *refuse* — was also the
      // one that failed silently in a client.
      const known = this.helper.catalog.catalogId;
      if (scope.catalogId && known && scope.catalogId !== known) {
        throw new ExpressUnknownCatalogError(scope.catalogId, [known]);
      }

      const dataModel: JsonObject = {};
      for (const [pathName, node] of scope.dataPathAssignments) {
        setNestedPath(dataModel, pathName, this.compileValue(node, scope.rawSymbols, ctx, false));
      }
      const hasDataModel = Object.keys(dataModel).length > 0;

      if (!scope.rawSymbols.has('root')) {
        if (scope.dataPathAssignments.size > 0) {
          // One message per assignment, each at the path it was written to —
          // not a single write of the whole tree to `/`.
          //
          // A block with no `root` is how the agent *amends* a surface that is
          // already drawn, so the difference is the whole point: `/` replaces
          // the data model, and the one in front of the traveller holds the
          // rows, the selections and the trip. Writing `$/prefs/theme` would
          // have deleted all of it.
          for (const [pathName, node] of scope.dataPathAssignments) {
            messages.push({
              version,
              [SurfaceOperation.UPDATE_DATA]: {
                surfaceId: scope.surfaceId,
                path: pathName.replace(/^\$/, '') || '/',
                value: this.compileValue(node, scope.rawSymbols, ctx, false),
              },
            } as A2uiMessage);
          }
          continue;
        }
        throw new ExpressUndefinedRootError();
      }

      const components: ComponentNode[] = [];
      for (const [name, node] of scope.rawSymbols) {
        const compiled = this.compileComponent(name, node, scope.rawSymbols, ctx);
        if (compiled) {
          components.push(compiled);
          // Whatever that component hoisted follows it immediately, and
          // whatever *those* hoist follows them — a level at a time, which is
          // the order the reference emits and the only order in which every
          // component is declared before the id pointing at it is read.
          while (ctx.pending.length > 0) {
            const next = ctx.pending.shift()!;
            const inline = this.compileComponent(next.id, next.node, next.symbols, ctx);
            if (inline) components.push(inline);
          }
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

      // Named so an inline constructor inside this property can be called
      // after it. Saved and restored rather than simply set, because a
      // component compiled from the queue is compiled *inside* nothing — the
      // owner it would otherwise inherit is whoever happened to run last.
      const ownerWas = ctx.owner;
      const propertyWas = ctx.ownerProperty;
      ctx.owner = id;
      ctx.ownerProperty = property;
      let value: Json;
      try {
        value = this.compileValue(
          arg,
          symbols,
          ctx,
          property === 'action' || property === 'submitAction',
        );
      } finally {
        ctx.owner = ownerWas;
        ctx.ownerProperty = propertyWas;
      }

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

      // Either spelling of the binding key, because this runs *after*
      // `compileValue` has already written whichever one this version uses.
      // Reading only `path` meant that at 1.0 nothing was ever recognised as
      // the component's bound value, so `?required` on a field compiled to
      // `required()` with no argument at all — a check that passes anything.
      if (
        property === 'value' &&
        value &&
        typeof value === 'object' &&
        ('path' in value || '@path' in value)
      ) {
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
        // `callFor`, not a literal `call`: a check's condition is a function
        // call like any other, and 1.0 spells those `@call`. Hardcoded here, a
        // 1.0 surface carried 1.0 bindings and 0.9 conditions, so every field
        // validated as unconstrained and no check ever ran.
        checks.push({ condition: this.callFor(raw.check, args, ctx) as Json, message });
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

  /** A data binding, spelled the way this protocol version spells it. */
  private bindingFor(path: string, ctx: CompileContext): JsonObject {
    return isV1(ctx.version) ? { '@path': path } : { path };
  }

  /** A dynamic function call, likewise. */
  private callFor(name: string, args: Json, ctx: CompileContext): JsonObject {
    return isV1(ctx.version) ? { '@call': name, args } : { call: name, args };
  }

  /**
   * What to call an inline constructor found in the component being compiled.
   *
   * `root_child`, or `root_child_children_1_child` four levels down: the id
   * says where it came from, which is what makes a hoisted component findable
   * at all — nothing in the source named it.
   *
   * Outside a component (a bare inline in a data assignment, say) there is no
   * owner to name it after, so it falls back to the position it was met in.
   */
  private hoistedId(ctx: CompileContext): string {
    if (ctx.owner && ctx.ownerProperty) return `${ctx.owner}_${ctx.ownerProperty}`;
    return `_inline_${ctx.pending.length + 1}`;
  }

  private compileValue(
    value: AstValue,
    symbols: Map<string, AstValue>,
    ctx: CompileContext,
    isAction: boolean,
  ): Json {
    if (Array.isArray(value)) {
      // The index joins the name, so the two inlines in `Column([Text(…),
      // Button(…)])` become `…_children_0` and `…_children_1` rather than
      // colliding on one id — which a client resolves to whichever arrived last.
      const propertyWas = ctx.ownerProperty;
      try {
        return value.map((item, at) => {
          ctx.ownerProperty = propertyWas === null ? null : `${propertyWas}_${at}`;
          return this.compileValue(item, symbols, ctx, isAction);
        });
      } finally {
        ctx.ownerProperty = propertyWas;
      }
    }

    if (value === null || typeof value !== 'object') return value as Json;

    // A2UI 1.0 reserves `@` for directives: a binding is `{"@path": …}` and a
    // plain `{"path": …}` is ordinary data. The AST keeps the unprefixed name
    // because that is what the DSL writes; the prefix is a wire spelling and
    // belongs here, where the wire is produced.
    if (isPath(value)) return this.bindingFor(value.path, ctx) as Json;

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
      return this.callFor(value.check, args, ctx) as Json;
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
    //
    // Queued rather than compiled here, so the owner finishes before its
    // children start — see `CompileContext.pending` for why that ordering is
    // the wire's and not an implementation detail.
    if (this.helper.hasComponent(name)) {
      const inlineId = this.hoistedId(ctx);
      ctx.pending.push({ id: inlineId, node, symbols });
      return inlineId;
    }

    if (name === '_template') {
      if (args.length < 2) {
        throw new Error(
          '_template requires 2 arguments: the list path and the template component.',
        );
      }
      const pathValue = this.compileValue(args[0]!, symbols, ctx, isAction);
      // Either spelling, because `compileValue` has just emitted whichever one
      // this version uses: 1.0 reserves `@` for directives, so a binding is
      // `{"@path": …}` there. Reading only `path` rejected every `_template` in
      // the catalog at 1.0 — "must be a '$' data binding path" about a path
      // that was a '$' data binding path.
      const path = (pathValue as { path?: string; '@path'?: string } | null)?.['@path'] ??
        (pathValue as { path?: string } | null)?.path;
      if (!pathValue || typeof pathValue !== 'object' || typeof path !== 'string') {
        throw new Error(
          "_template's first argument must be a '$' data binding path, e.g. _template($/items, row).",
        );
      }
      const componentId = this.compileValue(args[1]!, symbols, ctx, isAction);
      // `path` unprefixed on the way out: a ChildList template's own key keeps
      // the 0.9 spelling at 1.0, which is the spec's choice, not ours.
      return { path, componentId };
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
      // An event with nothing to say carries no `context` key at all, rather
      // than an empty object. The reference omits it, and a client that
      // round-trips what it was handed sends the empty object back — so the
      // key's presence has to mean the author wrote one.
      if (Object.keys(context).length === 0) return { event: { name: eventName } };
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
      //
      // `callFor` in both, because the key is 1.0's `@call` either way — the
      // envelope changes, the directive does not.
      if (isAction) return { functionCall: this.callFor(name, compiledArgs, ctx) as Json };
      return this.callFor(name, compiledArgs, ctx) as Json;
    }

    return this.callFor(
      name,
      args.map((arg) => this.compileValue(arg, symbols, ctx, isAction)),
      ctx,
    ) as Json;
  }
}
