import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    // three 生态单包体积必然超默认阈值，属预期；调高消除噪音警告
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // three 生态单独成包：与业务代码分离，改业务不动三方缓存
        manualChunks: {
          three: ['three', '@react-three/fiber', '@react-three/drei'],
        },
      },
    },
  },
  server: {
    port: 5178,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8020',
    },
  },
})
