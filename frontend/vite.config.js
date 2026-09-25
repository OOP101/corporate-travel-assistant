import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// v3 单服务架构：Agent 内核（services/core）单进程单端口 8001。
// 前端沿用 /api/<service> 代理约定（journey / planner 两个历史前缀），
// 两者都改写到内核根路径 —— 前缀只用于兼容既有 fetch 调用，后端不再区分。
//
// ⚠️ 不要为已删除的服务补代理名：v3 切型移除了 sense-engine，曾有 `sense: CORE`
// 这条"兼容前端既有调用"的后门，结果 /api/sense/** 被静默转发到内核根路径
// （/monitor/status → 404），整页失败却看不出是代理造成的。前端已一并下线，
// 新增代理名前请先确认 services/ 下确有对应路由（scripts/check_api_contract.py）。
const CORE = process.env.VITE_CORE_URL || 'http://127.0.0.1:8001'

const targets = { journey: CORE, planner: CORE }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.VITE_PORT) || 3001,
    proxy: Object.fromEntries(
      Object.entries(targets).map(([svc, target]) => [
        `/api/${svc}`,
        {
          target,
          changeOrigin: true,
          // 边界限定 `(?=/|$)`：否则 /api/journeyfoo 也会被当成 /api/journey 重写
          rewrite: (path) => path.replace(new RegExp(`^/api/${svc}(?=/|$)`), ''),
        },
      ])
    ),
  },
})
