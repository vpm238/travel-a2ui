/**
 * Unit tests for the pieces parity cannot reach: streaming, error messages, and
 * the lexer corners where ANTLR's tie-breaking rules actually matter.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  ExpressCompiler,
  ExpressDecompiler,
  ExpressStreamParser,
  ExpressUndefinedRootError,
  ExpressUnknownPropertyError,
  ExpressForbiddenDatabindingError,
  ExpressInvalidEnumError,
  T,
  extractExpressBlock,
  parse,
  tokenize,
  type CatalogSchema,
  type StreamEvent,
} from '../src/index.js';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..', '..');
const catalog = JSON.parse(
  readFileSync(join(root, 'catalogs', 'a2ui-travel', 'catalog.json'), 'utf8'),
) as CatalogSchema;

const compiler = new ExpressCompiler(catalog, 'v0.9.1');
const compile = (source: string) =>
  compiler.compile(source, { surfaceId: 's', catalogId: catalog.catalogId, version: 'v0.9.1' });

const componentsOf = (messages: ReturnType<typeof compile>) => {
  for (const message of messages) {
    if ('updateComponents' in message) return message.updateComponents.components;
  }
  return [];
};

describe('lexer', () => {
  it('prefers the literal token over IDENTIFIER only on an exact match', () => {
    const types = tokenize('null nullish _ _template true trueish').map((t) => t.type);
    expect(types).toEqual([
      T.NULL,
      T.IDENTIFIER,
      T.UNDERSCORE,
      T.IDENTIFIER,
      T.BOOLEAN,
      T.IDENTIFIER,
      T.EOF,
    ]);
  });

  it('lexes a negative number as one token, not minus then digits', () => {
    const tokens = tokenize('-12.5');
    expect(tokens[0]).toMatchObject({ type: T.NUMBER, text: '-12.5' });
  });

  it('lets a backslash consume the character after it inside a string', () => {
    const tokens = tokenize('"a\\\\" "b"');
    expect(tokens[0]!.type).toBe(T.STANDARD_STRING);
    expect(tokens[1]!.type).toBe(T.STANDARD_STRING);
  });

  it('skips both comment forms and semicolons', () => {
    const types = tokenize('# one\na // two\n/* three */ b;').map((t) => t.type);
    expect(types).toEqual([T.IDENTIFIER, T.IDENTIFIER, T.EOF]);
  });

  it('stops at a truncated string when tolerant, throws when not', () => {
    expect(() => tokenize('a = "unfinis')).toThrow(/unterminated string/);
    expect(tokenize('a = "unfinis', true).map((t) => t.type)).toEqual([
      T.IDENTIFIER,
      T.EQUALS,
      T.EOF,
    ]);
  });
});

describe('parser', () => {
  it('keeps statements before the first error and reports the error', () => {
    const { statements, errors } = parse('a = Text("ok")\nb = Text(', { isFinal: true });
    expect(statements).toHaveLength(1);
    expect(errors).toHaveLength(1);
    expect(errors[0]!.line).toBe(2);
  });

  it('reads a trailing comma in arrays, maps and calls', () => {
    const { errors } = parse('a = Text("x",)\nb = [1, 2,]\nc = {k: 1,}');
    expect(errors).toEqual([]);
  });
});

describe('sentinels', () => {
  it('keeps only what is between the tags', () => {
    const text = 'Here you go:\n<a2ui>\nroot = Text("Hi")\n</a2ui>\nAnything else?';
    expect(extractExpressBlock(text).trim()).toBe('root = Text("Hi")');
  });

  it('treats untagged input as a bare block', () => {
    expect(extractExpressBlock('root = Text("Hi")').trim()).toBe('root = Text("Hi")');
  });
});

describe('compiler errors', () => {
  it('names the properties a component does accept', () => {
    expect(() => compile('root = Text("hi", colour="red")')).toThrow(ExpressUnknownPropertyError);
    try {
      compile('root = Text("hi", colour="red")');
    } catch (error) {
      expect((error as Error).message).toContain('text, variant');
    }
  });

  it('rejects a data binding on a static property', () => {
    expect(() => compile('root = Text("hi", variant=$/style/heading)')).toThrow(
      ExpressForbiddenDatabindingError,
    );
  });

  it('rejects a value outside a property enum', () => {
    expect(() => compile('root = Text("hi", variant="enormous")')).toThrow(ExpressInvalidEnumError);
  });

  it('requires a root', () => {
    expect(() => compile('a = Text("hi")')).toThrow(ExpressUndefinedRootError);
  });
});

