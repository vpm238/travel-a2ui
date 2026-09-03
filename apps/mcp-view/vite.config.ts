import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // One chunk, no code splitting, no hashed names: the shell in
    // `scripts/inline.mjs` points at exactly one script and one stylesheet, and
    // the Worker serves them under those names.
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: {
        // A classic script, not a module. The host renders this document in a
        // sandboxed iframe with an opaque origin, and a module script is fetched
        // in CORS mode — a classic one is not. Same bytes, one fewer thing that
        // can silently fail in someone else's sandbox.
        format: 'iife',
        entryFileNames: 'app.js',
        assetFileNames: 'app.[ext]',
        inlineDynamicImports: true,
      },
    },
  },
});
