import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 测试独立配置：不与 vite.config.ts（dev/build）混用。
// jsdom 提供 DOM；url 指定有效 origin 以启用 localStorage（jsdom 30 需要）。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    environmentOptions: {
      jsdom: {
        url: 'http://localhost:5178/',
      },
    },
    setupFiles: ['src/test/setup.ts'],
  },
})
