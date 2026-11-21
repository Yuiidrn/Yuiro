import { app, BrowserWindow, Tray, Menu, MenuItemConstructorOptions, ipcMain, nativeImage, dialog, IpcMainInvokeEvent, screen, session, shell } from 'electron'
import { join } from 'node:path'
import { registerDetachedUi } from './detachedUi'
import { overlayCursor } from './overlayCoordinates'
import { cpSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync, type Dirent } from 'node:fs'
import { relative, sep } from 'node:path'
import type { ModelImportResult, ModelIssue, ModelReport, PickFilesOptions, ShellEvent } from '../shared'
import { inspectModel } from './live2dManifest'
import { live2dRootDir, toWebPath } from './live2dPaths'

// 文本/语音聊天由桌宠窗口的渲染进程用浏览器原生 WebSocket 直连引擎，
// 主进程只负责窗口、托盘、审批与点击穿透切换。

let petWindow: BrowserWindow | null = null

/** 桌宠窗口外观（调试窗口可改，main 为真相源并同步给渲染层）。 */
let petLayoutConfigured=false
const petLayout = { width: 420, height: 560, fillRatio: 0.55, xOffset: 0, yOffset: 0.45 }

/* ---------------------------------------------------------------------------
 * 壳层 UI 设置的落盘
 *
 * 渲染层里用 localStorage 保存的设置（免打扰 / 主题 / 回复气泡）本来就跨启动保留；
 * 但「外观」页的窗口几何是主进程状态，此前只存在内存里，重启即丢。
 * 这里把它持久化成一个小 JSON，让每次启动都沿用上次的窗口外观。
 *
 * 位置：优先 YUIRO_DATA_DIR（由 config/env.ps1 指向 <repo>/.env-local/data，
 * 遵守「不占 C 盘」约定）；未设置该变量时（如打包运行）回退到 Electron 默认 userData。
 * ------------------------------------------------------------------------- */

/** UI 设置文件名。 */
const UI_SETTINGS_FILE = 'shell-ui.json'

function uiSettingsPath(): string {
  const dir = process.env['YUIRO_DATA_DIR'] || app.getPath('userData')
  try {
    mkdirSync(dir, { recursive: true })
  } catch { /* 目录已存在或不可创建，后续读写会各自兜底 */ }
  return join(dir, UI_SETTINGS_FILE)
}

/** 数值归一：非数字/NaN 回退默认值，并夹紧到合法区间。 */
function clampNum(v: unknown, lo: number, hi: number, fallback: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  return Math.min(Math.max(n, lo), hi)
}

/** 校验并归一化窗口外观，避免手改设置文件写进离谱数值把窗口弄没。 */
function sanitizePetLayout(raw: unknown): typeof petLayout {
  const o = (raw ?? {}) as Partial<typeof petLayout>
  return {
    width: Math.round(clampNum(o.width, 200, 2000, 420)),
    height: Math.round(clampNum(o.height, 200, 2000, 560)),
    fillRatio: clampNum(o.fillRatio, 0.1, 2, 0.55),
    // 模型水平偏移（px）：正值向右。夹紧到 ±600，避免把模型推出可视区
    xOffset: Math.round(clampNum(o.xOffset, -600, 600, 0)),
    yOffset: clampNum(o.yOffset, 0, 1, 0.45),
  }
}

/**
 * 把窗口尺寸夹紧到「当前显示器工作区」内（留8 DIP安全边距）。
 *
 * 为什么必须夹紧：模型的原始尺寸可能比屏幕还大 —— shizuku 是 1280×1380，
 * 贴合后窗口高达 1480px，在 1080p 屏上超出屏幕，模型被顶到屏幕外，
 * 表现为「**只有这个模型加载不出来**」（其它模型尺寸温和，贴合后在屏幕内）。
 * 更糟的是坏尺寸会落盘，之后每次启动都复现。
 *
 * 夹紧后多出的空间不必担心：渲染层按「可用区」自动缩小模型
 * （fillRatio 保持 1 时 fit < 1 即为等比缩放），模型始终完整可见。
 */
function clampToWorkArea(width: number, height: number): { width: number; height: number; clamped: boolean } {
  const display = petWindow && !petWindow.isDestroyed()
    ? screen.getDisplayMatching(petWindow.getBounds())
    : screen.getPrimaryDisplay()
  const area = display.workAreaSize
  const w = Math.min(width, Math.max(240, area.width - 16))
  const h = Math.min(height, Math.max(240, area.height - 16))
  return { width: w, height: h, clamped: w !== width || h !== height }
}

/** 启动时读取上次保存的 UI 设置（无文件/解析失败则保持默认值）。 */
function loadUiSettings(): void {
  try {
    const raw = JSON.parse(readFileSync(uiSettingsPath(), 'utf-8')) as { petLayout?: unknown }
    if (raw?.petLayout) {
      Object.assign(petLayout, sanitizePetLayout(raw.petLayout))
      petLayoutConfigured=true
      // 自愈历史坏值：旧版本贴合模型时未按屏幕夹紧，可能落盘了 1280×1480
      // 这种比屏幕还大的窗口（模型被顶到屏幕外、且每次启动复现）。
      const fit = clampToWorkArea(petLayout.width, petLayout.height)
      if (fit.clamped) {
        console.log(`[ui-settings] 上次窗口超出屏幕，已夹紧 ${petLayout.width}×${petLayout.height} → ${fit.width}×${fit.height}`)
        petLayout.width = fit.width
        petLayout.height = fit.height
        saveUiSettings()
      }
      console.log('[ui-settings] 已沿用上次的窗口外观', JSON.stringify(petLayout))
    }
  } catch {
    // 首次启动没有该文件，属正常情况
  }
}

/** 写回 UI 设置（失败不阻断功能，只记日志）。 */
function saveUiSettings(): void {
  try {
    writeFileSync(uiSettingsPath(), JSON.stringify({ petLayout }, null, 2), 'utf-8')
  } catch (e) {
    console.error('[ui-settings] 保存失败:', e)
  }
}

