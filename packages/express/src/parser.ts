/**
 * Recursive-descent parser for A2UI Express, transcribed from `Express.g4`.
 *
 * The grammar is LL(2) at worst — the only lookahead needed is "does this
 * identifier or path start an assignment?" and "does this identifier start a
 * call?" — so a hand-written parser is both smaller and faster than a generated
 * one, and it drops the ANTLR runtime from the Worker bundle.
 *
 * Partial input matters as much as complete input here: the model streams
 * Express tokens, and we want to render the surface as it arrives. So the
 * parser collects errors rather than throwing on the first one, and (like the
 * reference visitor) drops statements from the first error's line onward. A
 * half-written last line is simply not yet a statement.
 */

import { ExpressSyntaxError } from './errors.js';
import { STRING_TOKENS, T, type Token, stringTokenValue, tokenize } from './lexer.js';
import type { AstCall, AstMap, AstStatement, AstValue } from './ast.js';

export interface ParseResult {
  statements: AstStatement[];
  /** Syntax errors in source order. Empty on a clean parse. */
  errors: ExpressSyntaxError[];
}

export interface ParseOptions {
  /**
   * When false, the input is treated as a prefix of a longer document: a
   * truncated tail is dropped instead of reported. Set it true for the final
   * parse so real syntax errors surface.
   */
  isFinal?: boolean;
}

class Parser {
  private pos = 0;
  readonly errors: ExpressSyntaxError[] = [];

  constructor(private readonly tokens: Token[]) {}

  private peek(offset = 0): Token {
    return this.tokens[Math.min(this.pos + offset, this.tokens.length - 1)]!;
  }

  private at(type: T): boolean {
    return this.peek().type === type;
  }

  private next(): Token {
    const token = this.peek();
    if (token.type !== T.EOF) this.pos++;
    return token;
  }

  private expect(type: T, what: string): Token {
    if (!this.at(type)) {
      const token = this.peek();
      throw new ExpressSyntaxError(
        `expected ${what} but found ${token.type === T.EOF ? 'end of input' : `'${token.text}'`}`,
        token.line,
        token.column,
      );
    }
    return this.next();
  }

  parseProgram(): AstStatement[] {
    const statements: AstStatement[] = [];
    while (!this.at(T.EOF)) {
      const before = this.pos;
      try {
        statements.push(this.parseStatement());
      } catch (error) {
        if (error instanceof ExpressSyntaxError) {
          this.errors.push(error);
          // One error is enough: everything after it is unreliable, and the
          // reference implementation truncates at the first error's line too.
          break;
        }
        throw error;
      }
      if (this.pos === before) {
        // Defensive: never spin on a token no rule consumed.
        const token = this.peek();
        this.errors.push(
          new ExpressSyntaxError(`unexpected '${token.text}'`, token.line, token.column),
        );
        break;
      }
    }
    return statements;
  }

  /** statement : assignment | expression ; */
  private parseStatement(): AstStatement {
    const start = this.peek();
    const assignable = start.type === T.IDENTIFIER || start.type === T.PATH;
    if (assignable && this.peek(1).type === T.EQUALS) {
      const target = this.next().text;
      this.next(); // '='
      const value = this.parseExpression();
      return { kind: 'ASSIGN', target, value, line: start.line };
    }
    return { kind: 'EXPR', value: this.parseExpression(), line: start.line };
  }

  /** expression : array | map | path | check | call | variable | literal ; */
  private parseExpression(): AstValue {
    const token = this.peek();
    switch (token.type) {
      case T.LBRACKET:
        return this.parseArray();
      case T.LBRACE:
        return this.parseMap();
      case T.PATH:
        this.next();
        return { path: token.text.slice(1) };
      case T.CHECK:
        return this.parseCheck();
      case T.IDENTIFIER:
        if (this.peek(1).type === T.LPAREN) return this.parseCall();
        this.next();
        return { variable: token.text };
      case T.UNDERSCORE:
        this.next();
        return { skipped: true };
      case T.NUMBER:
        this.next();
        return Number(token.text);
      case T.BOOLEAN:
        this.next();
        return token.text === 'true';
      case T.NULL:
        this.next();
        return null;
      default:
        if (STRING_TOKENS.has(token.type)) {
          this.next();
          return stringTokenValue(token);
        }
        throw new ExpressSyntaxError(
          `expected a value but found ${token.type === T.EOF ? 'end of input' : `'${token.text}'`}`,
          token.line,
          token.column,
        );
    }
  }

