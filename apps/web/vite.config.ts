import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // The Worker serves this directory; source maps make a production bug
    // debuggable without a separate upload step.
    sourcemap: true,
  },
  server: {
    port: 5173,
    // In dev the app runs on Vite and the API on wrangler; in production both
    // are the same origin. Proxying keeps the client's fetch paths identical in
    // both, so there is no "is this dev?" branch in application code.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true },
      '/mcp': { target: 'http://127.0.0.1:8787', changeOrigin: true },
    },
  },
});
