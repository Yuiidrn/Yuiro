import { contextBridge, ipcRenderer } from 'electron'
import type { DetachedAction, DetachedContent, DetachedState, DialogueConnector } from '../shared/detachedUi'
import type {
  Live2DManifest,
  ModelImportResult,
  ModelReport,
  PetLayout,
  PickFilesOptions,
  PickFilesResult,
  ShellEvent,
} from '../shared'

/**
 * Preload bridge — exposes a typed, minimal API to the renderer.
 */
const api = {
  setDiaryAppearance(value:{skin:'cream'|'lily';theme:'light'|'dark'}):void{ipcRenderer.send('diary:appearance',value)},
  onDialogueLine(cb:(state:DialogueConnector)=>void):()=>void {
    const listener=(_e:unknown,s:DialogueConnector):void=>cb(s)
    ipcRenderer.on('detached:line',listener)
    return ()=>ipcRenderer.removeListener('detached:line',listener)
  },
  publishDetached(state: DetachedState): void { ipcRenderer.send('detached:publish', state) },
  detachedReady(): void { ipcRenderer.send('detached:ready') },
  detachedSize(size: {width:number;height:number;key:string}): void { ipcRenderer.send('detached:size', size) },
  detachedAction(action: DetachedAction): void { ipcRenderer.send('detached:action', action) },
  onDetachedState(cb: (state: DetachedContent) => void): () => void {
    const listener=(_e:unknown,s:DetachedContent):void=>cb(s)
    ipcRenderer.on('detached:state',listener)
    return ()=>ipcRenderer.removeListener('detached:state',listener)
  },
  onDetachedAction(cb: (action: DetachedAction) => void): () => void {
    const listener=(_e:unknown,a:DetachedAction):void=>cb(a)
    ipcRenderer.on('detached:action',listener)
    return ()=>ipcRenderer.removeListener('detached:action',listener)
  },
  // Send typed events to main.
  send(event: ShellEvent): void {
    ipcRenderer.send('shell:event', event)
  },
  // Subscribe to typed events from main.
  on(callback: (event: ShellEvent) => void): () => void {
    const listener = (_e: Electron.IpcRendererEvent, payload: ShellEvent): void => {
      if (payload?.type === 'appearance:update') {
        console.log('[preload] shell:event appearance:update', payload)
      }
      callback(payload)
    }
    ipcRenderer.on('shell:event', listener)
    return () => ipcRenderer.removeListener('shell:event', listener)
  },
  // 桌宠窗口点击穿透开关：输入聚焦时关闭(可交互)，失焦时开启(桌宠不挡鼠标)
  /** sendSync：须在 click 到达前同步关闭 OS 级穿透 */
  setMousePassthrough(passthrough: boolean): void {
    ipcRenderer.sendSync('mouse:passthrough', passthrough)
  },
  /** 对话输入等场景需临时允许窗口获取键盘焦点（默认 focusable:false）。 */
  setFocusable(focusable: boolean): void {
    ipcRenderer.send('window:focusable', focusable)
  },
  // Request native approval for a system action.
  requestApproval(request: {
    approvalRequestId: string
    tool: string
    summary: string
  }): Promise<{ requestId: string, approved: boolean }> {
    return ipcRenderer.invoke('approval:required', request)
  },
  // 打开开发者调试窗口（settings / logs / status）。
  openDev(section: 'settings' | 'logs' | 'status' = 'settings'): Promise<void> {
    return ipcRenderer.invoke('dev:open', section)
  },
  /** S51：用系统浏览器打开外部链接（来源卡点击核验）；仅 http/https。 */
  openExternal(url: string): Promise<{ ok: boolean, note?: string }> {
    return ipcRenderer.invoke('shell:open-external', url)
  },
  /** S51：打开独立日记编辑窗口（日记输入不走 AgentLoop，与对话物理分离）。 */
  openDiary(): Promise<void> {
    return ipcRenderer.invoke('diary:open')
  },
  /**
   * S51：日记窗口把一段文字**转成桌宠的聊天输入**（返回桌宠窗口是否收到）。
   *
   * 为什么绕主进程一跳而不让日记窗口自己发 `chat:user`：
   * 引擎 `/ws/control` 的 `chat:assistant` 只回**发起的那条连接**（`ws.send_json`），
   * 且 `_control_conns` 按 session 存**单个**连接 —— 日记窗口自己发会开一个新
   * session，回复既接不上桌宠的 history，也显示不到桌宠窗口（气泡/口型都在那边）。
   */
  relayChat(text: string): Promise<boolean> {
    return ipcRenderer.invoke('diary:relay-chat', text)
  },
  /** 桌宠窗口：接收日记窗口转来的聊天输入。 */
  onRelayChat(cb: (text: string) => void): () => void {
    const listener = (_e: Electron.IpcRendererEvent, text: string): void => cb(text)
    ipcRenderer.on('pet:relay-chat', listener)
    return () => ipcRenderer.removeListener('pet:relay-chat', listener)
  },
  /** 桌宠窗口：把这一轮回复回传给日记窗口（写作页的页边批注）。 */
  relayDiaryReply(text: string): Promise<boolean> {
    return ipcRenderer.invoke('diary:relay-reply', text)
  },
  /** 日记窗口：订阅桌宠回传的回复。 */
  onDiaryReply(cb: (text: string) => void): () => void {
    const listener = (_e: Electron.IpcRendererEvent, text: string): void => cb(text)
    ipcRenderer.on('diary:reply', listener)
    return () => ipcRenderer.removeListener('diary:reply', listener)
  },
  // 引擎 WS 鉴权用的共享密钥（来自启动环境 YUIRO_SHARED_SECRET）。
  // 前端 WebSocket 无法自定义 header，故连引擎时以 ?secret= 查询参数携带此值。
  getEngineSecret(): Promise<string> {
    return ipcRenderer.invoke('engine:secret')
  },
  // 桌宠窗口外观（窗口尺寸 / 模型缩放 / 模型偏移）。
  getPetLayout(): Promise<PetLayout> {
    return ipcRenderer.invoke('dev:get-pet-layout')
  },
  /**
   * 提交窗口外观。
   * @param persist 是否落盘。滑杆拖动过程传 false（窗口要跟手但不必每次写盘），
   *                松手时再以 true 提交一次。
   */
  setPetLayout(layout: PetLayout, persist = true): Promise<PetLayout> {
    return ipcRenderer.invoke('dev:set-pet-layout', layout, persist)
  },
  // 桌宠形象：更换 Live2D 模型 / 试播动作 / 预览表情（调试台「外观」页调用，
  // 经主进程广播给桌宠窗口执行）
  setPetModel(path: string, characterId?: string): Promise<{ ok: boolean, path?: string }> {
    return ipcRenderer.invoke('dev:set-pet-model', path, characterId)
  },
  /** 扫描 live2d 目录，列出用户自己放入的模型（不依赖 model_dict.json 登记）。 */
  scanLive2dModels(): Promise<{ path: string, registeredHint: string, name?: string, author?: string }[]> {
    return ipcRenderer.invoke('live2d:scan-models')
  },
  /** 模型清单（语义槽位推断）：槽位 → 具体表情/动作索引，按 mtime 缓存。 */
  inspectPetModel(path: string): Promise<Live2DManifest> {
    return ipcRenderer.invoke('live2d:inspect-model', path)
  },
  // ── 模型体检 / 导入（S49）──
  /** 体检一个模型目录或 model3.json（只读，问题以报告形式返回，不抛错）。 */
  validatePetModel(path: string): Promise<ModelReport> {
    return ipcRenderer.invoke('dev:validate-model', path)
  },
  /** 弹出目录选择框（导入模型用）。 */
  pickModelDir(): Promise<{ canceled: boolean, path: string }> {
    return ipcRenderer.invoke('dev:pick-model-dir')
  },
  /**
   * S54：弹出系统文件/目录选择框，返回**绝对路径**。
   *
   * TTS 参考（音频/转写）用单选，知识库导入用 `multiple: true`；
   * `directory: true` 时选目录。取消时返回 `{canceled: true, paths: []}`。
   */
  pickFiles(opts?: PickFilesOptions): Promise<PickFilesResult> {
    return ipcRenderer.invoke('dev:pick-files', opts ?? {})
  },
  /** 导入模型目录：体检 → 复制进 live2d 资源目录 → 登记。 */
  importPetModel(path: string, name?: string): Promise<ModelImportResult> {
    return ipcRenderer.invoke('dev:import-model', path, name)
  },
  /**
   * 试演一次成套表演（表情 + 动作 + 时长）。
   * 走主进程直推桌宠窗口，**不需要引擎在线** —— 调试台自己解析表演内容。
   */
  applyPetIntent(payload: {
    characterId?: string
    modelPath?: string
    name?: string
    expression?: string
    motion?: string
    motionIndex?: number | null
    durationMs?: number
  }): Promise<{ ok: boolean }> {
    return ipcRenderer.invoke('dev:apply-intent', payload)
  },
  playPetMotion(group: string, index?: number, context?: { characterId?: string; modelPath?: string }): Promise<{ ok: boolean }> {
    return ipcRenderer.invoke('dev:play-motion', group, index, context)
  },
  previewPetExpression(name: string, context?: { characterId?: string; modelPath?: string }): Promise<{ ok: boolean }> {
    return ipcRenderer.invoke('dev:play-expression', name, context)
  },
  // 窗口贴合模型：渲染层量出模型实际尺寸后，主进程把窗口 resize 为
  // 模型尺寸 + 底部功能区余量（消除透明空白，实现"窗口 ≈ 模型"）。
  fitWindowToModel(size: { width: number, height: number }): Promise<void> {
    return ipcRenderer.invoke('window:fit-to-model', size)
  },
  // 聊天坞：窗口向左生长出面板空间（返回实际扩出宽度，0 = 屏幕空间不足）。
  expandChat(width: number): Promise<{ width: number }> {
    return ipcRenderer.invoke('window:expand-chat', width)
  },
  collapseChat(): Promise<void> {
    return ipcRenderer.invoke('window:collapse-chat')
  },
  // JS 拖动：主进程读 OS 光标绝对坐标，三阶段（start/move/end），无累积误差
  dragPetStart(): void {
    ipcRenderer.sendSync('window:drag-start')
  },
  dragPetMove(): void {
    ipcRenderer.sendSync('window:drag-move')
  },
  dragPetEnd(): void {
    ipcRenderer.sendSync('window:drag-end')
  },
  // overlay 悬停渐隐：订阅主进程 ~60fps 推来的鼠标 screen 坐标
  onCursorPoint(cb: (p: { x: number, y: number, u?: number, v?: number }) => void): () => void {
    const listener = (_e: Electron.IpcRendererEvent, p: { x: number, y: number, u?: number, v?: number }): void => cb(p)
    ipcRenderer.on('overlay:cursor', listener)
    return () => ipcRenderer.removeListener('overlay:cursor', listener)
  },
  // overlay 悬停渐隐：订阅主进程推来的窗口 bounds（DIP）
  onWindowBounds(cb: (b: { x: number, y: number, width: number, height: number }) => void): () => void {
    const listener = (_e: Electron.IpcRendererEvent, b: { x: number, y: number, width: number, height: number }): void => cb(b)
    ipcRenderer.on('overlay:bounds', listener)
    return () => ipcRenderer.removeListener('overlay:bounds', listener)
  },
  // overlay 悬停渐隐：首次使用时启动主进程坐标流
  startOverlayTracking(): Promise<unknown> {
    return ipcRenderer.invoke('overlay:tracking-start')
  },
  // overlay 悬停渐隐：渲染层向主进程上报开启状态（供托盘菜单动态显示逃生项）
  reportFadeState(enabled: boolean): void {
    ipcRenderer.send('fade:state', enabled)
  },
  // overlay 悬停渐隐：主进程（托盘切换）请求设置开关时回调，传入目标态
  onFadeSet(cb: (on: boolean) => void): () => void {
    const listener = (_e: unknown, on: boolean): void => cb(on)
    ipcRenderer.on('fade:set', listener)
    return () => ipcRenderer.removeListener('fade:set', listener)
  },
}

contextBridge.exposeInMainWorld('yuiro', api)

export type YuiroBridge = typeof api
