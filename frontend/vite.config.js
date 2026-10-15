/// <reference types="vitest/config" />
/**
 * Storm Energy RTU frontend - Vite config.
 * Production: static build served by the storm-frontend nginx container behind the
 * reverse proxy; the app calls same-origin /api and /health (no host/port in code).
 * No PWA / service worker: API responses are never cached by the browser app.
 * `npm run dev` only: /api and /health are proxied to STORM_API_DEV_TARGET.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { readFileSync } from 'node:fs';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'));
const devApiTarget = process.env.STORM_API_DEV_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: devApiTarget, changeOrigin: true },
      '/health': { target: devApiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{js,jsx}'],
    setupFiles: ['./src/test/setup.js'],
  },
});
