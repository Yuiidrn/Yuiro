<script setup lang="ts">
import { useConfigStore } from '../stores/config'
const store = useConfigStore()
async function change(event: Event): Promise<void> {
  const selected = (event.target as HTMLSelectElement).value
  if (selected === store.character?.active_id) return
  if (store.hasDraftChanges && !window.confirm('当前页面有未保存的编辑。切换角色会丢弃这些草稿并停止旧输出，继续？')) {
    (event.target as HTMLSelectElement).value = store.character?.active_id ?? ''
    return
  }
  await store.switchCharacter(selected)
}
</script>

<template>
  <label v-if="store.character" class="character-picker">
    当前角色
    <select :value="store.character.active_id" :disabled="store.loading || store.saving || store.switching" @change="change">
      <option v-for="item in store.character.items" :key="item.id" :value="item.id">{{ item.label }}</option>
    </select>
    <small>{{ store.switching ? '正在安全切换…' : '整套切换并停止旧输出 · 设备与权限共用' }}</small>
    <span v-if="store.saveError" role="alert">{{ store.saveError }}</span>
  </label>
</template>

<style scoped>
.character-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13px; }
select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: inherit; }
small { color: var(--text-soft); }
[role=alert] { color: #b33; max-width: 300px; }
</style>