/**
 * 扫描 live2d 目录下所有 *.model3.json，返回渲染层可直接加载的 URL 列表。
 *
 * 目的：用户把自己的 Live2D 模型文件夹丢进 public/live2d/ 就能被调试台发现，
 * 不需要改代码、也不强制登记到 model_dict.json。
 *
 * 开发态从源码 public/ 扫，打包后从 out/renderer 扫；都取不到就返回空数组
 * （调用方会回退到 model_dict.json 注册表，不会因此报错）。
 */
function scanLive2dModels(): { path: string; registeredHint: string; name?: string; author?: string }[] {
  const root = live2dRootDir()
  if (!root) return []

  const found: { path: string; registeredHint: string; name?:string;author?:string }[] = []
  let registry:Record<string,{name?:string;author?:string;hidden?:boolean;modelPath?:string}>={}
  try{registry=JSON.parse(readFileSync(join(root,'model_dict.json'),'utf8')).models??{}}catch{/* 未登记模型仍可扫描 */}
  const walk = (dir: string, depth: number): void => {
    if (depth > 4) return
    let entries: Dirent[]
    try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      const full = join(dir, e.name)
      if (e.isDirectory()) {
        walk(full, depth + 1)
      } else if (e.isFile() && e.name.endsWith('.model3.json')) {
        // toWebPath 统一负责 /live2d/ 前缀与分隔符（含空格目录也不丢字符）
        const path=toWebPath(full),meta=Object.values(registry).find(x=>x.modelPath===path)
        if(!meta?.hidden)found.push({ path, registeredHint: relative(root, full).split(sep)[0],name:meta?.name,author:meta?.author })
      }
    }
  }
  walk(root, 0)
  return found
}

/* ─────────────────────────────────────────────────────────────────────────
 * 模型体检 / 导入（S49）
 *
 * 为什么需要：换模型出的问题有一半是**资源包本身不齐或命名不规范** ——
 * 缺贴图、引用大小写不匹配（Windows 不区分、打包到别处就 404）、
 * 中文或空格文件名（URL 未编码 → 404）、moc3 版本超出 SDK 支持范围。
 * 加载失败时这些只表现成一句语焉不详的报错，甚至一片空白（这类排查花过一整轮）。
 * 这里把它们变成一份可读报告：谁缺了、在哪个目录、建议怎么改。
 * ───────────────────────────────────────────────────────────────────────── */

/** 导入时跳过的目录（打包/版本控制/系统垃圾，进模型目录只会添乱）。 */
const SKIP_DIRS = new Set(['__MACOSX', '.git', '.svn', 'node_modules', '.idea', '.vscode'])

/* 报告结构定义在 shared/events.ts（主进程 / preload / 渲染层共用一份，避免三处各写各的）。 */

/** 递归找 model3.json（跳过打包产生的垃圾目录）。 */
function findModel3(dir: string, depth = 0): string | null {
  if (depth > 3) return null
  let entries: Dirent[]
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return null }
  const direct = entries.find((e) => e.isFile() && e.name.endsWith('.model3.json'))
  if (direct) return join(dir, direct.name)
  for (const e of entries) {
    if (!e.isDirectory() || e.name === '__MACOSX' || e.name.startsWith('.')) continue
    const r = findModel3(join(dir, e.name), depth + 1)
    if (r) return r
  }
  return null
}

/** 同目录下不区分大小写地找一个文件（用于把"大小写不匹配"从"文件缺失"里区分出来）。 */
function findEntryInsensitive(dir: string, name: string): string | null {
  try {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name.toLowerCase() === name.toLowerCase()) return e.name
    }
  } catch { /* ignore */ }
  return null
}

/** 目录里是否已有同名（不区分大小写）的条目 —— 用它给出"更接近的正确名字"。 */
function collectNonAscii(dir: string, out: string[], depth = 0): void {
  if (depth > 3 || out.length >= 6) return
  let entries: Dirent[]
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
  for (const e of entries) {
    if (e.isDirectory()) collectNonAscii(join(dir, e.name), out, depth + 1)
    // eslint-disable-next-line no-control-regex
    else if (/[^\u0000-\u007F]/.test(e.name) && out.length < 6) out.push(e.name)
  }
}

/**
 * 体检一个模型目录（或直接给 model3.json 路径）。**不抛错**，全部问题都收进报告。
 */
