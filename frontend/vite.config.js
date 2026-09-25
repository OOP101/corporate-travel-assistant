import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// v3 单服务架构：Agent 内核（services/core）单进程单端口 8001，
// 前端沿用 /api/<service> 代理约定，全部改写到内核根路径。
// （journey/planner/sense 三个代理名保留，兼容前端既有 fetch 调用，不再区分前缀）
const CORE = 'http://127.0.0.1:8001'

const targets = { journey: CORE, planner: CORE, sense: CORE }
const prefixes = { journey: '', planner: '', sense: '' }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3001,
    proxy: Object.fromEntries(
      ['journey', 'planner', 'sense'].map((svc) => [
        `/api/${svc}`,
        {
          target: targets[svc],
          changeOrigin: true,
          rewrite: (path) => path.replace(new RegExp(`^/api/${svc}`), prefixes[svc]),
        },
      ])
    ),
  },
})