describe('compiler semantics', () => {
  it('hoists inline constructors and leaves their ids behind', () => {
    const components = componentsOf(compile('root = Card(Column([Text("a"), Text("b")]))'));
    const rootNode = components.find((c) => c.id === 'root')!;
    expect(rootNode['child']).toBe('_inline_1');
    expect(components.map((c) => c.id).sort()).toEqual(
      ['_inline_1', '_inline_2', '_inline_3', 'root'].sort(),
    );
  });

  it('wraps a catalog function as a handler in an action slot and a value elsewhere', () => {
    const components = componentsOf(
      compile(
        'a = Text(formatCurrency($/total, "EUR"))\n' +
          'b = Button(a, action=openUrl("https://example.com"))\n' +
          'root = Column([b])',
      ),
    );
    const text = components.find((c) => c.id === 'a')!;
    const button = components.find((c) => c.id === 'b')!;
    expect(text['text']).toMatchObject({ call: 'formatCurrency' });
    expect(button['action']).toMatchObject({ functionCall: { call: 'openUrl' } });
  });

  it('borrows the bound value as a check subject', () => {
    const components = componentsOf(
      compile('f = TextField("Email", $/form/email, ?required)\nroot = Column([f])'),
    );
    const field = components.find((c) => c.id === 'f')!;
    expect(field['checks']).toEqual([
      { condition: { call: 'required', args: { value: { path: '/form/email' } } }, message: 'Required check failed' },
    ]);
  });

  it('reads a trailing string as the failure message, not an argument', () => {
    const components = componentsOf(
      compile('f = TextField("Zip", $/form/zip, ?length(5, "Five digits"))\nroot = Column([f])'),
    );
    const field = components.find((c) => c.id === 'f')!;
    expect(field['checks']).toEqual([
      {
        condition: { call: 'length', args: { value: { path: '/form/zip' }, min: 5 } },
        message: 'Five digits',
      },
    ]);
  });

  it('lifts bare option strings into label/value pairs', () => {
    const components = componentsOf(
      compile('p = ChoicePicker("Cabin", _, ["economy", "business"], $/c)\nroot = Column([p])'),
    );
    const picker = components.find((c) => c.id === 'p')!;
    expect(picker['options']).toEqual([
      { label: 'economy', value: 'economy' },
      { label: 'business', value: 'business' },
    ]);
  });
});

describe('streaming', () => {
  const collect = (chunks: string[]): StreamEvent[] => {
    const stream = new ExpressStreamParser(compiler, {
      surfaceId: 's',
      catalogId: catalog.catalogId,
      version: 'v0.9.1',
    });
    const events: StreamEvent[] = [];
    for (const chunk of chunks) events.push(...stream.push(chunk));
    events.push(...stream.end());
    return events;
  };

  it('separates prose from UI and finishes the block', () => {
    const events = collect([
      'Two options for you:\n',
      '<a2ui>\ntitle = Text(',
      '"Options")\nroot = Column([title])\n</a2ui>',
      '\nWant me to hold one?',
    ]);
    const text = events
      .filter((e) => e.type === 'text')
      .map((e) => (e as { delta: string }).delta)
      .join('');
    expect(text).toContain('Two options for you');
    expect(text).toContain('Want me to hold one?');

    const done = events.filter((e) => e.type === 'ui' && e.done);
    expect(done).toHaveLength(1);
  });

  it('reassembles a sentinel split across chunks', () => {
    const events = collect(['before <a2', 'ui>\nroot = Text("Hi")\n</a2', 'ui> after']);
    const text = events
      .filter((e) => e.type === 'text')
      .map((e) => (e as { delta: string }).delta)
      .join('');
    expect(text).toBe('before  after');
    expect(events.some((e) => e.type === 'ui' && e.done)).toBe(true);
  });

  it('paints a partial tree before the block closes', () => {
    const stream = new ExpressStreamParser(compiler, {
      surfaceId: 's',
      catalogId: catalog.catalogId,
      version: 'v0.9.1',
    });
    stream.push('<a2ui>\na = Text("One")\nroot = Column([a])\n');
    const partial = stream.push('b = Text("Two")\n');
    const uiEvents = partial.filter((e) => e.type === 'ui');
    expect(uiEvents.length).toBeGreaterThan(0);
    const [event] = uiEvents as Array<Extract<StreamEvent, { type: 'ui' }>>;
    expect(event!.done).toBe(false);
    expect(componentsOf(event!.messages).map((c) => c.id)).toContain('root');
  });

  it('reports a syntax error only once the block is finished', () => {
    const events = collect(['<a2ui>\nroot = Column([\n</a2ui>']);
    expect(events.some((e) => e.type === 'error')).toBe(true);
  });
});

describe('decompiler', () => {
  it('folds the v0.9.1 three-message form back into one block', () => {
    const messages = compile('$/x = 1\na = Text("Hi")\nroot = Column([a])');
    const express = new ExpressDecompiler(catalog).decompile(messages as never);
    expect(express.match(/surface\(/g) ?? []).toHaveLength(1);
    expect(express).toContain('root = Column([a])');
  });
});
