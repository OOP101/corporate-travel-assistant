import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3001,
    proxy: {
      '/api/journey': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/journey/, ''),
      },
      '/api/planner': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/planner/, ''),
      },
      '/api/sense': {
        target: 'http://127.0.0.1:8003',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/sense/, ''),
      },
    },
  },
})
