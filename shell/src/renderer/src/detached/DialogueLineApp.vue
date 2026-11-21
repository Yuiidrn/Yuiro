<script setup lang="ts">
import { onMounted,onBeforeUnmount,ref } from 'vue'
import type { DialogueConnector } from '../../../shared/detachedUi'
const line=ref<DialogueConnector|null>(null)
let off:(()=>void)|undefined
document.title='Yuiro 对白曲线'
onMounted(()=>{off=window.yuiro.onDialogueLine(s=>line.value=s);window.yuiro.detachedReady()})
onBeforeUnmount(()=>off?.())
</script>
<template><svg v-if="line" :viewBox="`0 0 ${line.width} ${line.height}`" width="100%" height="100%" aria-hidden="true"><path :d="line.path" fill="none" :stroke="line.color" :stroke-width="line.stroke" stroke-linecap="round" /></svg></template>
<style>html[data-detached-kind='connector'],html[data-detached-kind='connector'] body,html[data-detached-kind='connector'] #app{margin:0;width:100%;height:100%;background:transparent;overflow:hidden;pointer-events:none}</style>
<style scoped>svg{display:block;pointer-events:none}</style>