  /** array : '[' (expression (',' expression)* ','?)? ']' ; */
  private parseArray(): AstValue[] {
    this.expect(T.LBRACKET, "'['");
    const items: AstValue[] = [];
    while (!this.at(T.RBRACKET)) {
      items.push(this.parseExpression());
      if (this.at(T.COMMA)) this.next();
      else break;
    }
    this.expect(T.RBRACKET, "']'");
    return items;
  }

  /** map : '{' (map_entry (',' map_entry)* ','?)? '}' ; */
  private parseMap(): AstMap {
    this.expect(T.LBRACE, "'{'");
    const map: AstMap = {};
    while (!this.at(T.RBRACE)) {
      const keyToken = this.peek();
      let key: string;
      if (keyToken.type === T.IDENTIFIER) key = this.next().text;
      else if (STRING_TOKENS.has(keyToken.type)) key = stringTokenValue(this.next());
      else
        throw new ExpressSyntaxError(
          `expected a map key but found '${keyToken.text}'`,
          keyToken.line,
          keyToken.column,
        );
      this.expect(T.COLON, "':'");
      map[key] = this.parseExpression();
      if (this.at(T.COMMA)) this.next();
      else break;
    }
    this.expect(T.RBRACE, "'}'");
    return map;
  }

  /** check : CHECK ('(' (expression (',' expression)* ','?)? ')')? ; */
  private parseCheck(): AstValue {
    const token = this.expect(T.CHECK, 'a check rule');
    const args: AstValue[] = [];
    if (this.at(T.LPAREN)) {
      this.next();
      while (!this.at(T.RPAREN)) {
        args.push(this.parseExpression());
        if (this.at(T.COMMA)) this.next();
        else break;
      }
      this.expect(T.RPAREN, "')'");
    }
    return { check: token.text.slice(1), args };
  }

  /** call : identifier '(' (arg (',' arg)* ','?)? ')' ; */
  private parseCall(): AstCall {
    const name = this.expect(T.IDENTIFIER, 'a component or function name').text;
    this.expect(T.LPAREN, "'('");
    const args: AstValue[] = [];
    const kwargs: Record<string, AstValue> = {};
    let hasKwargs = false;

    while (!this.at(T.RPAREN)) {
      // arg : named_arg | expression ;  named_arg : identifier '=' expression ;
      if (this.at(T.IDENTIFIER) && this.peek(1).type === T.EQUALS) {
        const key = this.next().text;
        this.next(); // '='
        kwargs[key] = this.parseExpression();
        hasKwargs = true;
      } else {
        args.push(this.parseExpression());
      }
      if (this.at(T.COMMA)) this.next();
      else break;
    }
    this.expect(T.RPAREN, "')'");

    const node: AstCall = { call: name, args };
    if (hasKwargs) node.kwargs = kwargs;
    return node;
  }
}

/** Parses Express source into statements, collecting rather than throwing errors. */
export function parse(source: string, options: ParseOptions = {}): ParseResult {
  const isFinal = options.isFinal ?? true;

  let tokens: Token[];
  const lexErrors: ExpressSyntaxError[] = [];
  try {
    tokens = tokenize(source, !isFinal);
  } catch (error) {
    if (error instanceof ExpressSyntaxError && isFinal) return { statements: [], errors: [error] };
    if (error instanceof ExpressSyntaxError) {
      lexErrors.push(error);
      tokens = tokenize(source, true);
    } else throw error;
  }

  const parser = new Parser(tokens);
  const statements = parser.parseProgram();
  const errors = [...lexErrors, ...parser.errors];

  if (errors.length === 0) return { statements, errors };

  // Match the reference visitor: keep only statements that start before the
  // first error's line. A statement straddling the error is not trustworthy.
  const firstErrorLine = errors[0]!.line;
  return { statements: statements.filter((s) => s.line < firstErrorLine), errors };
}
