import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import process from 'node:process';

const apiTarget = process.env.ISOSAFE_API_PROXY_TARGET || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
      '/media': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
  },
});
