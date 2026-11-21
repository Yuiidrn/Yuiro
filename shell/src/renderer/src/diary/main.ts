import { createApp } from 'vue'
import { addCollection } from '@iconify/vue'
import solarIcons from '@iconify-json/solar/icons.json'
import DiaryApp from './DiaryApp.vue'
import '../styles/main.css'

// 与桌宠窗口同一套本地图标集（离线可用，不依赖 Iconify API）
addCollection(solarIcons)
createApp(DiaryApp).mount('#app')
