/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Master backend (API + OAuth routes)
      '/api': { target: 'http://127.0.0.1:8436', changeOrigin: true, secure: false },
      '/oauth-callback': { target: 'http://127.0.0.1:8436', changeOrigin: true, secure: false },
      '/account': { target: 'http://127.0.0.1:8436', changeOrigin: true, secure: false },
      '/admin': { target: 'http://127.0.0.1:8436', changeOrigin: true, secure: false }
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
