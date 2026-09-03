/**
 * Hand-written lexer for A2UI Express.
 *
 * The reference implementation generates its lexer from `Express.g4` with
 * ANTLR. We do not ship an ANTLR runtime to a Cloudflare Worker for a grammar
 * this small, so this is a direct transcription of that grammar's lexer rules.
 * Two ANTLR behaviours are reproduced deliberately, because Express text in the
 * wild depends on them:
 *
 *   1. Maximal munch — the longest match wins.
 *   2. On a tie, the rule declared first wins, and implicit literal tokens
 *      ('null', '_', punctuation) are declared before named lexer rules. That
 *      is why `null` lexes as NULL but `nullish` lexes as IDENTIFIER, and why
 *      `_` is the skipped-argument sentinel but `_template` is an identifier.
 */

import { ExpressSyntaxError } from './errors.js';

export enum T {
  RAW_TRIPLE_STRING = 'RAW_TRIPLE_STRING',
  TRIPLE_STRING = 'TRIPLE_STRING',
  RAW_STRING = 'RAW_STRING',
  STANDARD_STRING = 'STANDARD_STRING',
  PATH = 'PATH',
  CHECK = 'CHECK',
  NUMBER = 'NUMBER',
  BOOLEAN = 'BOOLEAN',
  NULL = 'NULL',
  UNDERSCORE = 'UNDERSCORE',
  IDENTIFIER = 'IDENTIFIER',
  EQUALS = 'EQUALS',
  LBRACKET = 'LBRACKET',
  RBRACKET = 'RBRACKET',
  LBRACE = 'LBRACE',
  RBRACE = 'RBRACE',
  LPAREN = 'LPAREN',
  RPAREN = 'RPAREN',
  COMMA = 'COMMA',
  COLON = 'COLON',
  EOF = 'EOF',
}

export interface Token {
  type: T;
  text: string;
  line: number;
  column: number;
  /** Index into the source string, for slicing partial input while streaming. */
  start: number;
}

const PUNCTUATION: Record<string, T> = {
  '=': T.EQUALS,
  '[': T.LBRACKET,
  ']': T.RBRACKET,
  '{': T.LBRACE,
  '}': T.RBRACE,
  '(': T.LPAREN,
  ')': T.RPAREN,
  ',': T.COMMA,
  ':': T.COLON,
};

const isIdentStart = (c: string) => /[A-Za-z_]/.test(c);
const isIdentPart = (c: string) => /[A-Za-z0-9_]/.test(c);
const isDigit = (c: string) => c >= '0' && c <= '9';
const isPathPart = (c: string) => /[A-Za-z0-9_/]/.test(c);

/**
 * Tokenizes Express source.
 *
 * @param src Express source text, already stripped of sentinel tags.
 * @param tolerant When true an unterminated construct at the very end of the
 *   input ends tokenization quietly instead of throwing. Streaming needs this:
 *   a half-received string is not a syntax error, it is a string that has not
 *   finished arriving.
 */
