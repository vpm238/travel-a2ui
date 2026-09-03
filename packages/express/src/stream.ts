/**
 * Incremental Express extraction and compilation for a streaming model.
 *
 * The whole point of Express over raw JSON is that a partial program is still a
 * program: `root = Column([a, b])` compiles the moment those three lines exist,
 * and recompiles when a fourth arrives. So the UI paints while the model is
 * still typing rather than after it stops.
 *
 * This splits a token stream into prose and `<a2ui>` blocks, and recompiles the
 * open block on every chunk. Recompiling from scratch is deliberate: it is
 * microseconds on surfaces this size, and it means a late line can revise an
 * earlier component instead of being stuck with whatever we already emitted.
 *
 * Sentinel tags arriving split across chunks are handled by holding back any
 * tail that could still turn into one.
 */

import { ExpressCompiler, type CompileOptions } from './compiler.js';
import { A2UI_CLOSE, A2UI_OPEN, type A2uiMessage } from './types.js';

export type StreamEvent =
  | { type: 'text'; delta: string }
  | { type: 'ui'; blockIndex: number; messages: A2uiMessage[]; done: boolean }
  | { type: 'error'; blockIndex: number; message: string };

/** Longest prefix of `text`'s tail that is also a proper prefix of `token`. */
function danglingPrefixLength(text: string, token: string): number {
  const max = Math.min(text.length, token.length - 1);
  for (let length = max; length > 0; length--) {
    if (text.endsWith(token.slice(0, length))) return length;
  }
  return 0;
}

export class ExpressStreamParser {
  private buffer = '';
  private inside = false;
  private blockSource = '';
  private blockIndex = -1;
  private lastEmitted = '';

  constructor(
    private readonly compiler: ExpressCompiler,
    private readonly options: CompileOptions = {},
  ) {}

  /** Feeds a chunk of model output and returns the events it produced. */
  push(chunk: string): StreamEvent[] {
    this.buffer += chunk;
    const events: StreamEvent[] = [];

    for (;;) {
      if (!this.inside) {
        const open = this.buffer.indexOf(A2UI_OPEN);
        if (open === -1) {
          // Emit everything except a tail that might still become `<a2ui>`.
          const hold = danglingPrefixLength(this.buffer, A2UI_OPEN);
          const emit = this.buffer.slice(0, this.buffer.length - hold);
          if (emit) events.push({ type: 'text', delta: emit });
          this.buffer = this.buffer.slice(this.buffer.length - hold);
          return events;
        }
        const prose = this.buffer.slice(0, open);
        if (prose) events.push({ type: 'text', delta: prose });
        this.buffer = this.buffer.slice(open + A2UI_OPEN.length);
        this.inside = true;
        this.blockIndex += 1;
        this.blockSource = '';
        this.lastEmitted = '';
        continue;
      }

      const close = this.buffer.indexOf(A2UI_CLOSE);
      if (close === -1) {
        const hold = danglingPrefixLength(this.buffer, A2UI_CLOSE);
        this.blockSource += this.buffer.slice(0, this.buffer.length - hold);
        this.buffer = this.buffer.slice(this.buffer.length - hold);
        const event = this.compileBlock(false);
        if (event) events.push(event);
        return events;
      }

      this.blockSource += this.buffer.slice(0, close);
      this.buffer = this.buffer.slice(close + A2UI_CLOSE.length);
      this.inside = false;
      const event = this.compileBlock(true);
      if (event) events.push(event);
    }
  }

  /** Flushes anything still buffered when the model stops. */
  end(): StreamEvent[] {
    const events: StreamEvent[] = [];
    if (this.inside) {
      // The model stopped mid-block. Compile what we have — an unterminated
      // block usually still describes a complete tree.
      this.blockSource += this.buffer;
      this.buffer = '';
      this.inside = false;
      const event = this.compileBlock(true);
      if (event) events.push(event);
    } else if (this.buffer) {
      events.push({ type: 'text', delta: this.buffer });
      this.buffer = '';
    }
    return events;
  }

  private compileBlock(done: boolean): StreamEvent | null {
    const source = this.blockSource;
    if (!source.trim()) return null;
    // Nothing new to say if the source has not changed since the last emit.
    if (!done && source === this.lastEmitted) return null;
    this.lastEmitted = source;

    try {
      const messages = this.compiler.compile(source, { ...this.options, isFinal: done });
      return { type: 'ui', blockIndex: this.blockIndex, messages, done };
    } catch (error) {
      // Mid-stream failures are expected — half a constructor is not valid
      // Express. Only a failure on the finished block is worth reporting.
      if (!done) return null;
      return {
        type: 'error',
        blockIndex: this.blockIndex,
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }
}