function validateModel(input: string): ModelReport {
  const issues: ModelIssue[] = []
  const info: ModelReport['info'] = {
    moc: '', mocVersion: 0, textures: [], expressions: [], motionGroups: [], params: 0,
    physics: false, pose: false, nonAscii: [],
  }
  const fail = (dir: string, model3: string, text: string): ModelReport => {
    issues.push({ level: 'error', text })
    return { ok: false, dir, model3, issues, info }
  }

  let dir = input
  let model3: string | null = null
  try {
    if (statSync(input).isDirectory()) {
      model3 = findModel3(input)
      dir = input
    } else {
      model3 = input
      dir = input.replace(/[\\/][^\\/]+$/, '')
    }
  } catch {
    return fail(dir, '', `路径不存在或不可读：${input}`)
  }
  if (!model3) return fail(dir, '', '没有找到 *.model3.json（Live2D 模型的入口文件）')

  let json: Record<string, any>
  try {
    json = JSON.parse(readFileSync(model3, 'utf8')) as Record<string, any>
  } catch (e) {
    return fail(dir, model3, `model3.json 解析失败：${e instanceof Error ? e.message : String(e)}`)
  }

  const refs = (json.FileReferences ?? {}) as Record<string, any>
  const base = model3.replace(/[\\/][^\\/]+$/, '')

  // ── 引用完整性 ──
  const checkRef = (label: string, rel: unknown): boolean => {
    const r = String(rel ?? '').trim()
    if (!r) return true
    const full = join(base, r)
    try {
      if (statSync(full).isFile()) return true
    } catch { /* 继续找大小写近似 */ }
    const segs = r.split(/[\\/]/)
    const fileName = segs.pop() ?? r
    const parent = segs.length ? join(base, ...segs) : base
    const ci = findEntryInsensitive(parent, fileName)
    if (ci) {
      issues.push({
        level: 'error',
        text: `${label} 引用大小写不匹配：写的是 "${r}"，磁盘上是 "${ci}"（本机 Windows 能读，换平台/打包后 404）`,
      })
    } else {
      issues.push({ level: 'error', text: `${label} 引用的文件不存在：${r}` })
    }
    return false
  }

  checkRef('Moc', refs.Moc)
  for (const t of (Array.isArray(refs.Textures) ? refs.Textures : [])) {
    if (checkRef('Texture', t)) {
      const full = join(base, String(t))
      try {
        info.textures.push({ file: String(t), mb: Number((statSync(full).size / 1048576).toFixed(2)) })
      } catch { /* ignore */ }
    }
  }
  if (refs.Physics) { info.physics = checkRef('Physics', refs.Physics) }
  if (refs.Pose) { info.pose = checkRef('Pose', refs.Pose) }
  checkRef('UserData', refs.UserData)
  checkRef('DisplayInfo', refs.DisplayInfo)

  const motions = (refs.Motions ?? {}) as Record<string, any[]>
  for (const [group, arr] of Object.entries(motions)) {
    const list = Array.isArray(arr) ? arr : []
    let okCount = 0
    for (const item of list) {
      if (checkRef(`动作 ${group}`, (item as Record<string, unknown>)?.File)) okCount++
    }
    info.motionGroups.push({ group, count: okCount })
  }

  const exps = Array.isArray(refs.Expressions) ? refs.Expressions : []
  for (const item of exps) {
    const name = String((item as Record<string, unknown>)?.Name ?? '(未命名)')
    if (checkRef(`表情 ${name}`, (item as Record<string, unknown>)?.File)) info.expressions.push(name)
  }

  // ── moc3 头与版本 ──
  const mocRel = String(refs.Moc ?? '')
  if (mocRel) {
    info.moc = mocRel
    try {
      const buf = readFileSync(join(base, mocRel))
      const header = buf.subarray(0, 4).toString('ascii')
      const ver = buf[4] ?? 0
      info.mocVersion = ver
      if (header !== 'MOC3') issues.push({ level: 'error', text: `Moc 不是有效的 moc3 文件（头部="${header}"，应为 MOC3）` })
      // 版本 6 起属于 Cubism 5.3+，本项目的 SDK（5.1）读不了
      if (ver >= 6) issues.push({ level: 'error', text: `moc3 版本 ${ver}（Cubism 5.3+）超出当前 SDK（5.1）支持范围，会加载失败` })
    } catch {
      issues.push({ level: 'warn', text: `Moc 无法读取：${mocRel}` })
    }
  }

  // ── cdi3 参数表 ──
  if (refs.DisplayInfo) {
    try {
      const cdi = JSON.parse(readFileSync(join(base, String(refs.DisplayInfo)), 'utf8')) as Record<string, unknown>
      info.params = Array.isArray(cdi.Parameters) ? cdi.Parameters.length : 0
    } catch { /* ignore */ }
  }

  // ── 体积与命名（都是"能加载但会坑"的项）──
  const totalMb = info.textures.reduce((s, t) => s + t.mb, 0)
  if (totalMb > 30) issues.push({ level: 'warn', text: `贴图合计 ${totalMb.toFixed(1)} MB，偏重（>30MB）` })
  for (const t of info.textures) {
    if (t.mb > 100) issues.push({ level: 'warn', text: `贴图过大：${t.file} = ${t.mb} MB` })
  }
  collectNonAscii(dir, info.nonAscii)
  if (info.nonAscii.length) {
    issues.push({
      level: 'warn',
      text: `文件名含中文/空格：${info.nonAscii.join('、')}${info.nonAscii.length >= 6 ? '…' : ''}`
        + '（loader 不一定会编码 URL → 可能 404；建议改成纯 ASCII 名）',
    })
  }

  return {
    ok: !issues.some((i) => i.level === 'error'),
    dir,
    model3,
    issues,
    info,
  }
}

/** 把模型目录导入 live2d 资源目录，并登记进 model_dict.json（写不了也不影响加载）。 */
function importModelDir(srcDir: string, displayName?: string): ModelImportResult {
  const report = validateModel(srcDir)
  if (!report.ok) {
    return { ok: false, report, message: '体检未通过，未导入（先按报告修好资源）' }
  }
  const root = live2dRootDir()
  if (!root) {
    return { ok: false, report, message: '找不到 live2d 资源目录；打包后的应用不支持导入（请手动放入资源目录）' }
  }
  const rawName = String(displayName ?? '').trim() || String(srcDir).replace(/[\\/]+$/, '').split(/[\\/]/).pop() || 'model'
  // 目录名强制 ASCII：中文/空格目录名是 404 的高发原因（导入时就地消掉，不留隐患）
  const name = rawName.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'model'
  const dest = join(root, name)
  try {
    if (statSync(dest).isDirectory()) {
      return { ok: false, report, message: `目标目录已存在：live2d/${name}（先改名或删掉旧的）` }
    }
  } catch { /* 不存在 → 可以导入 */ }

  try {
    cpSync(srcDir, dest, {
      recursive: true,
      filter: (src) => !SKIP_DIRS.has(src.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? ''),
    })
  } catch (e) {
    return { ok: false, report, message: `复制失败：${e instanceof Error ? e.message : String(e)}` }
  }

  // 登记（best-effort）：让调试台显示友好名与来源；失败只影响显示
  let modelPath = ''
  const model3 = findModel3(dest)
  if (model3) {
    const rel = relative(root, model3).split(sep).join('/')
    modelPath = `/live2d/${rel}`
    try {
      const dictPath = join(root, 'model_dict.json')
      const dict = JSON.parse(readFileSync(dictPath, 'utf8')) as { models?: Record<string, unknown> }
      dict.models = dict.models ?? {}
      if (!dict.models[name]) {
        dict.models[name] = {
          name: rawName,
          author: '未登记',
          type: 'live2d',
          modelPath,
          license: '未登记（请自行确认授权）',
          origin: '本地导入',
        }
        writeFileSync(dictPath, `${JSON.stringify(dict, null, 2)}\n`, 'utf8')
      }
    } catch { /* 只读或解析失败：跳过登记 */ }
  }

  return {
    ok: true,
    dest,
    modelPath,
    report,
    message: `已导入 live2d/${name}（${report.info.textures.length} 张贴图 / ${report.info.expressions.length} 个表情 / ${report.info.motionGroups.reduce((s, g) => s + g.count, 0)} 个动作）`,
  }
}

