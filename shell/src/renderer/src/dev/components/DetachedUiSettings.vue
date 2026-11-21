<script setup lang="ts">
import { computed, ref } from 'vue'
import { useUiAppearance } from '../../composables/useUiAppearance'
import { useSpeechBubblePref } from '../../composables/useSpeechBubblePref'
import { useResultCardPref } from '../../composables/useResultCardPref'
import type { PanelKind } from '../../../../shared/uiAppearance'
import { UI_APPEARANCE_DEFAULTS } from '../../../../shared/uiAppearance'
import UiRange from './UiRange.vue'
import ReplySurface from '../../components/ReplySurface.vue'
import ResultCard from '../../components/ResultCard.vue'
import UiScenePreview from './UiScenePreview.vue'
const ui=useUiAppearance(),{settings}=ui
const bubble=useSpeechBubblePref(),card=useResultCardPref()
const previewMode=ref<'scene'|'surface'>('scene')
const kind=ref<PanelKind>('speech'),previewNote=ref('预览只演示外观，不会播放、联网或打开链接。')
const text=ref('**今天也在这里陪着你。**\n\n- 调整位置和曲线尖端\n- 在模型旁看见真实预览\n\n这是支持 Markdown 的对话气泡。')
const previewWidth=computed(()=>kind.value==='speech'?bubble.maxWidth.value:kind.value==='source'&&settings.value.source.independent?settings.value.source.width:card.maxWidth.value)
const song=ref([{name:'Monody',artist:'TheFatRat / Laura Brehm',song_id:'36308916',availability:'api_unavailable' as const,availability_note:'桌宠通道暂不可播'}])
const sources=[{title:'来源卡外观示例：信息清晰，方便核验',url:'https://example.com/preview',snippet:'这是一段用于排版的示例摘要。来源卡可以设置独立的宽度、高度和字号，也可以选择摘要显示几行。预览中的链接不会被打开，不会发出联网请求。较长文字会按设置收拢，让重要信息更容易看清。',published_at:'2026-10-24T08:00:00+08:00'}]
const playback={backend:'netease_client' as const,song_id:'36308916',name:'Monody',artist:'TheFatRat',status:'paused' as const,playback_id:'ui-preview-only',can_stop:false as const}
function demo(action:string){previewNote.value=`预览：${action}，未执行真实操作。`}
function resetGroup(){
  if(kind.value==='speech'){bubble.reset();ui.reset('speech');settings.value.speechSide='right'}
  else if(kind.value==='music'){card.reset();ui.reset('results')}
  else ui.reset('source')
}
function comicPreset():void {
  settings.value.speech.mode='bubble'
  settings.value.speech.comic=true;settings.value.speech.tail=28;settings.value.speech.border=1.8;settings.value.speech.bubbleStyle='soft';settings.value.speech.anchorY=-.2;settings.value.speech.radius=30;settings.value.speech.padding=24;settings.value.speech.fontSize=17;settings.value.speech.maxHeight=300;settings.value.gap=4;bubble.maxWidth.value=260;bubble.offsetX.value=0;bubble.offsetY.value=0
}
async function modelFirstPreset():Promise<void>{
  const height=Math.round(Math.min(820,screen.availHeight*.84)),width=Math.round(height*.71+40)
  await window.yuiro.setPetLayout({width,height,fillRatio:.96,xOffset:0,yOffset:.5},true)
  comicPreset();settings.value.speech.headAnchored=true;settings.value.speech.anchorY=.14
  settings.value.speech.tail=22;settings.value.speech.radius=26;settings.value.speech.fontSize=14;settings.value.speech.padding=10;settings.value.speech.lineHeight=1.5;settings.value.speech.maxHeight=220
  bubble.maxWidth.value=176;settings.value.speechSide='right';settings.value.gap=8
  card.maxWidth.value=206;card.offsetX.value=0;card.offsetY.value=0;card.side.value='left';settings.value.results.fontSize=11;settings.value.results.maxHeight=260;settings.value.results.compact=true
  settings.value.source.width=224;settings.value.source.fontSize=11;settings.value.source.maxHeight=240
}
function linePreset(dark:boolean):void {
  settings.value.speech.mode='line';settings.value.speech.lineRise=40;settings.value.speech.lineBend=.25;settings.value.speech.ink=dark?'#ffffff':'#252525';settings.value.speech.lineColor=settings.value.speech.ink;settings.value.speech.shadowColor=dark?'#000000':'#ffffff';settings.value.speech.fontSize=18;settings.value.speech.anchorY=-.3;settings.value.speech.lineWidth=1.2;bubble.maxWidth.value=250;bubble.offsetX.value=0;bubble.offsetY.value=0
}
</script>
<template>
  <div class="bubble detached-settings">
    <h3 class="bubble-title">独立回复与结果面板</h3>
    <p class="hint">本机共用的显示偏好，拖动或输入数值即时生效。不会改变角色的大脑、声音、人设或播放器归属。保留了原来的宽度、透明度与偏移设置。</p>
    <div class="ui-workbench">
      <aside class="ui-preview-pane" aria-label="实时预览" tabindex="0">
        <h4 class="pane-title">实时预览</h4>
        <div v-if="kind==='speech'" class="seg panel-tabs" role="group" aria-label="预览方式">
          <button class="seg-btn" :class="{on:previewMode==='scene'}" :aria-pressed="previewMode==='scene'" @click="previewMode='scene'">模型与气泡</button>
          <button class="seg-btn" :class="{on:previewMode==='surface'}" :aria-pressed="previewMode==='surface'" @click="previewMode='surface'">面板细节</button>
        </div>
        <div v-show="kind==='speech'&&previewMode==='scene'" class="model-preview"><UiScenePreview :text="text" /></div>
    <div v-show="kind!=='speech'||previewMode==='surface'" class="preview-board" aria-label="安全外观预览">
      <div class="preview-panel" :style="{width:previewWidth+'px'}">
        <ReplySurface v-if="kind==='speech'" :text="text" :alpha="bubble.alpha.value" />
        <ResultCard v-else detached :rect="null" :title="kind==='music'?'选歌与播放器预览':'联网来源预览'" :kind="kind==='music'?'song':'source'" :items="kind==='music'?song:sources" :playback="kind==='music'?playback:null" @pick="demo('选择条目')" @official="demo('打开歌曲页')" @client="demo('选择网易云客户端')" @control="demo('继续/暂停')" />
      </div>
    </div>
    <p class="hint" role="status">{{ previewNote }}</p>
    <label v-if="kind==='speech'" class="preview-text">预览文字<textarea v-model="text" rows="2" aria-label="回复预览文字" /></label>
      </aside>
      <section class="ui-parameter-pane" aria-label="外观参数" tabindex="0">
        <h4 class="pane-title">调整参数</h4>
    <button class="btn" @click="modelFirstPreset">模型优先 · 头部对白预设</button>
    <p class="hint">放大模型窗口且保留全身，缩小对白/选歌卡；按当前屏幕限制尺寸，可继续微调。</p>
    <details open>
      <summary>共用外观与窗口留白</summary>
      <label class="ui-choice">角色 UI 风格<select v-model="settings.skin" aria-label="角色 UI 风格"><option value="auto">随角色 · Hiyori 奶油 / Hotaru 白花</option><option value="cream">Hiyori · 奶油星光</option><option value="lily">Hotaru · 百合与茉莉</option></select></label>
      <p class="hint">只切换外观；日间/夜间与下方字体、位置设置保持独立。</p>
      <label class="ui-choice">面板主题
        <select v-model="settings.theme" aria-label="面板主题"><option value="light">日间</option><option value="dark">夜间</option><option value="auto">跟随桌宠主题</option></select>
      </label>
      <UiRange v-model="settings.gap" label="与模型和其他面板的留白" :min="4" :max="48" unit=" px" />
      <button class="btn" @click="ui.reset('general')">恢复共用外观默认值</button>
      <p class="hint">回复、选歌与联网来源可同时独立显示，跟随模型拖动，屏幕边缘自动换侧。避让优先于左右微调；空间不足时暂时收起，不覆盖角色。</p>
    </details>
    <div class="seg panel-tabs" role="group" aria-label="自定义面板">
      <button class="seg-btn" :class="{on:kind==='speech'}" :aria-pressed="kind==='speech'" @click="kind='speech'">回复气泡</button>
      <button class="seg-btn" :class="{on:kind==='music'}" :aria-pressed="kind==='music'" @click="kind='music'">音乐与候选</button>
      <button class="seg-btn" :class="{on:kind==='source'}" :aria-pressed="kind==='source'" @click="kind='source'">联网来源</button>
    </div>
    <div class="row-between"><strong>{{ kind==='speech'?'回复气泡':kind==='music'?'音乐与候选卡':'联网来源卡' }}设置</strong><button class="btn" @click="resetGroup">恢复本组默认</button></div>
    <template v-if="kind==='speech'">
      <label class="ui-choice">对白表现<select v-model="settings.speech.mode" aria-label="对白表现"><option value="bubble">气泡（保留漫画预设）</option><option value="line">极简单曲线 · 无背景文字</option></select></label>
      <div><button class="btn" @click="linePreset(true)">单曲线 · 深色桌面</button> <button class="btn" @click="linePreset(false)">单曲线 · 浅色桌面</button></div>
      <label class="check"><input v-model="settings.speech.headAnchored" type="checkbox" /> 对白尖尾跟随头部（默认右上，边缘自动避让）</label>
      <template v-if="settings.speech.mode==='bubble'">
        <label class="ui-choice">气泡笔触<select v-model="settings.speech.bubbleStyle"><option value="soft">柔白双描边</option><option value="ink">漫画墨线</option></select></label>
        <label class="check"><input v-model="settings.speech.ornaments" type="checkbox" /> 角落花卉 / 星光（不遮挡文字）</label>
        <UiRange v-if="settings.speech.ornaments" v-model="settings.speech.ornamentAlpha" label="角落装饰不透明度" :min="0" :max="1" :step=".05" />
      </template>
      <label class="ui-choice">字形<select v-model="settings.speech.font"><option value="system">系统黑体</option><option value="serif">宋体 / 衬线</option><option value="hand">楷体 / 手写感</option><option value="mono">等宽</option></select></label>
      <label class="ui-choice">对齐<select v-model="settings.speech.align"><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></select></label>
      <UiRange v-model="settings.speech.weight" label="字重" :min="300" :max="800" :step="100" />
      <UiRange v-model="settings.speech.tracking" label="字间距" :min="-.5" :max="6" :step=".1" unit=" px" />
      <UiRange v-model="settings.speech.paragraphGap" label="段间距" :min=".1" :max="2" :step=".05" unit=" em" />
      <label class="ui-choice">文字颜色<input v-model="settings.speech.ink" type="color" @input="settings.speech.customInk=true" /></label>
      <label v-if="settings.speech.mode==='bubble'" class="check"><input v-model="settings.speech.customInk" type="checkbox" /> 气泡也使用自选文字色</label>
      <template v-if="settings.speech.mode==='line'">
        <label class="ui-choice">曲线颜色<input v-model="settings.speech.lineColor" type="color" /></label>
        <UiRange v-model="settings.speech.lineRise" label="曲线距离（文字高于嘴部）" :min="0" :max="240" unit=" px" />
        <UiRange v-model="settings.speech.lineBend" label="曲线弯曲程度" :min="0" :max=".8" :step=".01" />
        <UiRange v-model="settings.speech.lineWidth" label="曲线粗细" :min=".5" :max="4" :step=".1" unit=" px" />
        <label class="ui-choice">文字阴影颜色<input v-model="settings.speech.shadowColor" type="color" /></label>
        <UiRange v-model="settings.speech.shadowSize" label="文字柔和阴影" :min="0" :max="5" :step=".25" unit=" px" />
        <label class="check"><input v-model="settings.speech.calibratedMouth" type="checkbox" /> 使用 Hiyori / Hotaru 当前资源的嘴部侧点标定</label>
        <template v-if="!settings.speech.calibratedMouth">
        <UiRange v-model="settings.speech.mouthX" label="嘴部附近的侧向锚点" :min=".5" :max=".95" :step=".01" />
        <UiRange v-model="settings.speech.mouthY" label="嘴部附近的高度锚点" :min=".02" :max=".4" :step=".01" />
        </template>
        <p class="hint">单条开放贝塞尔曲线，无箭头和封闭背景；曲线层始终点击穿透。锚点按模型比例调整，不是自动识别嘴部。</p>
      </template>
      <button class="btn" @click="comicPreset">试用漫画曲线预设</button>
      <label class="check"><input v-model="settings.speech.comic" type="checkbox" /> 曲线尖端与柔和漫画轮廓</label>
      <UiRange v-model="settings.speech.tail" label="曲线尖端长度" :min="0" :max="120" unit=" px" />
      <UiRange v-model="settings.speech.anchorY" label="相对模型的说话高度（负数靠上）" :min="-.8" :max="1.2" :step=".02" />
      <UiRange v-model="settings.speech.border" label="气泡描边" :min="0" :max="4" :step=".5" unit=" px" />
      <label class="ui-choice">优先出现位置<select v-model="settings.speechSide" aria-label="回复优先侧"><option value="left">模型左侧</option><option value="right">模型右侧</option></select></label>
      <UiRange v-model="bubble.maxWidth.value" label="回复宽度" :min="100" :max="720" unit=" px" />
      <UiRange v-model="settings.speech.maxHeight" label="回复最大高度" :min="80" :max="900" unit=" px" />
      <UiRange v-model="settings.speech.fontSize" label="回复字号" :min="10" :max="36" unit=" px" />
      <UiRange v-model="settings.speech.lineHeight" label="回复行距" :min="1" :max="2.5" :step=".05" />
      <UiRange v-model="settings.speech.radius" label="回复圆角" :min="0" :max="100" unit=" px" />
      <UiRange v-model="settings.speech.padding" label="回复内边距" :min="4" :max="48" unit=" px" />
      <UiRange v-model="bubble.alpha.value" label="回复不透明度" :min=".05" :max="1" :step=".02" />
      <UiRange v-model="bubble.offsetX.value" label="回复左右微调" :min="-1000" :max="1000" unit=" px" />
      <UiRange v-model="bubble.offsetY.value" label="回复上下微调" :min="-1000" :max="1000" unit=" px" />
    </template>
    <template v-else-if="kind==='music'">
      <label class="ui-choice">优先出现位置<select v-model="card.side.value" aria-label="结果卡优先侧"><option value="left">模型左侧</option><option value="right">模型右侧</option></select></label>
      <UiRange v-model="card.maxWidth.value" label="结果卡宽度" :min="120" :max="420" unit=" px" />
      <UiRange v-model="settings.results.maxHeight" label="结果卡最大高度" :min="160" :max="440" unit=" px" />
      <UiRange v-model="settings.results.fontSize" label="结果卡字号" :min="11" :max="20" unit=" px" />
      <UiRange v-model="settings.results.lineHeight" label="结果卡行距" :min="1.2" :max="2" :step=".05" />
      <UiRange v-model="settings.results.radius" label="结果卡圆角" :min="0" :max="32" unit=" px" />
      <UiRange v-model="settings.results.padding" label="结果卡内边距" :min="8" :max="24" unit=" px" />
      <UiRange v-model="card.alpha.value" label="结果卡不透明度" :min=".3" :max="1" :step=".02" />
      <UiRange v-model="card.offsetX.value" label="结果卡左右微调" :min="-400" :max="400" unit=" px" />
      <UiRange v-model="card.offsetY.value" label="结果卡上下微调" :min="-400" :max="400" unit=" px" />
      <UiRange v-model="settings.results.seconds" label="候选卡停留时间（0 为手动收起）" :min="0" :max="120" unit=" 秒" />
      <label class="check"><input v-model="settings.results.compact" type="checkbox" /> 紧凑条目间距</label>
      <label class="check"><input v-model="settings.results.showAvailableNote" type="checkbox" /> 显示客户端权益说明</label>
      <label class="check"><input v-model="settings.results.showOfficialPage" type="checkbox" /> 显示“打开官方歌曲页”</label>
      <p class="hint">选歌仅使用网易云客户端，API 可播标志不代表客户端权益。正在使用官方播放器时，控制卡不按候选时长自动消失。</p>
    </template>
    <template v-else>
      <label class="check"><input v-model="settings.source.independent" type="checkbox" /> 来源卡使用独立宽度、字号与高度</label>
      <p class="hint">未开启时跟随“音乐与候选”的尺寸和字号；位置、透明度、圆角及主题共用，避免同类面板调整不一致。</p>
      <template v-if="settings.source.independent">
        <UiRange v-model="settings.source.width" label="来源卡宽度" :min="160" :max="420" unit=" px" />
        <UiRange v-model="settings.source.maxHeight" label="来源卡最大高度" :min="160" :max="440" unit=" px" />
        <UiRange v-model="settings.source.fontSize" label="来源卡字号" :min="11" :max="20" unit=" px" />
      </template>
      <UiRange v-model="settings.source.summaryLines" label="来源摘要行数" :min="1" :max="8" />
      <UiRange v-model="settings.source.seconds" label="来源卡停留时间（0 为手动收起）" :min="0" :max="120" unit=" 秒" />
      <label class="check"><input v-model="settings.source.showDate" type="checkbox" /> 显示发布时间（无日期时说明未知）</label>
    </template>
    <details><summary>悬浮功能岛（仅调整呼出后的菜单）</summary>
      <UiRange v-model="settings.island.size" label="功能岛按钮大小" :min="28" :max="80" unit=" px" />
      <UiRange v-model="settings.island.distance" label="功能岛横向展开距离" :min="12" :max="180" unit=" px" />
      <UiRange v-model="settings.island.gap" label="功能岛纵向间距" :min="32" :max="120" unit=" px" />
      <UiRange v-model="settings.island.alpha" label="功能岛底色不透明度" :min=".05" :max="1" :step=".05" />
      <UiRange v-model="settings.island.radius" label="功能岛圆角比例" :min="0" :max="50" unit=" %" />
      <UiRange v-model="settings.island.offsetY" label="功能岛上下微调" :min="-200" :max="200" unit=" px" />
      <UiRange v-model="settings.island.duration" label="功能岛展开动画时长" :min="0" :max="600" unit=" ms" />
      <button class="btn" @click="settings.island={...UI_APPEARANCE_DEFAULTS.island}">恢复功能岛默认</button>
    </details>
      </section>
    </div>
  </div>
