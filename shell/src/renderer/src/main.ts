import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { addCollection } from '@iconify/vue'
import solarIcons from '@iconify-json/solar/icons.json'
import App from './App.vue'
import './styles/main.css'

addCollection(solarIcons)
createApp(App).use(createPinia()).mount('#app')
