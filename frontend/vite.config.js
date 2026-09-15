import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// 默认「单体模式」：三个业务服务同进程同端口（services/gateway 装配），前端只代理 8001。
// 微服务模式（launcher.py start micro / CJH_MODE=micro）下自动回退为三端口直连，便于架构演示。
const micro = (process.env.CJH_MODE || '').toLowerCase() === 'micro'
const GATEWAY = 'http://127.0.0.1:8001'

const targets = micro
  ? { journey: 'http://127.0.0.1:8001', planner: 'http://127.0.0.1:8002', sense: 'http://127.0.0.1:8003' }
  : { journey: GATEWAY, planner: GATEWAY, sense: GATEWAY }

// 单体模式下 planner/sense 挂在网关前缀下，微服务模式下各自在根路径
const prefixes = micro
  ? { journey: '', planner: '', sense: '' }
  : { journey: '', planner: '/planner', sense: '/sense' }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3001,
    // 统一按 /api/<service> 代理：目标端口与路径前缀由运行模式决定
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
