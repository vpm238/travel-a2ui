/**
 * What the agent said about assistive technology, as DOM attributes.
 *
 * This is a pass that can only fail silently. Nothing on screen changes when a
 * label is dropped, no test that reads the page notices, and the only person
 * who finds out is using a screen reader. So the checks here are about the
 * three ways that happens: the property not being read at all, a name landing
 * on an element with no role (where every screen reader discards it), and a
 * role being handed to something that was already a control.
 *
 * The first test is structural, in the spirit of `functions.test.ts`: it reads
 * the catalog, and fails if the protocol offers a key this file does not
 * translate.
 */

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { ariaOf } from '../src/accessibility.js';
import { IconComponent } from '../src/components/basic.js';
import type { ResolveScope } from '../src/binding.js';
import { supportedComponents } from '../src/Surface.js';
import catalog from '../../../catalogs/a2ui-travel/catalog.json';

const EMPTY: ResolveScope = { model: {}, itemPointer: '' };

const scopeOf = (model: Record<string, unknown>): ResolveScope => ({
  model: model as never,
  itemPointer: '',
});

const node = (accessibility: unknown) =>
  ({ component: 'Text', accessibility }) as never;

describe('the catalog and this file agree', () => {
  it('translates every key the protocol offers', () => {
    const declared = Object.keys(
      (catalog as never as { $defs: { AccessibilityAttributes: { properties: object } } }).$defs
        .AccessibilityAttributes.properties,
    );
    expect(declared.sort()).toEqual(['description', 'hidden', 'label', 'live']);
  });

  it('offers it on every component, which is what makes it worth reading', () => {
    const components = (catalog as never as { components: Record<string, never> }).components;
    const without = Object.entries(components).filter(
      ([, schema]) =>
        !JSON.stringify(schema).includes('#/$defs/CatalogComponentCommon'),
    );
    expect(without.map(([name]) => name)).toEqual([]);
  });
});

describe('every component this host draws reads the block', () => {
  /**
   * The source of each renderer, carved up by the function it belongs to.
   *
   * Reading source in a test is unusual and is the point: a helper that is
   * correct and uncalled is the failure this whole file exists to catch, and it
   * is invisible to any test that exercises `ariaOf` directly. Nothing else
   * here would notice a component that quietly stopped spreading it.
   */
  const BODIES = (() => {
    const out = new Map<string, string>();
    for (const file of ['basic.tsx', 'travel.tsx', 'map.tsx']) {
      const source = readFileSync(new URL(`../src/components/${file}`, import.meta.url), 'utf8');
      for (const chunk of source.split(/\nexport function /).slice(1)) {
        out.set(chunk.slice(0, chunk.indexOf('(')), chunk);
      }
    }
    return out;
  })();

  /** Where a catalog name and its function's name do not line up. */
  const ALIASES: Record<string, string> = { AudioPlayer: 'AudioComponent' };

  it.each(supportedComponents())('%s', (name) => {
    // Most of the registry's renderers are named after their component, and
    // the few that collide with a React import carry a `Component` suffix.
    const body = BODIES.get(ALIASES[name] ?? name) ?? BODIES.get(`${name}Component`);
    expect(body, `no renderer function found for ${name}`).toBeDefined();
    expect(body).toContain('ariaOf(');
  });
});

describe('an icon the agent named', () => {
  /**
   * Read off the returned element rather than a rendered DOM, which needs no
   * test renderer and is enough here: the question is only which props the
   * component hands down.
   *
   * `Icon` sets `aria-hidden` on itself — correct for the glyphs inside a card,
   * and the one case where honouring `accessibility` is not just spreading it:
   * a label on a hidden subtree is announced to nobody.
   */
  const propsOf = (accessibility?: unknown) =>
    (
      IconComponent({
        node: { component: 'Icon', name: 'plane', accessibility } as never,
        scope: EMPTY,
        ctx: {} as never,
      }) as { props: Record<string, unknown> }
    ).props;

  it('is hidden by default, as decoration inside a card', () => {
    expect(propsOf()['aria-hidden']).toBe(true);
  });

  it('stops being hidden once it carries a name', () => {
    const props = propsOf({ label: 'Nonstop' });
    expect(props['aria-hidden']).toBeUndefined();
    expect(props['aria-label']).toBe('Nonstop');
    expect(props['role']).toBe('img');
  });

  it('stays hidden when the agent asked for both', () => {
    expect(propsOf({ label: 'Nonstop', hidden: true })['aria-hidden']).toBe(true);
  });
});

