import { resolve } from 'node:path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/main' },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/preload' },
  },
  renderer: {
    resolve: {
      alias: { '@renderer': resolve('src/renderer/src'), '@shared': resolve('src/shared') },
    },
    plugins: [vue()],
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: {
          index: resolve('src/renderer/index.html'),
          dev: resolve('src/renderer/dev.html'),
          // S51：日记编辑窗口（独立入口 —— 日记输入不走 AgentLoop）
          diary: resolve('src/renderer/diary.html'),
          detached: resolve('src/renderer/detached.html'),
        },
      },
    },
  },
})
