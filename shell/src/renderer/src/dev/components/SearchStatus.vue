<script setup lang="ts">
/**
 * 联网检索的**引擎侧生效状态**（S51）。
 *
 * 为什么必须有它：下面的配置卡显示的是**草稿**（改了没保存就是"未保存"），
 * 而聊天坞的联网按钮判断的是**引擎的真实状态**。两者不一致时，用户看到的是
 * "我明明把开关打开了，点按钮还说已关闭"（实测原话）。
 *
 * 这里把引擎的答案直接摆出来：总开关是否**真的**为 true、key 是否**真的**
 * 配上了、当前到底可不可用。一眼就能区分"没保存"与"真坏了"。
 */
import { onMounted, ref } from 'vue'
import { Icon } from '@iconify/vue'
import { api, type SearchStatusView } from '../api'

const st = ref<SearchStatusView | null>(null)
const error = ref('')
const loading = ref(false)
const query = ref('DeepSeek 官方 API 文档')
const testing = ref(false)
const result = ref<Awaited<ReturnType<typeof api.testSearch>> | null>(null)
async function test(): Promise<void> {
  testing.value = true
  result.value = null
  error.value = ''
  try { result.value = await api.testSearch(query.value) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { testing.value = false }
}
function openSource(url: string): void { void window.yuiro?.openExternal(url) }

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    st.value = await api.getSearchStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<template>
  <div class="ss-card" :class="st?.available ? 'ok' : 'warn'">
    <div class="ss-head">
      <Icon :icon="st?.available ? 'solar:checklist-minimalistic-bold' : 'solar:info-circle-bold'" width="15" />
      <span class="ss-title">
        {{ st?.available ? '引擎侧已生效：联网检索可用' : '引擎侧尚未生效' }}
      </span>
      <button class="ss-refresh" :disabled="loading" @click="refresh">
        <Icon icon="solar:refresh-bold" width="12" />
        {{ loading ? '查询中…' : '刷新' }}
      </button>
    </div>

    <p v-if="error" class="ss-err">读不到状态：{{ error }}</p>
    <template v-else-if="st">
      <p v-if="!st.available" class="ss-hint">{{ st.hint || '条件未满足' }}</p>
      <div class="ss-rows">
        <span class="ss-row">
          <span class="ss-label">总开关（引擎侧）</span>
          <span class="ss-val" :class="st.enabled ? 'yes' : 'no'">{{ st.enabled ? '已开启' : '已关闭' }}</span>
        </span>
        <span class="ss-row">
          <span class="ss-label">搜索服务</span>
          <span class="ss-val">{{ st.provider }}</span>
        </span>
        <span class="ss-row">
          <span class="ss-label">模型可见性</span>
          <span class="ss-val" :class="st.available ? 'yes' : 'no'">
            {{ st.available ? 'web_search 已注入' : '未注入（模型看不到它）' }}
          </span>
        </span>
      </div>
      <p class="ss-foot">
        若这里显示「已关闭」而上面的开关是打开的 —— 说明**还没保存**（配置卡只改了草稿）。
      </p>
    </template>
    <div class="ss-test">
      <label>DeepSeek 搜索联调（使用已保存配置，查询词会发送给 DeepSeek）</label>
      <input v-model="query" maxlength="128" :disabled="testing" aria-label="搜索测试关键词" />
      <button class="btn" :disabled="testing || !st?.available || !query.trim()" @click="test">{{ testing ? '搜索中…' : '测试搜索' }}</button>
      <p v-if="result">{{ result.note || `返回 ${result.count ?? 0} 条来源` }} · {{ result.latency_ms }} ms</p>
      <div v-for="item in result?.results" :key="item.url">
        <button class="btn" @click="openSource(item.url)">{{ item.title || item.url }}</button>
        <p>{{ item.published_at }} {{ item.snippet }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ss-test { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.ss-test input { padding: 8px; border: 1px solid var(--border); border-radius: 6px; color: var(--text); background: var(--input); }
.ss-card {
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  border: 1px solid var(--border-soft, rgba(148, 163, 184, 0.2));
  background: var(--card-bg, rgba(148, 163, 184, 0.05));
  font-size: 12.5px;
}
.ss-card.ok { border-color: rgba(96, 180, 120, 0.45); background: rgba(96, 180, 120, 0.08); }
.ss-card.warn { border-color: rgba(214, 158, 92, 0.45); background: rgba(214, 158, 92, 0.08); }
.ss-head { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; }
.ss-title { font-weight: 600; flex: 1; }
.ss-refresh {
  display: flex; align-items: center; gap: 4px;
  background: transparent; color: var(--text-soft, #94a3b8);
  border: 1px solid var(--border-soft, rgba(148, 163, 184, 0.25));
  border-radius: 6px; padding: 3px 8px; cursor: pointer; font-size: 11.5px;
}
.ss-refresh:disabled { opacity: 0.5; cursor: default; }
.ss-hint { margin: 0 0 8px; color: var(--text, #e8e2d8); }
.ss-err { margin: 0; color: var(--dot-err, #c47b7b); }
.ss-rows { display: flex; flex-direction: column; gap: 3px; }
.ss-row { display: flex; justify-content: space-between; gap: 10px; }
.ss-label { color: var(--text-soft, #94a3b8); }
.ss-val.yes { color: var(--dot-ok, #7bc47f); }
.ss-val.no { color: var(--dot-err, #c47b7b); }
.ss-foot { margin: 8px 0 0; color: var(--text-soft, #94a3b8); font-size: 11.5px; line-height: 1.6; }
</style>