/**
 * 窗口贴合模型时，底部为「输入胶囊 + 语音提示展开区」预留的高度（px）。
 *
 * 必须与渲染层 layout.ts 的 BOTTOM_RESERVE 保持一致：
 * 渲染层按 height - BOTTOM_RESERVE 计算模型可用高度，两者相等时模型 scale=1。
 *
 * 取 100 的原因：输入胶囊 42px + 语音提示向下展开区 ~44px + 边距。
 * 预留区完全透明、位于模型脚底之下，因此这些 UI 展开时不会遮住模型。
 */
const ISLAND_RESERVE_H = 100

/**
 * Transparent desktop-pet overlay window (AIRI window-contract pattern).
 * Visual-only, non-focusable, click-through, always-on-top.
 */
function createOverlayWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: petLayout.width,
    height: petLayout.height,
    show: false,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    roundedCorners: false,
    // 关键：必须 focusable:true，否则窗口内的 <input> 无法获得键盘焦点、无法输入。
    // 不抢焦点靠 showInactive() 实现（不主动抢占前台焦点）。
    focusable: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false,
      backgroundThrottling: false,
    },
  })
  petWindow = win

  // 初始【不穿透】（整个窗口可交互），让功能岛一定能点到；
  // 穿透交由渲染层按区域判断（鼠标在模型本体上时才穿透）。
  win.setIgnoreMouseEvents(false)
  win.setAlwaysOnTop(true, 'screen-saver')
  // 仅本地开发截图验收临时关闭，打包版始终保留保护。
  win.setContentProtection(!(process.env['YUIRO_UI_CAPTURE']==='1'&&!app.isPackaged))
  if (process.platform === 'darwin') {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  }
  win.showInactive()
  // Windows 显示/重建透明窗口后重申捕获保护，不能只在创建前设置。
  const protectCapture=()=>{if(!win.isDestroyed())win.setContentProtection(!(process.env['YUIRO_UI_CAPTURE']==='1'&&!app.isPackaged))}
  protectCapture()
  win.on('show',protectCapture)
  win.webContents.on('did-finish-load',protectCapture)

  // 调试：F12 打开 DevTools（detach 模式，避免抢占透明窗口空间）
  win.webContents.on('before-input-event', (_e, input) => {
    if (input.key === 'F12' && input.type === 'keyDown') {
      if (win.webContents.isDevToolsOpened()) win.webContents.closeDevTools()
      else win.webContents.openDevTools({ mode: 'detach' })
    }
  })
  // 渲染进程崩溃 / 加载失败定位白屏
  win.webContents.on('did-fail-load', (_e, errorCode, errorDescription, validatedURL) => {
    console.error('[main] pet 渲染进程加载失败', errorCode, errorDescription, validatedURL)
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    console.error('[main] pet 渲染进程崩溃', details.reason, details.exitCode)
  })
  // 转发渲染层 console.* 到主进程终端（pnpm dev 直接可见，无需 F12）。
  // Electron 33 实际触发旧式 (event, level, message, line, sourceId)，兼容对象形式。
  win.webContents.on('console-message', (_e, levelOrDetail: any, messageOrUndef?: any) => {
    // 旧式：args = (event, level:number, message:string, line:number, sourceId:string)
    if (typeof levelOrDetail === 'number') {
      const lv = levelOrDetail
      const msg = String(messageOrUndef ?? '')
      const tag = lv === 2 ? '[render:error]' : lv === 1 ? '[render:warn]' : '[render]'
      if (msg) console.log(`${tag} ${msg}`)
      return
    }
    // 对象形式：args = (event, MessageDetails)
    const msg = typeof levelOrDetail === 'object' && levelOrDetail
      ? String((levelOrDetail as any).message ?? '') : ''
    if (msg) console.log(`[render] ${msg}`)
  })

  if (process.env['ELECTRON_RENDERER_URL']) {
    win.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
  return win
}

let tray: Tray | null = null

/** 悬停渐隐是否处于开启态（渲染层经 IPC 上报，供托盘菜单动态显示逃生项）。 */
let fadeOn = false

/** 当前审批模式（auto 自动通过 / manual 人工审批弹窗），供托盘菜单显示勾选态。 */
let approvalMode = 'auto'

/** 引擎 debug API base（与渲染层 shared/config.ts 保持一致）。 */
const ENGINE_DEBUG_BASE = 'http://127.0.0.1:8200'

/** 主进程直接调用引擎 debug API 切换审批模式（实时生效，不落盘）。 */
async function setEngineApprovalMode(mode: string): Promise<void> {
  try {
    await fetch(`${ENGINE_DEBUG_BASE}/api/systemd/approval-mode`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_mode: mode }),
    })
    approvalMode = mode
  } catch (e) {
    console.error('[yuiro-main] 切换审批模式失败:', e)
    dialog.showErrorBox('切换审批模式失败', String(e))
  }
  refreshTray()
}

/** 重建托盘菜单（状态变化后调用，刷新勾选态）。 */
function refreshTray(): void {
  if (tray) tray.setContextMenu(buildTrayMenu())
}

/** 启动时同步引擎当前审批模式到托盘菜单勾选态。 */
async function syncEngineApprovalMode(): Promise<void> {
  try {
    const res = await fetch(`${ENGINE_DEBUG_BASE}/api/systemd/approval-mode`)
    const body = (await res.json()) as { approval_mode?: string }
    if (body?.approval_mode) approvalMode = body.approval_mode
  } catch { /* 引擎未起，忽略；托盘用默认 auto */ }
  refreshTray()
}

