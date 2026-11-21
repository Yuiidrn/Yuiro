<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

const key = ref('')
const configured = ref(false)
const busy = ref(false)
const message = ref('')
async function run(action: 'load' | 'save' | 'clear'): Promise<void> {
  busy.value = true
  message.value = ''
  try {
    const result = action === 'save' ? await api.setFishKey(key.value)
      : action === 'clear' ? await api.clearFishKey() : await api.getFishKey()
    configured.value = result.status === 'set'
    key.value = ''
    message.value = configured.value ? '已保存到本机安全存储' : '未配置 Fish Key'
  } catch {
    message.value = '操作失败，请检查引擎连接、鉴权或本机安全存储'
  } finally {
    busy.value = false
  }
}
onMounted(() => void run('load'))
</script>

<template>
  <section class="fish-key-settings">
    <h4>Fish API Key</h4>
    <p>凭证由各角色共用，仅保存在本机安全存储；音色与合成参数按角色独立保存。</p>
    <div class="fish-key-form">
    <input v-model="key" type="password" autocomplete="off" placeholder="输入新的 Fish API Key" :disabled="busy" />
    <button class="btn" :disabled="busy || !key.trim()" @click="run('save')">安全保存</button>
    <button class="btn" :disabled="busy || !configured" @click="run('clear')">清除密钥</button>
    </div>
    <p role="status">{{ message }}</p>
  </section>
</template>

<style scoped>
.fish-key-settings { margin: 0 18px 16px; padding-top: 14px; border-top: 1px solid var(--border); }
h4 { margin: 0 0 6px; font-size: 13px; }
p { margin: 6px 0; color: var(--muted); font-size: 12px; }
.fish-key-form { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
input { flex: 1; min-width: 180px; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--input); color: var(--text); }
</style>
