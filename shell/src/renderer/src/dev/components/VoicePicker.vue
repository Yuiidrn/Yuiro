<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useConfigStore } from '../stores/config'

/**
 * 音色选择（调试台「声音」页）
 *
 * 原本挂在「性格」页 —— 但它决定的是嗓音，与 tts / asr / vad 同属声音链路，故移到这里。
 * 写入引擎配置 persona.voice；用原生 datalist 兼顾「选预设」与「自由输入」。
 */
const store = useConfigStore()

/** edge-tts 常用中文音色预设（也可直接输入任意音色名）。 */
const VOICE_PRESETS = [
  'zh-CN-XiaoxiaoNeural',
  'zh-CN-XiaoyiNeural',
  'zh-CN-YunjianNeural',
  'zh-CN-YunxiNeural',
  'zh-CN-YunxiaNeural',
  'zh-CN-YunyangNeural',
  'zh-CN-liaoning-XiaobeiNeural',
  'zh-TW-HsiaoChenNeural',
  'zh-HK-HiuMaanNeural',
]

const remote = computed(() => store.sections.persona ?? {})

const value = ref('')
const dirty = ref(false)
const applying = ref(false)
const saved = ref(false)
const error = ref('')

watch(remote, () => {
  value.value = String(remote.value.voice ?? '')
  dirty.value = false
  saved.value = false
}, { immediate: true, deep: true })

function markDirty(): void {
  dirty.value = true
  saved.value = false
}

async function apply(): Promise<void> {
  applying.value = true
  error.value = ''
  try {
    await store.applySection('persona', { voice: value.value })
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div class="bubble voice-picker">
    <div class="vp-head">
      <div>
        <h3 class="vp-title">音色</h3>
        <p class="hint">桌宠说话的嗓音。edge-tts 用音色名（如 zh-CN-XiaoxiaoNeural），可下拉选择或直接输入。</p>
      </div>
      <span v-if="saved" class="pill pill-ok">已保存</span>
      <span v-else-if="dirty" class="pill pill-warn">未保存</span>
    </div>

    <div class="vp-row">
      <input
        v-model="value"
        class="vp-input"
        list="yuiro-voice-presets"
        placeholder="zh-CN-XiaoxiaoNeural"
        @input="markDirty" />
      <datalist id="yuiro-voice-presets">
        <option v-for="v in VOICE_PRESETS" :key="v" :value="v" />
      </datalist>
      <button class="btn btn-primary" :disabled="!dirty || applying" @click="apply">
        {{ applying ? '保存中…' : '保存' }}
      </button>
    </div>

    <p v-if="error" class="vp-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.voice-picker { display: flex; flex-direction: column; gap: 10px; }
.vp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.vp-title { margin: 0 0 4px; font-size: 14px; font-weight: 600; }

/* 注意：外层 .voice-picker 是纵向 flex，这里绝不能再写 flex-basis（260px 会被当成
   行高，把单行输入框撑出一片空白——就是"音色卡空白过大"的根因），保持内容高度即可。 */
.vp-row { display: flex; align-items: center; gap: 10px; }
.vp-input {
  flex: 1;
  padding: 8px 11px; border-radius: var(--radius-sm);
  border: 1px solid var(--border); background: var(--input);
  color: var(--text); font-size: 13px; outline: none; font-family: inherit;
}
.vp-input:focus { border-color: var(--accent); }
.vp-error { margin: 0; font-size: 12px; color: var(--err); }
</style>
