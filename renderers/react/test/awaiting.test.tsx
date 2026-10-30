/**
 * A card whose row has not arrived is shown, and is not pressable.
 *
 * Drawing a list before its lookup returns is the whole design, and the way it
 * shows is a shimmer per field. What that left behind was a button: a card is
 * interactive from `Boolean(node.action)` alone, the handlers ran whatever the
 * card's state, and a placeholder's `action` carries bindings into the row that
 * is not there — so pressing one sent `select_flight` with a null id and
 * recorded a choice of nothing.
 *
 * Rendered rather than asserted on the predicate alone, through
 * `react-dom/server`, which needs no DOM: the bug was never in the predicate,
 * it was in which attributes the element ended up with.
 */

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { awaiting } from '../src/components/travel.js';
import { FlightOption, HotelCard } from '../src/components/travel.js';

type Json = Parameters<typeof awaiting>[0][string];

/**
 * The scope a seeded row is actually drawn in.
 *
 * Not the surface root: `Flights()` is one template under `_template(/flights,
 * row)`, so each card resolves its relative `price` against `/flights/<n>`.
 * Passing `{}` as the row is exactly what `seed_rows` files, which is the case
 * under test.
 */
function rowScope(row: Record<string, Json>) {
  return {
    model: { flights: [row] },
    itemPointer: '/flights/0',
  } as Parameters<typeof awaiting>[1];
}

const ctx = {
  send: () => undefined,
  surfaceId: 'inline-1',
  components: {},
} as unknown as Parameters<typeof FlightOption>[0]['ctx'];

const bind = (path: string) => ({ '@path': path });

const FARE = {
  component: 'FlightOption',
  id: 'row',
  airline: bind('airline'),
  flightNumber: bind('flightNumber'),
  price: bind('price'),
  action: { event: { name: 'select_flight', context: { id: bind('id') } } },
};

const STAY = {
  component: 'HotelCard',
  id: 'row',
  name: bind('name'),
  price: bind('price'),
  action: { event: { name: 'select_hotel', context: { id: bind('id') } } },
};

function markup(
  Component: typeof FlightOption | typeof HotelCard,
  node: Record<string, Json>,
  data: Record<string, Json>,
) {
  return renderToStaticMarkup(<Component node={node as never} scope={rowScope(data)} ctx={ctx} />);
}

describe('the predicate', () => {
  it('calls a row awaiting when every named field is unresolvable', () => {
    expect(awaiting(FARE as never, rowScope({}), ['flightNumber', 'price'])).toBe(true);
  });

  it('and not awaiting as soon as one of them resolves', () => {
    const scope = rowScope({ price: '€281' });
    expect(awaiting(FARE as never, scope, ['flightNumber', 'price'])).toBe(false);
  });

  it('treats an empty string as arrived, not as waiting', () => {
    // The data model's own rule, and the reason this needs no loading flag: a
    // path that resolves to '' has an answer and the answer is nothing.
    const scope = rowScope({ flightNumber: '', price: '' });
    expect(awaiting(FARE as never, scope, ['flightNumber', 'price'])).toBe(false);
  });

  it('never calls a literal awaiting', () => {
    const written = { ...FARE, flightNumber: 'DY1234', price: '€281' };
    expect(awaiting(written as never, rowScope({}), ['flightNumber', 'price'])).toBe(false);
  });
});

describe('a fare whose row has not arrived', () => {
  const html = markup(FlightOption, FARE, {});

  it('is not announced as a button', () => {
    expect(html).not.toContain('role="button"');
  });

  it('is not in the tab order', () => {
    expect(html).not.toContain('tabindex="0"');
  });

  it('says it is busy', () => {
    expect(html).toContain('aria-busy="true"');
  });

  it('shows the shimmer rather than empty space', () => {
    expect(html).toContain('tv-pending');
  });

  it('and carries the class the stylesheet needs', () => {
    expect(html).toContain('is-awaiting');
    expect(html).not.toContain('is-interactive');
  });
});

describe('the same fare once its row lands', () => {
  const html = markup(FlightOption, FARE, { flightNumber: 'DY1234', price: '€281', id: 'DY1234' });

  it('is a button again', () => {
    expect(html).toContain('role="button"');
    expect(html).toContain('tabindex="0"');
  });

  it('is no longer busy', () => {
    expect(html).not.toContain('aria-busy');
    expect(html).not.toContain('is-awaiting');
  });

  it('and shows what it is', () => {
    expect(html).toContain('DY1234');
    expect(html).toContain('€281');
  });
});

describe('a stay', () => {
  it('is not pressable while its row is awaited', () => {
    const html = markup(HotelCard, STAY, {});
    expect(html).not.toContain('role="button"');
    expect(html).toContain('aria-busy="true"');
  });

  it('is pressable once it lands', () => {
    const html = markup(HotelCard, STAY, { name: 'Hostal Persal', price: '€96' });
    expect(html).toContain('role="button"');
    expect(html).toContain('Hostal Persal');
  });

  it('is not a button at all when it carries no action', () => {
    // It used to be one unconditionally, so a stay drawn to be read — on the
    // trip panel, where the only press is Change — was announced to a screen
    // reader as a button that did nothing.
    const html = markup(HotelCard, { ...STAY, action: undefined }, { name: 'Hostal Persal' });
    expect(html).not.toContain('role="button"');
    expect(html).not.toContain('tabindex="0"');
  });
});