export function tokenize(src: string, tolerant = false): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  let line = 1;
  let lineStart = 0;

  const col = () => i - lineStart;

  const advanceOver = (text: string) => {
    for (let k = 0; k < text.length; k++) {
      if (text[k] === '\n') {
        line++;
        lineStart = i + k + 1;
      }
    }
    i += text.length;
  };

  const push = (type: T, text: string) => {
    tokens.push({ type, text, line, column: col(), start: i });
    advanceOver(text);
  };

  while (i < src.length) {
    const c = src[i]!;

    // Whitespace and semicolons are skipped by the grammar.
    if (c === ' ' || c === '\t' || c === '\r' || c === '\n' || c === ';') {
      if (c === '\n') {
        line++;
        lineStart = i + 1;
      }
      i++;
      continue;
    }

    // COMMENT : ('#' | '//') ~[\r\n]* -> skip
    if (c === '#' || (c === '/' && src[i + 1] === '/')) {
      while (i < src.length && src[i] !== '\n' && src[i] !== '\r') i++;
      continue;
    }

    // BLOCK_COMMENT : '/*' .*? '*/' -> skip
    if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      if (end === -1) {
        if (tolerant) break;
        throw new ExpressSyntaxError('unterminated block comment', line, col());
      }
      advanceOver(src.slice(i, end + 2));
      continue;
    }

    // Strings. Triple-quoted forms must be tried before single-quoted ones.
    const rawPrefix = c === 'r' || c === 'R';
    if (rawPrefix && src.startsWith('"""', i + 1)) {
      const end = src.indexOf('"""', i + 4);
      if (end === -1) {
        if (tolerant) break;
        throw new ExpressSyntaxError('unterminated raw triple-quoted string', line, col());
      }
      push(T.RAW_TRIPLE_STRING, src.slice(i, end + 3));
      continue;
    }
    if (src.startsWith('"""', i)) {
      const end = findStringEnd(src, i + 3, '"""');
      if (end === -1) {
        if (tolerant) break;
        throw new ExpressSyntaxError('unterminated triple-quoted string', line, col());
      }
      push(T.TRIPLE_STRING, src.slice(i, end + 3));
      continue;
    }
    if (rawPrefix && src[i + 1] === '"') {
      // RAW_STRING : [rR] '"' ~[\r\n"]* '"'
      let j = i + 2;
      while (j < src.length && src[j] !== '"' && src[j] !== '\n' && src[j] !== '\r') j++;
      if (j >= src.length || src[j] !== '"') {
        if (tolerant) break;
        throw new ExpressSyntaxError('unterminated raw string', line, col());
      }
      push(T.RAW_STRING, src.slice(i, j + 1));
      continue;
    }
    if (c === '"') {
      const end = findStringEnd(src, i + 1, '"');
      if (end === -1) {
        if (tolerant) break;
        throw new ExpressSyntaxError('unterminated string', line, col());
      }
      push(T.STANDARD_STRING, src.slice(i, end + 1));
      continue;
    }

    // PATH : '$' [a-zA-Z0-9_/]*
    if (c === '$') {
      let j = i + 1;
      while (j < src.length && isPathPart(src[j]!)) j++;
      push(T.PATH, src.slice(i, j));
      continue;
    }

    // CHECK : '?' [a-zA-Z_] [a-zA-Z0-9_]*
    if (c === '?') {
      let j = i + 1;
      if (j < src.length && isIdentStart(src[j]!)) {
        j++;
        while (j < src.length && isIdentPart(src[j]!)) j++;
        push(T.CHECK, src.slice(i, j));
        continue;
      }
      if (tolerant) break;
      throw new ExpressSyntaxError("'?' must be followed by a check name", line, col());
    }

    // NUMBER : '-'? [0-9]+ ('.' [0-9]+)?
    if (isDigit(c) || (c === '-' && i + 1 < src.length && isDigit(src[i + 1]!))) {
      let j = c === '-' ? i + 1 : i;
      while (j < src.length && isDigit(src[j]!)) j++;
      if (src[j] === '.' && j + 1 < src.length && isDigit(src[j + 1]!)) {
        j++;
        while (j < src.length && isDigit(src[j]!)) j++;
      }
      push(T.NUMBER, src.slice(i, j));
      continue;
    }

    // Identifiers, and the keyword-shaped tokens that outrank them on a tie.
    if (isIdentStart(c)) {
      let j = i;
      while (j < src.length && isIdentPart(src[j]!)) j++;
      const word = src.slice(i, j);
      if (word === 'true' || word === 'false') push(T.BOOLEAN, word);
      else if (word === 'null') push(T.NULL, word);
      else if (word === '_') push(T.UNDERSCORE, word);
      else push(T.IDENTIFIER, word);
      continue;
    }

    const punct = PUNCTUATION[c];
    if (punct) {
      push(punct, c);
      continue;
    }

    if (tolerant) break;
    throw new ExpressSyntaxError(`unexpected character '${c}'`, line, col());
  }

  tokens.push({ type: T.EOF, text: '', line, column: col(), start: i });
  return tokens;
}

/**
 * Finds the closing delimiter of a string, honouring `\\`-escapes.
 *
 * The grammar's string rules are `( '\\' . | ~'\\' )*?`, i.e. a backslash
 * always consumes the character after it — including a backslash — so `"a\\\\"`
 * terminates and `"a\\""` does not.
 */
function findStringEnd(src: string, from: number, delim: string): number {
  let j = from;
  while (j < src.length) {
    if (src[j] === '\\') {
      j += 2;
      continue;
    }
    if (src.startsWith(delim, j)) return j;
    j++;
  }
  return -1;
}

/** Resolves the escape sequences the reference visitor resolves, and no others. */
export function unescape(value: string): string {
  return value.replace(/\\([\s\S])/g, (seq, ch: string) => {
    switch (ch) {
      case 'n':
        return '\n';
      case 'r':
        return '\r';
      case 't':
        return '\t';
      case '\\':
        return '\\';
      case '"':
        return '"';
      default:
        return seq;
    }
  });
}

/** Strips quoting and applies escapes, per the token's specific string form. */
export function stringTokenValue(token: Token): string {
  switch (token.type) {
    case T.RAW_TRIPLE_STRING:
      return token.text.slice(4, -3);
    case T.RAW_STRING:
      return token.text.slice(2, -1);
    case T.TRIPLE_STRING:
      return unescape(token.text.slice(3, -3));
    case T.STANDARD_STRING:
      return unescape(token.text.slice(1, -1));
    default:
      return token.text;
  }
}

export const STRING_TOKENS = new Set([
  T.RAW_TRIPLE_STRING,
  T.TRIPLE_STRING,
  T.RAW_STRING,
  T.STANDARD_STRING,
]);