</template>
<style scoped>
.detached-settings{--line:var(--border);--surface:var(--input);container-type:inline-size;width:100%;max-width:none;min-width:0}
.ui-workbench{display:grid;grid-template-columns:minmax(0,1fr);gap:20px;margin-top:16px}
.ui-preview-pane,.ui-parameter-pane{min-width:0;box-sizing:border-box}
.ui-preview-pane{background:var(--card-head);border:1px solid var(--border-soft);border-radius:16px;padding:14px}
.pane-title{margin:0 0 12px;font-size:13px;font-weight:600;color:var(--text-soft)}
.ui-parameter-pane{padding:4px 10px 12px 2px}
.ui-parameter-pane .ui-choice select{min-width:0;max-width:65%}
.ui-parameter-pane:focus-visible,.ui-preview-pane:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.model-preview :deep(.ui-scene){height:clamp(260px,calc(100vh - 430px),420px)}
@container(min-width:640px){
 .ui-workbench{grid-template-columns:minmax(0,1.1fr) minmax(280px,.9fr);height:clamp(420px,calc(100vh - 250px),720px);align-items:stretch}
 .ui-preview-pane,.ui-parameter-pane{overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--border) transparent}
}

.panel-tabs{gap:4px;padding:4px;border:1px solid var(--border);border-radius:12px;background:var(--card-head)}
.panel-tabs .seg-btn{border:0;border-radius:8px;background:transparent;color:var(--text-soft);font:inherit;font-size:13px;padding:8px 12px;cursor:pointer}
.panel-tabs .seg-btn:hover{background:var(--accent-soft)}
.panel-tabs .seg-btn.on{background:var(--card);color:var(--text);box-shadow:var(--shadow-soft)}
.panel-tabs .seg-btn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.detached-settings details{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:16px}.detached-settings summary{cursor:pointer;font-weight:600;margin-bottom:12px}.ui-choice{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:14px 0;font-size:13px}.ui-choice select{max-width:220px;padding:6px;border:1px solid var(--line);border-radius:8px;color:inherit;background:var(--surface)}.panel-tabs{display:flex;flex-wrap:wrap;margin:12px 0}.preview-board{overflow:auto;max-height:470px;min-height:100px;display:flex;justify-content:center;padding:18px 8px;border-radius:12px;background:repeating-conic-gradient(#b7b7b7 0% 25%,#dedede 0% 50%) 0/16px 16px}.preview-panel{flex-shrink:0;max-width:100%}.preview-text{display:block;margin:10px 0 18px;font-size:12px}.preview-text textarea{display:block;width:100%;box-sizing:border-box;resize:vertical;border:1px solid var(--line);border-radius:8px;padding:8px;color:inherit;background:var(--surface)}.check{display:block;font-size:13px;margin:12px 0}.check input{margin-right:6px;accent-color:var(--accent)}
</style>
