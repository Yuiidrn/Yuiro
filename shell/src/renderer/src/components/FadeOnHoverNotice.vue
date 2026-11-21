<script setup lang="ts">
import { ref } from 'vue'
import { Icon } from '@iconify/vue'

const emit = defineEmits<{ (e: 'confirm', dontShow: boolean): void; (e: 'cancel'): void }>()
const dontShow = ref(false)
</script>

<template>
  <div class="fade-notice-mask">
    <div class="fade-notice-card">
      <div class="fade-notice-title">
        <Icon icon="solar:eye-broken" class="fade-notice-icon" />
        <span>开启「悬停渐隐」</span>
      </div>
      <p class="fade-notice-body">
        开启后，鼠标移动到桌宠窗口上时，整窗将<strong>不再拦截点击</strong>，
        你可直接操作被桌宠挡住的桌面内容。
      </p>
      <ul class="fade-notice-list">
        <li>开启后桌宠进入<strong>免打扰</strong>：鼠标一进入窗口，整窗 UI（模型 + 功能泡）就淡出，不再拦截点击。</li>
        <li>鼠标移出窗口或贴住窗口边缘时，UI 立即恢复显示，可正常拖动 / 点击。</li>
        <li>
          <strong>开启期间无法按住模型本体拖动</strong>（穿透时拖拽事件不送达）；
          移动桌宠请改用窗口边缘拖动或托盘菜单。
        </li>
        <li>
          想关闭时：<strong>右键托盘图标 →「关闭悬停渐隐」</strong>即可恢复可交互；
          或在开发者调试台「外观」页关闭。
        </li>
      </ul>
      <label class="fade-notice-check">
        <input type="checkbox" v-model="dontShow" />
        <span>不再显示此提示</span>
      </label>
      <div class="fade-notice-actions">
        <button class="fade-notice-btn ghost" @click="emit('cancel')">取消</button>
        <button class="fade-notice-btn primary" @click="emit('confirm', dontShow)">确认开启</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-notice-mask {
  position: absolute;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}
.fade-notice-card {
  width: 300px;
  max-width: 86%;
  padding: 18px 18px 16px;
  border-radius: 14px;
  background: #1c1d22;
  color: #e8e8ec;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 13px;
  line-height: 1.6;
}
.fade-notice-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}
.fade-notice-icon { font-size: 18px; color: #ffb454; }
.fade-notice-body { margin: 0 0 8px; color: #c8c8d0; }
.fade-notice-list { margin: 0 0 10px; padding-left: 18px; color: #c8c8d0; }
.fade-notice-list li { margin-bottom: 4px; }
.fade-notice-list strong { color: #ffd9a0; }
.fade-notice-check {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  color: #b8b8c0;
  cursor: pointer;
}
.fade-notice-actions { display: flex; gap: 8px; justify-content: flex-end; }
.fade-notice-btn {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
}
.fade-notice-btn.ghost { background: transparent; border-color: rgba(255, 255, 255, 0.18); color: #d0d0d8; }
.fade-notice-btn.primary { background: #ffb454; color: #1c1d22; font-weight: 600; }
.fade-notice-btn.primary:hover { background: #ffc46e; }
</style>