/**
 * 托盘菜单：悬停渐隐作为常驻切换项始终存在（开→关、关→开）。
 * 渐隐开启后窗口 click-through、渲染层点不动，托盘是无需进入窗口即可切换的逃生通道。
 */
function buildTrayMenu(): Menu {
  const items: MenuItemConstructorOptions[] = []
  items.push({
    label: fadeOn ? '关闭悬停渐隐' : '开启悬停渐隐',
    click: () => {
      // 托盘点击 → 直接向渲染层发 fade:set（与渲染层 onFadeSet 监听的通道一致），
      // 渲染层 setEnabled 切换 localStorage 后会经 fade:state 上报回来刷新 fadeOn 与菜单文案。
      // 注意：通道必须是 'fade:set'（曾误用 'fade:toggle' 导致渲染层收不到、托盘切换失效）。
      const target = !fadeOn
      if (petWindow && !petWindow.isDestroyed()) {
        petWindow.webContents.send('fade:set', target)
        // 兜底：关闭时主进程直接关穿透，避免渲染层链路异常导致窗口卡死穿透态。
        if (!target) petWindow.setIgnoreMouseEvents(false)
      }
    },
  })
  items.push({ type: 'separator' })
  items.push({
    label: '审批模式',
    submenu: [
      {
        label: '自动审批（完全开放）',
        type: 'radio',
        checked: approvalMode === 'auto',
        click: () => setEngineApprovalMode('auto'),
      },
      {
        label: '人工审批（弹窗确认）',
        type: 'radio',
        checked: approvalMode === 'manual',
        click: () => setEngineApprovalMode('manual'),
      },
    ],
  })
  items.push({ type: 'separator' })
  // 修复：托盘"设置"此前 app.emit('open-settings') 无监听器（断点），
  // 改为直接打开调试窗口（settings 页）。
  items.push({ label: '设置', click: () => createDevWindow('settings') })
  items.push({ type: 'separator' })
  items.push({ label: '退出', click: () => app.quit() })
  return Menu.buildFromTemplate(items)
}

function createTray(): void {
  tray = new Tray(nativeImage.createEmpty())
  tray.setToolTip('Yuiro 桌宠')
  tray.setContextMenu(buildTrayMenu())
}

/** 悬停渐隐：仅接收渲染层上报状态（刷新托盘菜单项文案）。 */
function registerFadeEscape(): void {
  // 渲染层 fadeEnabled 变化上报 → 更新 fadeOn 并刷新托盘菜单文案。
  ipcMain.on('fade:state', (_e, enabled: boolean) => {
    fadeOn = !!enabled
    if (tray) tray.setContextMenu(buildTrayMenu())
  })
}

// ---------------------------------------------------------------------------
// 开发者调试窗口（从桌宠功能岛「设置 / 日志」打开）
// ---------------------------------------------------------------------------
export type DevSection = 'settings' | 'logs' | 'status'

let devWindow: BrowserWindow | null = null

function createDevWindow(section: DevSection = 'settings'): BrowserWindow {
  if (devWindow && !devWindow.isDestroyed()) {
    if (devWindow.isMinimized()) devWindow.restore()
    devWindow.focus()
    return devWindow
  }
  devWindow = new BrowserWindow({
    width: 980,
    height: 720,
    minWidth: 720,
    minHeight: 520,
    title: 'Yuiro 开发者调试台',
    backgroundColor: '#0b0b0f',
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false,
      backgroundThrottling: false,
    },
  })
  if (process.env['ELECTRON_RENDERER_URL']) {
    devWindow.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/dev.html?section=${section}`)
  } else {
    devWindow.loadFile(join(__dirname, '../renderer/dev.html'), { query: { section } })
  }
  devWindow.on('closed', () => {
    devWindow = null
  })
  return devWindow
}

// ---------------------------------------------------------------------------
// S51：日记编辑窗口（独立窗口）
//
// 为什么必须是**独立窗口**而不是聊天坞内嵌：日记输入**不走 AgentLoop**
// （日记正文里的"记事本/微信"这类裸名词会被预路由当成指令，真的去打开应用），
// 物理分离能让这条边界一眼可见、也避免用户误以为在"跟她说话"。
// ---------------------------------------------------------------------------
let diaryWindow: BrowserWindow | null = null

function createDiaryWindow(): BrowserWindow {
  if (diaryWindow && !diaryWindow.isDestroyed()) {
    diaryWindow.show()
    diaryWindow.focus()
    return diaryWindow
  }
  const diaryArea=(petWindow?screen.getDisplayMatching(petWindow.getBounds()):screen.getPrimaryDisplay()).workAreaSize
  diaryWindow = new BrowserWindow({
    width:Math.min(900,diaryArea.width-16),
    height:Math.min(760,diaryArea.height-16),
    minWidth:Math.min(380,diaryArea.width-16),
    minHeight: 520,
    title: 'Yuiro 日记',
    // 纸面配色：系统标题栏会立刻把"一张纸"打回"工具窗口"，改成隐藏标题栏 +
    // 原生窗口按钮覆盖层（Windows 由系统绘制，行为可靠、仍是原生控件）。
    backgroundColor: '#f4eee3',
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#f4eee3', symbolColor: '#6b6156', height: 40 },
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      sandbox: false,
      backgroundThrottling: false,
    },
  })
  if (process.env['ELECTRON_RENDERER_URL']) {
    diaryWindow.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/diary.html`)
  } else {
    diaryWindow.loadFile(join(__dirname, '../renderer/diary.html'))
  }
  diaryWindow.on('closed', () => {
    diaryWindow = null
  })
  return diaryWindow
}

