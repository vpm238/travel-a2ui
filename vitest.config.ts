import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, type Plugin } from 'vitest/config';

const root = dirname(fileURLToPath(import.meta.url));

/**
 * Loads the Worker's text imports as text.
 *
 * The Worker does this through a `rules` entry in `wrangler.jsonc`, so a
 * generated `SKILL.md` and the MCP view's shell are the same artifacts at test
 * time as at run time. Without it the tests would be checking a mock of the
 * thing they exist to check — and Vite would try to process the shell as an
 * HTML *page*, which it is not.
 *
 * The `.html` case is scoped to that one file so it cannot swallow a real
 * entry-point HTML file.
 */
function workerTextImports(): Plugin {
  return {
    name: 'worker-text-imports',
    enforce: 'pre',
    load(id) {
      const path = id.split('?')[0]!;
      const isSkill = path.endsWith('.md');
      const isView = path.endsWith('mcp-view/shell.html');
      if (!isSkill && !isView) return null;
      return `export default ${JSON.stringify(readFileSync(path, 'utf8'))};`;
    },
  };
}

export default defineConfig({
  plugins: [workerTextImports()],
  resolve: {
    alias: {
      // Test the source, not the last build of it.
      '@travel-a2ui/express': resolve(root, 'packages/express/src/index.ts'),
      '@travel-a2ui/renderer': resolve(root, 'packages/renderer/src/index.ts'),
    },
  },
  test: {
    include: ['packages/*/test/**/*.test.ts', 'apps/*/test/**/*.test.ts'],
    environment: 'node',
    testTimeout: 20_000,
  },
});
