import { createApp } from 'vue'
import DetachedApp from './DetachedApp.vue'
import DialogueLineApp from './DialogueLineApp.vue'
const kind=new URLSearchParams(location.search).get('kind')
document.documentElement.dataset.detachedKind=kind||'speech'
createApp(kind==='connector'?DialogueLineApp:DetachedApp).mount('#app')