function registerDevWindow(): void {
  ipcMain.handle('dev:open', (_e, section: string = 'settings') => {
    const s: DevSection = section === 'logs' || section === 'status' ? section : 'settings'
    createDevWindow(s)
  })

  ipcMain.handle('diary:open', () => {
    createDiaryWindow()
  })

  // S51：日记窗口 → 桌宠窗口的聊天转发（用户要求：日记里每写一段就让她接话）。
  // 必须绕这一跳，不能让日记窗口自己发 chat:user：引擎的 chat:assistant 只回
  // **发起连接**，且 _control_conns 按 session 存单个连接 —— 日记窗口自己发会开
  // 新 session，回复接不上桌宠的 history、也显示不到桌宠窗口（气泡/口型在那边）。
  ipcMain.on('diary:appearance',(e,value:{skin:string;theme:string})=>{
    if(!diaryWindow||e.sender!==diaryWindow.webContents||!value||!['cream','lily'].includes(value.skin)||!['light','dark'].includes(value.theme))return
    const dark=value.theme==='dark',lily=value.skin==='lily'
    const color=dark?(lily?'#1b2229':'#221e19'):(lily?'#f6f8f8':'#fbf4e6')
    diaryWindow.setBackgroundColor(color)
    if(process.platform==='win32')diaryWindow.setTitleBarOverlay({color,symbolColor:dark?'#edf4f1':'#35434c',height:40})
  })

  ipcMain.handle('diary:relay-chat', (_e, text: string) => {
    const t = String(text || '').trim()
    if (!t) return false
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.webContents.send('pet:relay-chat', t)
      return true
    }
    return false
  })

  // S53：桌宠 → 日记窗口的**回复回传**（写作页的"页边批注"）。
  // 日记窗口的 WS 连接拿不到桌宠 session 的 chat:assistant（引擎只回发起连接），
  // 所以由桌宠窗口把它这一轮的回复转回来；只转日记转发引发的那一轮，
  // 普通聊天不会串进日记窗口（"是否日记轮"由桌宠侧标记）。
  ipcMain.handle('diary:relay-reply', (_e, text: string) => {
    const t = String(text || '').trim()
    if (!t) return false
    if (diaryWindow && !diaryWindow.isDestroyed()) {
      diaryWindow.webContents.send('diary:reply', t)
      return true
    }
    return false
  })

  // 引擎 WS 鉴权用的共享密钥（来自启动环境 YUIRO_SHARED_SECRET）。
  // 渲染层连引擎时以 ?secret= 查询参数携带，避免明文硬编码在前端代码中。
  ipcMain.handle('engine:secret', () => {
    return process.env['YUIRO_SHARED_SECRET'] || ''
  })

  /**
   * S51：用**系统默认浏览器**打开外部链接（联网检索来源卡的"点击核验"）。
   *
   * 为什么必须走主进程：桌宠窗口是透明置顶覆盖层，渲染进程里 `window.open`
   * 会被 Electron 当成"再开一个 Electron 窗口"，而不是用户想要的浏览器。
   * 只放行 http/https —— 避免 file:// 或自定义协议被网页内容利用（提示注入面）。
   */
  ipcMain.handle('shell:open-external', (_e, url: string) => {
    const u = String(url ?? '').trim()
    if (!/^https?:\/\//i.test(u)) return { ok: false, note: '仅支持 http/https 链接' }
    void shell.openExternal(u)
    return { ok: true }
  })

  // 以已夹紧的DIP设置为真相源。分数DPI的原生往返取整不能反写设置，否则每次读取都会漂移。
  ipcMain.handle('dev:get-pet-layout', () => ({ ...petLayout }))

  ipcMain.handle('dev:set-pet-layout', (
    _e,
    next: { width: number; height: number; fillRatio: number; xOffset: number; yOffset: number },
    // persist=false 用于滑杆**拖动过程中**的连续提交：窗口要跟手，但不必每次写盘
    //（拖一次会触发上百次提交，每次都同步写 shell-ui.json 很浪费）。松手时再落盘。
    persist = true,
  ) => {
    // 归一化（非法值回退、越界夹紧）后落盘，保证每次启动沿用同一份外观
    Object.assign(petLayout, sanitizePetLayout({ ...petLayout, ...next }))
    petLayoutConfigured=true
    // 与 fit-to-model 同一条防线：手动调尺寸也不许超出屏幕工作区，
    // 否则窗口会被推到屏幕外（用户侧表现为"设了却看不见/位置不对"）。
    const fit = clampToWorkArea(petLayout.width, petLayout.height)
    if (fit.clamped) {
      console.log(`[window] 手动尺寸超出屏幕，已夹紧 ${petLayout.width}×${petLayout.height} → ${fit.width}×${fit.height}`)
      petLayout.width = fit.width
      petLayout.height = fit.height
    }
    if (persist) saveUiSettings()
    if (petWindow) {
      const bounds=petWindow.getBounds(),area=screen.getDisplayMatching(bounds).workArea
      petWindow.setBounds({width:petLayout.width,height:petLayout.height,x:Math.round(Math.max(area.x+8,Math.min(bounds.x,area.x+area.width-petLayout.width-8))),y:Math.round(Math.max(area.y+8,Math.min(bounds.y,area.y+area.height-petLayout.height-8)))})
      petWindow.webContents.send('shell:event', {
        type: 'appearance:update',
        ...petLayout,
      })
    }
    return { ...petLayout }
  })

  // 窗口贴合模型：模型加载后渲染层上报实际尺寸，窗口 resize 为
  // 模型尺寸 + 底部功能区余量（ISLAND_RESERVE），实现"窗口 ≈ 模型"。
  ipcMain.handle('window:fit-to-model', (_e, size: { width: number; height: number }) => {
    if(petLayoutConfigured)return { ...petLayout } // 首次自动贴合不得覆盖已保存/手调尺寸。
    const w = Math.round(Number(size?.width) || petLayout.width)
    const h = Math.round(Number(size?.height) || petLayout.height)
    if (w < 80 || h < 80 || w > 1600 || h > 1600) return  // 异常值防御
    // 贴合尺寸不得超出屏幕工作区：模型原始尺寸可能比屏幕还大（shizuku 1280×1380），
    // 否则窗口会被顶到屏幕外、模型看不见（"只有这个模型加载不出来"）。
    // 夹紧多出的空间由渲染层按可用区自动等比缩小模型。
    const fit = clampToWorkArea(w, h + ISLAND_RESERVE_H)
    if (fit.clamped) {
      console.log(`[window] 贴合尺寸超出屏幕：${w}×${h + ISLAND_RESERVE_H} → ${fit.width}×${fit.height}（模型按可用区缩放）`)
    }
    petLayout.width = fit.width
    petLayout.height = fit.height
    petLayout.fillRatio = 1  // 贴合 = 一比一占满（缩放系数归一）
    saveUiSettings()         // 贴合结果也落盘，下次启动首个画面尺寸即正确
    if (petWindow) {
      petWindow.setSize(petLayout.width, petLayout.height)
      petWindow.webContents.send('shell:event', {
        type: 'appearance:update',
        ...petLayout,
      })
    }
  })

  // ── 桌宠形象控制（调试台「外观」页 → 桌宠窗口）──
  // 统一复用 shell:event 广播，与 appearance:update 同一范式。
  const sendToPet = (event: ShellEvent): void => {
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.webContents.send('shell:event', event)
    }
  }

  /** 扫描 live2d 目录，供调试台列出「自己丢进来的模型」。 */
  ipcMain.handle('live2d:scan-models', () => scanLive2dModels())

  /**
   * 模型清单（语义槽位推断）：读 model3.json + 每个 motion3 的 Meta，
   * 输出「槽位 → 具体资源」的索引，供渲染层把引擎的语义意图解析成实际调用。
   */
  ipcMain.handle('live2d:inspect-model', (_e, p: string) => inspectModel(String(p ?? '').trim()))

  // ── 模型体检 / 导入（S49）──
  /** 体检一个模型目录或 model3.json（只读，不抛错）。 */
  ipcMain.handle('dev:validate-model', (_e, p: string) => validateModel(String(p ?? '').trim()))

  /** 选一个目录（导入模型用）。 */
  ipcMain.handle('dev:pick-model-dir', async () => {
    const win = petWindow ?? BrowserWindow.getAllWindows()[0]
    const r = await dialog.showOpenDialog(win, {
      title: '选择 Live2D 模型目录',
      properties: ['openDirectory'],
    })
    return { canceled: r.canceled, path: r.filePaths?.[0] ?? '' }
  })

  /**
   * S54：通用文件/目录选择（TTS 参考音频/转写、知识库导入都走这里）。
   *
   * 为什么要有它：这些字段此前是**纯文本输入框**，用户得手敲绝对路径
   * （还得记住斜杠方向），实测极易填错。改为系统选择框后路径天然正确。
   * 知识库与 TTS 的差别只在 `multiple`：TTS 只需单一参考，知识库支持多选。
   */
  ipcMain.handle('dev:pick-files', async (_e, opts?: PickFilesOptions) => {
    const win = petWindow ?? BrowserWindow.getAllWindows()[0]
    const kind = opts?.kind ?? 'any'
    const filters =
      kind === 'audio'
        ? [{ name: '音频', extensions: ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'aac'] }]
        : kind === 'text'
          ? [{ name: '文本', extensions: ['txt', 'md', 'csv', 'json', 'log'] }]
          : undefined
    const properties: Array<'openFile' | 'openDirectory' | 'multiSelections'> = []
    if (opts?.directory) properties.push('openDirectory')
    else {
      properties.push('openFile')
      if (opts?.multiple) properties.push('multiSelections')
    }
    const r = await dialog.showOpenDialog(win, {
      title: opts?.title ?? '选择文件',
      properties,
      ...(filters ? { filters } : {}),
    })
    return { canceled: r.canceled, paths: r.filePaths ?? [] }
  })

  /** 导入模型目录（体检 → 复制 → 登记）。 */
  ipcMain.handle('dev:import-model', (_e, p: string, name?: string) => importModelDir(String(p ?? '').trim(), name))

  /** 更换 Live2D 模型（path 为 public 下的 model3.json 路径）。 */
  ipcMain.handle('dev:set-pet-model', (_e, path: string, characterId?: string) => {
    const p = String(path ?? '').trim()
    if (!p) return { ok: false }
    sendToPet({ type: 'avatar:model', path: p, characterId })
    return { ok: true, path: p }
  })

  /**
   * 试演一次成套表演（S49）：表情 + 动作 + 时长一次下发。
   * 调试台自己解析表演（它手上有引擎的表演库与当前模型明细），所以**不依赖引擎在线**。
   */
  ipcMain.handle('dev:apply-intent', (_e, payload: {
    characterId?: string
    modelPath?: string
    name?: string
    expression?: string
    motion?: string
    motionIndex?: number | null
    durationMs?: number
  }) => {
    sendToPet({ type: 'avatar:perform', ...(payload ?? {}) })
    return { ok: true }
  })

  /** 试播一个动作（index 省略 = 该组内随机）。 */
  ipcMain.handle('dev:play-motion', (_e, group: string, index?: number, context?: { characterId?: string; modelPath?: string }) => {
    const g = String(group ?? '').trim()
    if (!g) return { ok: false }
    sendToPet({
      type: 'avatar:motion',
      ...context,
      group: g,
      ...(typeof index === 'number' ? { index } : {}),
    })
    return { ok: true }
  })

  /** 预览一个表情。 */
  ipcMain.handle('dev:play-expression', (_e, name: string, context?: { characterId?: string; modelPath?: string }) => {
    const n = String(name ?? '').trim()
    if (!n) return { ok: false }
    sendToPet({ type: 'avatar:expression', name: n, ...context })
    return { ok: true }
  })
}

