import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { addCollection } from '@iconify/vue'
import solarIcons from '@iconify-json/solar/icons.json'
import DevApp from './DevApp.vue'
import './styles.css'

addCollection(solarIcons)
createApp(DevApp).use(createPinia()).mount('#app')
