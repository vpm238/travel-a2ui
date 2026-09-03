/**
 * The catalog, on screen.
 *
 * This is the vocabulary. Everything the agent can draw is here and nowhere
 * else: it cannot invent a component, and a component the host cannot render
 * cannot be in the catalog. So it is worth being able to see it without reading
 * a JSON schema — both to know what the agent has to work with, and to check
 * that what it emitted was in the list.
 *
 * The signatures shown are generated from the same crawl the skill generator
 * uses, in the same declaration order, because in a positional notation
 * **declaration order is the API**. What you read here is what the model reads.
 */

import { useEffect, useMemo, useState } from 'react';
import { CatalogHelper, type CatalogSchema } from '@travel-a2ui/express';
import { supportedComponents } from '@travel-a2ui/renderer';

import { catalogUrl } from '../api.js';
import { Empty, Spinner } from './bits.js';

interface Signature {
  name: string;
  args: string;
  description?: string;
  /** From the travel catalog rather than the upstream A2UI basic one. */
  travel: boolean;
  /** Whether this host can actually draw it. */
  rendered: boolean;
  props: Array<{ name: string; required: boolean; static: boolean; enum?: string[]; description?: string }>;
}

/** Names in the upstream A2UI v0.9.1 basic catalog, used to tell the two apart. */
const BASIC = new Set([
  'Text', 'Image', 'Icon', 'Video', 'AudioPlayer', 'Row', 'Column', 'List', 'Card',
  'Tabs', 'Modal', 'Divider', 'Button', 'TextField', 'CheckBox', 'ChoicePicker',
  'Slider', 'DateTimeInput',
]);

function signaturesOf(catalog: CatalogSchema): { components: Signature[]; functions: Signature[] } {
  const helper = new CatalogHelper(catalog);
  const rendered = new Set(supportedComponents());

  const components = helper.componentNames().map((name): Signature => {
    const required = new Set(helper.getComponentRequired(name));
    const props = helper.getComponentProperties(name).map((prop) => {
      const schema = helper.getPropertySchema(name, prop);
      const ref = typeof schema?.['$ref'] === 'string' ? schema['$ref'] : '';
      const dynamic = /DataBinding|Dynamic|ChildList/.test(ref);
      const entry: Signature['props'][number] = {
        name: prop,
        required: required.has(prop),
        static: !dynamic,
      };
      const values = helper.getPropertyEnum(name, prop);
      if (values) entry.enum = values;
      const description = schema?.['description'];
      if (typeof description === 'string') entry.description = description;
      return entry;
    });

    return {
      name,
      args: props
        .map((prop) => `${prop.name}${prop.required ? '' : '?'}`)
        .join(', '),
      ...(helper.getComponentDescription(name) ? { description: helper.getComponentDescription(name)! } : {}),
      travel: !BASIC.has(name),
      rendered: rendered.has(name),
      props,
    };
  });

  const functions = helper.functionNames().map((name): Signature => {
    const required = new Set(helper.getFunctionRequired(name));
    const props = helper.getFunctionProperties(name).map((prop) => ({
      name: prop,
      required: required.has(prop),
      static: false,
    }));
    return {
      name,
      args: props.map((prop) => `${prop.name}${prop.required ? '' : '?'}`).join(', '),
      ...(helper.getFunctionDescription(name) ? { description: helper.getFunctionDescription(name)! } : {}),
      travel: false,
      rendered: true,
      props,
    };
  });

  return { components, functions };
}

export function Catalog() {
  const [catalog, setCatalog] = useState<CatalogSchema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [only, setOnly] = useState<'all' | 'travel' | 'basic'>('all');

  useEffect(() => {
    fetch(catalogUrl())
      .then((response) => response.json() as Promise<CatalogSchema>)
      .then(setCatalog)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const { components, functions } = useMemo(
    () => (catalog ? signaturesOf(catalog) : { components: [], functions: [] }),
    [catalog],
  );

  const query = filter.trim().toLowerCase();
  const visible = components.filter((component) => {
    if (only === 'travel' && !component.travel) return false;
    if (only === 'basic' && component.travel) return false;
    if (!query) return true;
    return (
      component.name.toLowerCase().includes(query) ||
      component.description?.toLowerCase().includes(query) ||
      component.props.some((prop) => prop.name.toLowerCase().includes(query))
    );
  });

  const unrenderable = components.filter((component) => !component.rendered);

  return (
    <section className="catalog" aria-label="Component catalog">
      <header className="catalog__head">
        <div>
          <h2>The catalog</h2>
          <p>
            Everything the agent can draw. It cannot invent a component, and nothing is here that
            this host cannot render. These signatures are generated from the schema in declaration
            order — the same crawl the skill generator does, so this is what the model reads.
          </p>
        </div>
        <div className="catalog__meta">
          <code>{catalog?.catalogId ?? '…'}</code>
          <a href={catalogUrl()} target="_blank" rel="noreferrer">
            raw JSON →
          </a>
        </div>
      </header>

      {error ? <p className="mcp__error">{error}</p> : null}
      {!catalog && !error ? <Spinner label="Loading the catalog" /> : null}

      {catalog ? (
        <>
          <div className="catalog__controls">
            <input
              value={filter}
              placeholder="Filter components…"
              aria-label="Filter components"
              onChange={(event) => setFilter(event.target.value)}
            />
            <div className="segmented" role="group" aria-label="Which components">
              {(
                [
                  ['all', `All ${components.length}`],
                  ['travel', `Travel ${components.filter((c) => c.travel).length}`],
                  ['basic', `A2UI basic ${components.filter((c) => !c.travel).length}`],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={only === value}
                  className={only === value ? 'is-active' : undefined}
                  onClick={() => setOnly(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {unrenderable.length > 0 ? (
            <p className="catalog__warn">
              {unrenderable.length} component(s) in the catalog have no renderer here:{' '}
              {unrenderable.map((component) => component.name).join(', ')}. The agent would be told
              about them and the host could not draw them.
            </p>
          ) : null}

          {visible.length === 0 ? (
            <Empty title="Nothing matches">Try a different filter.</Empty>
          ) : (
            <ul className="catalog__list">
              {visible.map((component) => (
                <li key={component.name} className={component.travel ? 'is-travel' : undefined}>
                  <h3>
                    <span className="catalog__name">{component.name}</span>
                    <span className="catalog__args">({component.args})</span>
                    {component.travel ? <span className="catalog__tag">travel</span> : null}
                  </h3>
                  {component.description ? <p>{component.description}</p> : null}
                  <dl>
                    {component.props.map((prop) => (
                      <div key={prop.name}>
                        <dt>
                          {prop.name}
                          {prop.required ? <em title="required">required</em> : null}
                          {prop.static ? <em className="is-static" title="literal values only">static</em> : null}
                        </dt>
                        <dd>
                          {prop.description ?? ''}
                          {prop.enum ? (
                            <span className="catalog__enum">
                              {prop.enum.map((value) => (
                                <code key={value}>{value}</code>
                              ))}
                            </span>
                          ) : null}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          )}

          <section className="catalog__functions">
            <h3>Functions</h3>
            <p>
              Used in validation rules (<code>?required</code>) and dynamic values
              (<code>formatCurrency($/total, "EUR")</code>).
            </p>
            <ul>
              {functions.map((fn) => (
                <li key={fn.name}>
                  <code>
                    {fn.name}({fn.args})
                  </code>
                  {fn.description ? <span>{fn.description}</span> : null}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </section>
  );
}