/** 在输入框聚焦时关闭点击穿透(可交互)，失焦时恢复(桌宠不挡鼠标)。 */
function registerMousePassthrough(): void {
  // 用 ipcMain.on + event.returnValue，让 preload 的 sendSync 能同步返回（否则阻塞/穿透不生效）
  ipcMain.on('mouse:passthrough', (e, passthrough: boolean) => {
    e.returnValue = true
    if (!petWindow || e.sender !== petWindow.webContents) return
    // 关闭穿透时不能带 forward，否则 Windows 上 click 仍可能漏过
    if (passthrough) {
      petWindow.setIgnoreMouseEvents(true, { forward: true })
    } else {
      petWindow.setIgnoreMouseEvents(false)
    }
    // 切换透明窗口的鼠标样式后再次落实保护。
    petWindow.setContentProtection(!(process.env['YUIRO_UI_CAPTURE']==='1'&&!app.isPackaged))
  })
}

/** overlay 坐标流：~60fps 推鼠标 screen 坐标 + 窗口 bounds 给渲染层做"悬停渐隐"判定。 */
let overlayTimer: NodeJS.Timeout | null = null
function startOverlayTracking(): void {
  if (overlayTimer) return // 互斥防重入（单窗口，天然单消费者）
  console.log('[main] overlay tracking start')
  overlayTimer = setInterval(() => {
    if (!petWindow || petWindow.isDestroyed()) return
    try {
      // Retain legacy DIP fields; normalized physical fractions also work across mixed-DPI displays.
      petWindow.webContents.send('overlay:cursor', overlayCursor(screen,petWindow))
      const b = petWindow.getBounds() // DIP
      petWindow.webContents.send('overlay:bounds', { x: b.x, y: b.y, width: b.width, height: b.height })
    } catch (e) {
      console.error('[main] overlay tick failed:', e)
    }
  }, 1000 / 60)
}
function stopOverlayTracking(): void {
  if (overlayTimer) { clearInterval(overlayTimer); overlayTimer = null; console.log('[main] overlay tracking stop') }
}

