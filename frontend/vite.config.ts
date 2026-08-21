import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import * as path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    }
  },
  server: {
    port: 3000,
    open: true,
    /**
     * Dev-only proxy to the staging API.
     *
     * Set `VITE_API_URL=/api/v1` in `.env.local` and the browser calls its OWN
     * origin, so CORS never applies and staging needs no config change. That
     * matters: `config.py` deliberately RAISES if CORS_ORIGINS contains
     * 'localhost' outside development, and CLAUDE.md documents how easily
     * staging's .env gets clobbered. Loosening a security rail for local
     * convenience is the wrong trade; a proxy costs nothing.
     *
     * Why it exists: an empty local DB renders every page as an empty state,
     * so UI work could not be seen before shipping. Four attempts at the crew
     * row shipped unviewed because of this.
     *
     * WRITES GO TO STAGING. Clicking "Mark Present" here marks someone present
     * in staging data. Acceptable for seed data; know it before clicking.
     *
     * Dev server only — `vite preview` serves static files and does not proxy.
     */
    proxy: {
      '/api': {
        target: 'https://api-staging.asheflow.com',
        changeOrigin: true,
        secure: true,
      },
    },
  }
})
