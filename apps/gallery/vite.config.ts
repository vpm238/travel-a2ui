import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    rollupOptions: {
      output: { entryFileNames: 'app.js', assetFileNames: 'app.[ext]', inlineDynamicImports: true },
    },
  },
});