function registerOverlayTracking(): void {
  ipcMain.handle('overlay:tracking-start', () => {
    if (!overlayTimer) startOverlayTracking()
    return true
  })
}

/** 对话输入时聚焦窗口（窗口已常驻 focusable:true，这里只负责聚焦）。 */
function registerFocusableToggle(): void {
  ipcMain.on('window:focusable', (_e, focusable: boolean) => {
    if (!petWindow) return
    // 窗口保持 focusable:true（否则 <input> 无法输入）；此处仅按需聚焦
    if (focusable) petWindow.focus()
  })
}

/**
 * JS 拖动（三阶段，主进程读 OS 光标绝对坐标）。
 *
 * 防「长按膨胀/瞬移」的关键（见 debug-log 第 28 篇坑 B/C）：
 * - 用 `screen.getCursorScreenPoint()` 与 `getBounds()/setBounds()` 同一物理像素坐标系，
 *   渲染层不参与坐标换算 → 零累积误差、零瞬移。
 * - `drag-move` 一律 `setBounds({ x, y, width, height })` **显式钉死**拖动开始时的真实尺寸，
 *   绝不用 `setPosition`——Windows 下 transparent+autoDensity 会让 setPosition 每帧偷偷啃大
 *   窗口尺寸，长按即逐渐膨胀（坑 C）。
 */
function registerPetDrag(): void {
  let dragging = false
  let offsetX = 0
  let offsetY = 0
  let dragStartW = 0
  let dragStartH = 0

  ipcMain.on('window:drag-start', (e) => {
    e.returnValue = true
    if (!petWindow || petWindow.isDestroyed()) return
    const bounds = petWindow.getBounds()
    const cursor = screen.getCursorScreenPoint()
    // 记录窗口左上角相对光标的偏移 + 拖动开始时的真实尺寸
    offsetX = cursor.x - bounds.x
    offsetY = cursor.y - bounds.y
    dragStartW = bounds.width
    dragStartH = bounds.height
    dragging = true
    console.log('[main] drag-start bounds', bounds, 'offset', offsetX, offsetY)
  })

  ipcMain.on('window:drag-move', (e) => {
    e.returnValue = true
    if (!petWindow || petWindow.isDestroyed() || !dragging) return
    const cursor = screen.getCursorScreenPoint()
    const nx = cursor.x - offsetX
    const ny = cursor.y - offsetY
    // 关键：setBounds 同时钉死尺寸，杜绝 setPosition 的尺寸漂移膨胀
    petWindow.setBounds({
      x: Math.round(nx),
      y: Math.round(ny),
      width: dragStartW,
      height: dragStartH,
    })
  })

  ipcMain.on('window:drag-end', (e) => {
    e.returnValue = true
    dragging = false
  })
}

/** Route engine approval requests through a native dialog. */
function registerApprovalHandler(): void {
  ipcMain.handle(
    'approval:required',
    async (_e: IpcMainInvokeEvent, request: { approvalRequestId: string, tool: string, summary: string }) => {
      // 对话框异常时兜底为「拒绝」，确保渲染进程的 resolve 一定会发送，
      // 不会因 handler reject 导致引擎审批永久超时。
      try {
        const { response } = await dialog.showMessageBox({
          type: 'question',
          buttons: ['允许', '拒绝'],
          title: `Yuiro 请求: ${request.tool}`,
          message: `${request.summary}\n\n工具参数已记录（可在引擎审计查看）。`,
          defaultId: 0,
          cancelId: 1,
        })
        const approved = response === 0
        console.log(`[approval] dialog resolved: ${request.tool} -> ${approved ? '允许' : '拒绝'}`)
        return { requestId: request.approvalRequestId, approved }
      } catch (err) {
        console.error('[approval] dialog error, default deny:', err)
        return { requestId: request.approvalRequestId, approved: false }
      }
    },
  )
}

app.whenReady().then(() => {
  // 麦克风权限：透明无边框桌宠窗口的 getUserMedia 若无此授权会被默认拒绝，
  // 导致语音「开启后自然收起」。这里显式放行 media（麦克风）请求。
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'media')
  })
  // 先恢复上次的窗口外观，再创建窗口 —— 这样首帧尺寸就是用户调过的
  loadUiSettings()
  registerApprovalHandler()
  registerMousePassthrough()
  registerFocusableToggle()
  registerPetDrag()
  registerDevWindow()
  registerOverlayTracking()
  registerFadeEscape()
  registerDetachedUi(()=>petWindow)
  createOverlayWindow()
  createTray()
  syncEngineApprovalMode()
})

app.on('before-quit', () => {
  stopOverlayTracking()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
