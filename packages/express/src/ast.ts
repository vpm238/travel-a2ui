/**
 * AST node shapes.
 *
 * These match the plain-data structures the reference visitor produces, key for
 * key, because the compiler below is a port of the reference compiler and reads
 * them by the same names. Keeping the AST identical is what makes the parity
 * tests against the Python implementation meaningful.
 */

export type AstValue =
  | string
  | number
  | boolean
  | null
  | AstValue[]
  | AstPath
  | AstVariable
  | AstSkipped
  | AstCheck
  | AstCall
  | AstMap;

/** `$/trip/adults` → `{ path: "/trip/adults" }` */
export interface AstPath {
  path: string;
}

/** A bare identifier used as a value → `{ variable: "header" }` */
export interface AstVariable {
  variable: string;
}

/** The `_` positional placeholder → `{ skipped: true }` */
export interface AstSkipped {
  skipped: true;
}

/** `?regex("^[0-9]+$")` → `{ check: "regex", args: [...] }` */
export interface AstCheck {
  check: string;
  args: AstValue[];
}

/** `Button("Go", action=Event("go"))` */
export interface AstCall {
  call: string;
  args: AstValue[];
  kwargs?: Record<string, AstValue>;
}

/** `{ title: "Overview", child: contentCol }` */
export interface AstMap {
  [key: string]: AstValue;
}

export type AstStatement =
  | { kind: 'ASSIGN'; target: string; value: AstValue; line: number }
  | { kind: 'EXPR'; value: AstValue; line: number };

export function isPath(v: unknown): v is AstPath {
  return typeof v === 'object' && v !== null && 'path' in (v as object);
}

export function isVariable(v: unknown): v is AstVariable {
  return typeof v === 'object' && v !== null && 'variable' in (v as object);
}

export function isSkipped(v: unknown): v is AstSkipped {
  return typeof v === 'object' && v !== null && (v as AstSkipped).skipped === true;
}

export function isCheck(v: unknown): v is AstCheck {
  return typeof v === 'object' && v !== null && 'check' in (v as object);
}

export function isCall(v: unknown): v is AstCall {
  return typeof v === 'object' && v !== null && 'call' in (v as object);
}

/** True for a check node, or a list in which every element is one. */
export function isCheckExpression(v: unknown): boolean {
  if (isCheck(v)) return true;
  if (Array.isArray(v) && v.length > 0) return v.every(isCheckExpression);
  return false;
}
