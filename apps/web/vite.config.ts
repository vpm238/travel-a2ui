import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // The Python server serves this directory; source maps make a production bug
    // debuggable without a separate upload step.
    sourcemap: true,
  },
  server: {
    port: 5173,
    // In dev the app runs on Vite and the API on uvicorn; in production both
    // are the same origin. Proxying keeps the client's fetch paths identical in
    // both, so there is no "is this dev?" branch in application code.
    //
    // `ws` carries the voice socket. The Host header is left as the browser
    // sent it, so the server's same-origin check on that socket passes.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', ws: true },
    },
  },
});
