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
 *
 * Open one and it draws. Not a screenshot and not a mock — the same compiler
 * and the same React components a real turn goes through, given Express derived
 * from the component's own schema. That makes the gallery unable to lie: a
 * component whose renderer is broken is visibly broken here, and one added to
 * the catalog appears with a working preview without anyone writing it a
 * gallery entry.
 */

/**
 * A component, drawn on its own little surface.
 *
 * Each preview gets its own SDK processor, so a Slider moved in one does not
 * move the one three rows down, and an interaction goes nowhere: this is a
 * specimen, not a conversation. The messages were compiled at build time by
 * the A2UI SDK's own parser (`scripts/build_catalog_reference.py`), so this
 * page ships no compiler.
 */
function Preview({ component, withSource = true }: { component: Entry; withSource?: boolean }) {
  const surfaces = useMemo(() => {
    if (!component.messages) return null;
    const preview = new Surfaces();
    preview.apply(component.messages);
    return preview;
  }, [component]);
  const surfaceId = surfaces?.ids()[0];

  return (
    <div className="preview">
      {surfaces && surfaceId ? (
        <div className="preview__stage">
          <SurfaceView surfaces={surfaces} surfaceId={surfaceId} />
        </div>
      ) : (
        <p className="preview__error">{component.error ?? 'No example for this component.'}</p>
      )}
      {withSource ? (
        <details className="preview__source">
          <summary>The Express that drew it</summary>
          <pre>{component.express}</pre>
        </details>
      ) : null}
    </div>
  );
}

import { useMemo, useState } from 'react';

import reference from '../generated/catalog-reference.json';
import { catalogUrl } from '../api.js';
import { Surfaces } from '../surfaces.js';
import { Empty } from './bits.js';
import { SurfaceView } from './SurfaceView.js';

interface Prop {
  name: string;
  required: boolean;
  static: boolean;
  enum?: string[];
  description?: string;
}

interface Entry {
  name: string;
  args: string;
  description?: string;
  /** From the travel catalog rather than the A2UI basic one. */
  travel?: boolean;
  props: Prop[];
  express?: string;
  messages?: unknown[];
  error?: string;
}

const components = reference.components as Entry[];
const functions = reference.functions as Entry[];

export function Catalog() {
  const [filter, setFilter] = useState('');
  const [only, setOnly] = useState<'all' | 'travel' | 'basic'>('all');
  /** Which component is showing its reference. One at a time: they are tall. */
  const [open, setOpen] = useState<string | null>(null);

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

  return (
    <section className="catalog" aria-label="Component catalog">
      <header className="catalog__head">
        <div>
          <h2>The catalog</h2>
          <p>
            Everything the agent can draw. It cannot invent a component, and nothing is here that this host
            cannot render. These signatures are generated from the schema in declaration order — the same
            crawl the skill generator does, so this is what the model reads.
          </p>
        </div>
        <div className="catalog__meta">
          <code>{reference.catalogId}</code>
          <a href={catalogUrl()} target="_blank" rel="noreferrer">
            raw JSON →
          </a>
        </div>
      </header>

      {
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

          {visible.length === 0 ? (
            <Empty title="Nothing matches">Try a different filter.</Empty>
          ) : (
            <ul className="catalog__grid">
              {visible.map((component) => {
                const isOpen = open === component.name;
                return (
                  <li
                    key={component.name}
                    className={`catalog__card${component.travel ? ' is-travel' : ''}${
                      isOpen ? ' is-open' : ''
                    }`}
                  >
                    {/*
                      The component itself, first and largest.

                      The signature comes second: a catalog whose argument is
                      that a component *looks* like a flight is judged by eye.
                    */}
                    <button
                      type="button"
                      className="catalog__cardFace"
                      aria-expanded={isOpen}
                      onClick={() => setOpen(isOpen ? null : component.name)}
                    >
                      <div className="catalog__render" aria-hidden inert>
                        <Preview component={component} withSource={false} />
                      </div>
                      <span className="catalog__label">
                        <span className="catalog__name">{component.name}</span>
                        {component.travel ? <span className="catalog__tag">travel</span> : null}
                      </span>
                    </button>

                    {/* The reference, for when the picture has done its job. */}
                    {isOpen ? (
                      <div className="catalog__detail">
                        <p className="catalog__args">({component.args})</p>
                        <Preview component={component} />
                        {component.description ? <p>{component.description}</p> : null}
                        <dl>
                          {component.props.map((prop) => (
                            <div key={prop.name}>
                              <dt>
                                {prop.name}
                                {prop.required ? <em title="required">required</em> : null}
                                {prop.static ? (
                                  <em className="is-static" title="literal values only">
                                    static
                                  </em>
                                ) : null}
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
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}

          <section className="catalog__functions">
            <h3>Functions</h3>
            <p>
              Used in validation rules (<code>?required</code>) and dynamic values (
              <code>formatCurrency($/total, "EUR")</code>).
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
      }
    </section>
  );
}
