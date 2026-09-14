import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vitest/config';

const root = dirname(fileURLToPath(import.meta.url));

/**
 * Loads a generated `SKILL.md` as text.
 *
 * The Python server reads these from disk at runtime, so the skill a test
 * checks is the same artifact the model is given. Without it the tests would be
 * checking a mock of the thing they exist to check.
 */
function skillTextImports(): Plugin {
  return {
    name: 'skill-text-imports',
    enforce: 'pre',
    load(id) {
      const path = id.split('?')[0]!;
      if (!path.endsWith('.md')) return null;
      return `export default ${JSON.stringify(readFileSync(path, 'utf8'))};`;
    },
  };
}

export default defineConfig({
  plugins: [skillTextImports()],
  resolve: {
    alias: {
      // Test the source, not the last build of it.
      '@travel-a2ui/express': resolve(root, 'packages/express/src/index.ts'),
      '@travel-a2ui/renderer': resolve(root, 'renderers/react/src/index.ts'),
    },
  },
  test: {
    include: [
      'packages/*/test/**/*.test.ts',
      'renderers/*/test/**/*.test.ts',
      'apps/*/test/**/*.test.ts',
    ],
    environment: 'node',
    testTimeout: 20_000,
  },
});