describe('ariaOf', () => {
  it('reads nothing from a component that declared nothing', () => {
    expect(ariaOf({ component: 'Text' } as never, EMPTY)).toEqual({});
    expect(ariaOf(undefined, EMPTY)).toEqual({});
  });

  it('ignores a block that is not a block', () => {
    expect(ariaOf(node('Outbound flight'), EMPTY)).toEqual({});
    expect(ariaOf(node(['Outbound flight']), EMPTY)).toEqual({});
  });

  it('carries a label and a description', () => {
    expect(ariaOf(node({ label: 'Outbound', description: 'Press to choose' }), EMPTY)).toEqual({
      'aria-label': 'Outbound',
      'aria-description': 'Press to choose',
    });
  });

  it('resolves a bound label against the data model', () => {
    const scope = scopeOf({ leg: { reads: 'Norwegian, 07:15, €281' } });
    expect(ariaOf(node({ label: { '@path': '/leg/reads' } }), scope)).toEqual({
      'aria-label': 'Norwegian, 07:15, €281',
    });
  });

  it('drops a label that resolved to nothing rather than naming a card ""', () => {
    // A binding to a path the turn has not filled in yet is the ordinary case
    // mid-stream, and `aria-label=""` is worse than no label: it replaces the
    // card's own text with silence.
    expect(ariaOf(node({ label: { '@path': '/not/here' } }), EMPTY)).toEqual({});
    expect(ariaOf(node({ label: '   ' }), EMPTY)).toEqual({});
  });

  describe('the group role', () => {
    it('names a container, which otherwise announces nothing', () => {
      expect(ariaOf(node({ label: 'Your trip' }), EMPTY, 'group')).toEqual({
        'aria-label': 'Your trip',
        role: 'group',
      });
    });

    it('is not handed to something that is already a control', () => {
      expect(ariaOf(node({ label: 'Outbound' }), EMPTY)).not.toHaveProperty('role');
    });

    it('is not invented for a block with no name in it', () => {
      // `live` alone is not a reason to make a box into a group: there is
      // nothing to announce as its name.
      expect(ariaOf(node({ live: 'polite' }), EMPTY, 'group')).toEqual({
        'aria-live': 'polite',
      });
    });
  });

  describe('live', () => {
    it('passes polite and assertive through', () => {
      expect(ariaOf(node({ live: 'polite' }), EMPTY)['aria-live']).toBe('polite');
      expect(ariaOf(node({ live: 'assertive' }), EMPTY)['aria-live']).toBe('assertive');
    });

    it('leaves `off` off, because the attribute is the announcement', () => {
      expect(ariaOf(node({ live: 'off' }), EMPTY)).toEqual({});
    });

    it('ignores a politeness the protocol does not define', () => {
      expect(ariaOf(node({ live: 'shouting' }), EMPTY)).toEqual({});
    });
  });

  describe('hidden', () => {
    it('hides a subtree when asked', () => {
      expect(ariaOf(node({ hidden: true }), EMPTY)).toEqual({ 'aria-hidden': true });
    });

    it('says nothing when false', () => {
      // `aria-hidden="false"` is not "definitely visible" — it is a value the
      // spec leaves to the browser, so the absent case stays absent.
      expect(ariaOf(node({ hidden: false }), EMPTY)).toEqual({});
    });

    it('resolves a bound flag', () => {
      const scope = scopeOf({ ui: { decorative: true } });
      expect(ariaOf(node({ hidden: { '@path': '/ui/decorative' } }), scope)).toEqual({
        'aria-hidden': true,
      });
    });
  });
});
