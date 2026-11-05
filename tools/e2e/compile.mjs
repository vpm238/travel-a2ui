/**
 * Compiles canned Express with the A2UI SDK, through `compile.py`.
 *
 * One Python process per call, so a suite compiles all its fixtures at once.
 * `PYTHON` picks the interpreter (a venv's, usually), as the other suites do.
 */

import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** `[{surfaceId, source, partialAt?}]` → `[{messages, partial}]`, in order. */
export function compileAll(fixtures) {
  const output = execFileSync(process.env.PYTHON ?? 'python3', ['tools/e2e/compile.py'], {
    cwd: root,
    input: JSON.stringify(fixtures),
    maxBuffer: 32 * 1024 * 1024,
  });
  return JSON.parse(String(output));
}
