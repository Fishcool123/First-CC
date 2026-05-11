/**
 * Vite 构建配置 — 认知增强系统 v3
 *
 * 架构说明：
 * - 前端：Vue 3 CDN 生产版（不构建），Jinja2 {% raw %} 模板
 * - Vite：CSS 压缩打包 + 静态资源优化
 * - 未来可迁移到 Vue 3 SFC + Vite 完整构建
 *
 * 使用方式：
 *   npm run build    — 打包 CSS 到 static/dist/
 *   npm run dev      — Vite 开发服务器（代理 API 到 Flask :5000）
 *   py app.py        — Flask 直接运行（开发模式）
 *   py desktop.py    — 桌面应用模式
 */
import { defineConfig } from 'vite'
import path from 'path'

export default defineConfig({
  root: path.resolve(__dirname, 'static'),
  base: '/static/dist/',
  build: {
    outDir: path.resolve(__dirname, 'static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'static/css/style.css'),
      },
    },
    cssCodeSplit: true,
    minify: 'esbuild',
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
    },
    fs: {
      allow: [path.resolve(__dirname)],
    },
  },
})
