# Fade on Hover —— Yuiro 迁移提示词套件

> 将 AIRI（moeru-ai/airi，stage-tamagotchi）的"鼠标靠近后窗口渐隐、不影响定点点击"功能迁移到 **Yuiro**（`shell/` Electron + Vue3 + TS）。
> 以 Yuiro 当前实现情况（M0/M1 骨架 + 已可用的穿透/拖动/悬停基础设施）为基准，按序投喂给 AI 助手（Claude Code / Codex / opencode）。

## 前置结论：与 AIRI 的差异（决定怎么改）

| 维度 | AIRI 参考 | Yuiro 现状 | 迁移对策 |
|---|---|---|---|
| 前端框架 | Vue3 + Pinia + VueUse | **Vue3 + TS**（`useAppearance`/`usePetDrag` 同款写法） | 直接写成 Vue composable，风格对齐现有文件 |
| IPC | eventa 类型化总线 + `@proj-airi/electron-vueuse` | **原生 `ipcMain`/`ipcRenderer`** + 预加载桥 `window.yuiro` | 用现有 `shell:event` 总线 + 新增预加载方法；不引入 eventa |
| 穿透通道 | `electron.window.setIgnoreMouseEvents` invoke | **已有 `mouse:passthrough` 同步通道**（`setMousePassthrough`，开启带 `forward:true`） | 直接复用 |
| 渲染器 | Live2D(WebGL) + VRM(Three.js) 双路径 | **仅 Live2D（PixiJS v7 + pixi-live2d-display）** | 只做 WebGL 像素采样路径；`preserveDrawingBuffer:true` 已在 `Live2DCanvas.vue` 就位 |
| 模型包围盒 | 无（靠像素采样） | **已有 `Live2DCanvas.getModelRect()`**（client 坐标、响应式） | 用作采样前置粗筛（快路径） |
| 现有穿透逻辑 | 开启后整窗常驻穿透 | `useMousePassthrough` 是"按下时点击穿透 300ms" | 开启本功能后让位给本功能的状态机 |
| 测试 | Vitest | **shell 无测试框架**（仅 `pnpm typecheck`） | 验收以 typecheck + 人工清单为主；纯函数可选加 vitest |
| 文案 | i18n | **中文硬编码**（AGENTS.md 约定 UI 用中文） | 直接写中文，不引 i18n 库 |
| 依赖 | es-toolkit 等 | 仅 `@vueuse/core` + animejs + pinia | 用 VueUse（`useLocalStorage`/`refDebounced`）+ 原生 JS |

> 参考源码（AIRI）：`apps/stage-tamagotchi/src/renderer/pages/index.vue`（决策状态机）、`packages/stage-ui/src/composables/canvas-alpha.ts`（像素采样）、`packages/electron-vueuse/src/composables/*`（鼠标/窗口坐标流）、`apps/stage-tamagotchi/src/main/services/electron/screen.ts` + `window.ts`（60fps 数据流）。

---

## Prompt 0：功能规格（先读，用于上下文与最终验收）

```
我在开发 Yuiro 桌宠（Electron + Vue3 + TS，目录 shell/）。请实现并落地"Fade on Hover"功能，参考开源项目 AIRI
的同名特性：鼠标靠近桌宠后窗口内容渐隐，使鼠标能准确点击被桌宠挡住的桌面内容。

功能需求：
1. 主窗口为透明无边框 BrowserWindow（shell/src/main/index.ts 已配置：transparent、frame:false、focusable:true、
   showInactive、初始 setIgnoreMouseEvents(false)）。本功能不改动这些基础配置。
2. 用户可开关该功能（默认关闭），偏好持久化到 localStorage。
3. 开启后：窗口进入"点击穿透"模式（复用现有 mouse:passthrough 通道，setIgnoreMouseEvents(true, { forward: true })），
   整个窗口不再拦截鼠标点击；鼠标移动事件仍由 forward:true 转发进渲染进程供检测使用。
4. 当鼠标位于窗口内、且光标正下方是"Live2D 模型不透明区域"时，窗口内 UI（模型画布、括号菜单、气泡等）以 CSS
   opacity 渐隐（约 250ms），让用户看到并点击被遮挡内容；光标移到透明区域或移出窗口时 UI 恢复。
5. 例外（保持可交互、不穿透、不渐隐）：
   - 聊天面板 / 设置面板 / 括号菜单打开时（复用 App.vue 现有 activePanel、menuOpen）；
   - 鼠标位于窗口边缘 10px 范围内（保留边缘拖动/缩放能力）；
   - 鼠标位于任何可交互 UI（面板、功能泡）内时（250ms 防抖，防掠过闪烁）。
6. 模型边缘快速移动不能闪抖：透明度检测用"光标周围半径 25px 圆形区域采样 + alpha 阈值 10"，而非单像素。
7. 已知取舍：开启后模型本体不可再按住拖动（窗口常驻穿透，mousedown 不送达）；移动桌宠靠窗口边缘拖动/托盘。
   请把这个取舍写清楚，不要试图"既要穿透又要本体可拖"而引入闪烁。
8. 首次开启前弹一个应用内确认弹层（不新开窗口），确认后才启用；支持"不再显示"。

交付要求：
- 先输出实现方案（文件划分、数据流、状态机、与现有 useMousePassthrough/usePetDrag/useBracketMenu 的协作），我确认后再写代码。
- 代码风格对齐 shell/src/renderer/src/composables/ 现有文件（中文注释、console 带 [模块名] 前缀）。
- 文案直接写中文，不引 i18n 库。
```

---

## Prompt 1：主进程地基（60fps 光标/窗口坐标流）

```
在 shell/src/main/index.ts 增加"光标 + 窗口坐标"高频数据流（参考 AIRI screen.ts/window.ts 的 createRendererLoop），
供渲染层做 Fade on Hover 检测。当前已有：registerMousePassthrough（mouse:passthrough 同步通道，开穿透带 forward:true）、
registerPetDrag（拖动时主进程读 screen.getCursorScreenPoint()）。

要求：
1. 新增一个按需启动的 ~60fps 定时器循环（setInterval 1000/60 即可；必要时加互斥防重入）：
   - 每次 tick 读 screen.getCursorScreenPoint()（物理/DIP 坐标）与 petWindow.getBounds()；
   - 通过 petWindow.webContents.send 推给渲染进程：光标 {x,y} 与窗口 bounds {x,y,width,height}。
     两个事件共用或分用新通道均可（如 'overlay:cursor' / 'overlay:bounds'）。
2. 循环只在实际需要时运行：渲染层首次请求（ipcMain.handle('overlay:tracking-start')）时启动；
   应用退出（app 'before-quit' / 'window-all-closed'）时 clearInterval。
3. 坐标语义：getCursorScreenPoint 与 getBounds 同为 DIP，相减即窗口相对坐标，与渲染层 clientX/Y 一致；
   严禁让渲染层用 window.screenX 反推（见 docs/debug-log.md 坑 B：CSS 逻辑像素与物理像素混用会累积漂移）。
4. 校验只允许 petWindow 自己的 webContents 消费这些事件（当前是单窗口，做来源过滤即可）。
5. 完成后跑 pnpm typecheck 必须通过；给渲染层发的每个事件 console 一行 [main] 日志便于排查。
```

---

## Prompt 2：渲染层鼠标追踪 composables

```
在 shell/src/renderer/src/composables/ 新增一组"Electron 鼠标/窗口坐标"composable（参考 AIRI electron-vueuse 系列，
但用本项目原生 IPC + Vue 风格实现）。风格对齐现有 useAppearance.ts（模块级单例 state + listening 标志）。

1. useElectronMouse()：
   - 模块级单例：订阅 Prompt 1 推来的 'overlay:cursor'（经预加载桥，如 window.yuiro.onCursorPoint(cb)），
     转成响应式 {x, y}（screen 坐标）。建议用一个共享 EventTarget + 合成 mousemove 再消费，或直接 ref 更新。
   - 首次调用时向主进程请求启动追踪循环（window.yuiro.startOverlayTracking()）。
2. useElectronWindowBounds()：模块级单例，订阅 'overlay:bounds'，暴露 {x, y, width, height} 响应式。
3. useElectronRelativeMouse()：窗口相对坐标 = useElectronMouse 的坐标 − useElectronWindowBounds 的坐标（computed）。
4. useMouseInWindow() / useMouseInElement(target)：基于相对坐标 + getBoundingClientRect 判断 isOutside；
   元素尺寸变化（ResizeObserver）要重算；isOutside 用 refDebounced(250ms) 防抖后暴露。
5. useMouseAroundWindowBorder({ threshold: 10 })：光标距窗口任一边缘 ≤10px（允许略越界 overshoot）→ isNearAnyBorder。
6. 需要预加载桥新增方法：onCursorPoint(cb)、onWindowBounds(cb)、startOverlayTracking()（放 preload/index.ts 的 api 对象，
   类型对齐现有 YuiroBridge）。

先给出每个 composable 的返回值接口 + preload 改动清单，再实现。
```

---

## Prompt 3：Live2D 透明度命中测试（鼠标是否在模型本体上）

```
在 shell/src/renderer/src/composables/ 新增 useCanvasPixelIsTransparentAtPoint（参考 AIRI canvas-alpha.ts）。

背景：本项目渲染器只有 Live2D（PixiJS v7，pixi-live2d-display）。Live2DCanvas.vue 已设 preserveDrawingBuffer:true
（注释已说明为像素采样保留绘制缓冲），canvas 的 WebGL 上下文由 Pixi 持有——用 canvas.getContext('webgl2'||'webgl')
拿回的是同一个上下文，可直接 readPixels。

实现：
1. 输入：canvas 引用（live2d-canvas）、窗口相对坐标 x/y（来自 useElectronRelativeMouse）、options { threshold:10, regionRadius:25 }。
2. 把 client/相对坐标换算进 drawing buffer 空间：scaleX = gl.drawingBufferWidth / 元素CSS宽，scaleY 同理；
   像素 Y 需翻转：pixelY = drawingBufferHeight - 1 - yIn * scaleY（Pixi autoDensity + resolution≤2 时 DPI 缩放必须处理）。
3. 读取光标周围圆形区域（先 clamp 出方形 bbox 再 readPixels，CPU 端按 dx²+dy²≤r² 过滤方框边角），
   区域内任一像素 alpha >= threshold 即判定"不透明"（返回 false）；越界/上下文拿不到/异常一律返回 true（透明）。
4. 快路径优化：光标在 Live2DCanvas.getModelRect() 返回的模型包围盒之外时，直接返回 true，不做 GPU 读取
   （模型边缘附近才需要精确采样，避免 60fps 全屏读）。
5. 返回 Ref<boolean>（computed）：true=该处透明（应显示 UI），false=不透明（应渐隐）。
6. 用 console.debug('[fade] sample ...') 记录采样命中情况，便于终端排查（渲染层日志已转发主进程终端）。
```

---

## Prompt 4：决策状态机 + UI 渐隐（迁移核心）

```
在 shell/src/renderer/src/ 新增 useFadeOnHover composable + 一个纯决策函数，并在 App.vue 接入
（参考 AIRI pages/index.vue 的 watch 决策逻辑，但按 Yuiro 现有状态改写）。

纯决策函数（可单测）：
fadeOnHoverDecision(input: {
  fadeEnabled: boolean      // localStorage 开关
  mouseInWindow: boolean    // 鼠标是否在窗口内
  transparentAtCursor: boolean // Prompt 3 的结果（true=透明）
  nearBorder: boolean       // Prompt 2 的 isNearAnyBorder（250ms 防抖后）
  uiOpen: boolean           // activePanel !== null || menuOpen（聊天/设置面板/括号菜单打开）
}) => {
  interactive: boolean      // true=setIgnoreMouseEvents(false)、不渐隐
  shouldFade: boolean       // true=给 UI 加 opacity-0
}

优先级（命中即 interactive，短路）：
1. uiOpen                     → interactive=true,  shouldFade=false
2. nearBorder                 → interactive=true,  shouldFade=false   （保留边缘拖动/缩放）
3. 其余：                     → interactive = !fadeEnabled
                               shouldFade = fadeEnabled && mouseInWindow && !transparentAtCursor
注意：shouldFade 只在"鼠标在窗口内且光标不透明"时为真；光标在透明区域/窗口外 → 显示 UI。

composable useFadeOnHover：
- 输入：上述 refs（用 useElectronRelativeMouse / useMouseInWindow / useMouseAroundWindowBorder / getModelRect 组装），
  及 fadeEnabled（useLocalStorage('yuiro-fade-on-hover-enabled', false)）。
- watch 决策结果：
  - interactive → 调 window.yuiro.setMousePassthrough(false)（复用现有 mouse:passthrough 通道）；
  - 否则（fade 开启时）→ setMousePassthrough(true)（forward:true 已由主进程保证），并 resume 透明度采样；
  - fade 关闭时 pause 采样，避免无谓 GPU 读取。
- 用 pause()/resume() 门控 Prompt 3 的采样 watch（参考 AIRI index.vue 的做法）。

App.vue 接入：
- 新增 fadeOnHoverEnabled 开关状态 + useFadeOnHover 实例化；把 .pet 容器或模型画布外包一层 div，
  :class="shouldFade ? 'opacity-0' : 'opacity-100'" + transition: opacity 250ms ease-in-out。
- 与现有 useMousePassthrough 协作：fadeEnabled 开启期间，让 useMousePassthrough 的按下穿透逻辑让位
  （在其 uiActive()/onMouseDown 里加 fadeEnabled 短路），避免两套穿透打架。
- 开启状态下已知取舍（写进代码注释）：模型本体不可按住拖动（mousedown 不送达），移动靠窗口边缘拖动。
- 新增关键分支日志：[fade] interactive / [fade] shouldFade / [fade] decision。
```

---

## Prompt 5：偏好持久化 + 设置入口 + 首次确认弹层

```
实现 Fade on Hover 的用户入口（Yuiro 现有设置面板在 App.vue 的 activePanel==='settings'，是窗口内面板；
无独立通知窗口体系，用应用内弹层即可）。

1. 持久化：useLocalStorage('yuiro-fade-on-hover-enabled', false)（默认关）；
   另存 useLocalStorage('yuiro-fade-on-hover-dont-show-again', false)。
2. 在设置面板新增一行开关（复用现有 .setting-row + .toggle-btn 样式，与"主题"行一致）：
   - 显示当前状态；用 @iconify/vue + solar 图标（eye / eye-slash）体现开关；
   - 点击开启：若 dont-show-again 为 true 直接启用；否则弹"首次确认弹层"（新组件，覆盖层 + 说明文字
     + "不再显示"勾选 + 确认按钮），确认后才启用（即写入 fadeEnabled=true）。
   - 关闭：直接禁用。
3. 文案中文（AGENTS.md 约定）；弹层说明写清楚三点：开启后窗口不挡点击、悬停模型会渐隐、模型本体不可拖动。
4. 弹层做成 shell/src/renderer/src/components/FadeOnHoverNotice.vue（轻量，无额外依赖）。
```

---

## Prompt 6：验证与测试清单

```
实现完成后按以下清单验证（本 shell 无测试框架，验收以 pnpm typecheck + 人工走查为主；
纯决策函数若想加单测，可选引入 vitest，不强制）：

自动化：
1. pnpm typecheck（vue-tsc --noEmit）必须零错误。
2. 可选：给 fadeOnHoverDecision 纯函数加 vitest 单测，覆盖全部优先级分支
   （uiOpen × nearBorder × fadeEnabled × mouseInWindow × transparentAtCursor）。

人工走查（pnpm dev 后看终端日志，无需 F12）：
1. 设置面板开启本功能（首次弹确认层，确认后生效）；重启应用后开关状态保留。
2. 开启后桌宠下方桌面图标/窗口可被直接点击（整窗穿透）。
3. 鼠标移到模型本体上：UI 平滑渐隐（~250ms，日志出现 [fade] shouldFade）；移到透明处/移出窗口：恢复显示；
   快速划过模型边缘无明显闪抖（区域采样 25px 生效）。
4. 鼠标悬停模型 → 括号菜单仍能唤出（forward:true 转发 mousemove 生效）；悬停功能泡/打开聊天或设置面板 → 窗口可交互。
5. 鼠标贴窗口边缘 10px：出现边缘反馈并可拖动/缩放窗口。
6. 已知取舍确认：开启后按住模型本体不会拖动窗口（日志应无 [drag] start）；关闭本功能后拖动恢复。
7. 关闭本功能：行为完全回到现状（默认可交互、按下点击穿透 300ms 的旧逻辑恢复）。
```

---

## 迁移提示（重要）

- **IPC 别走 Python 后端**：Fade on Hover 是纯 Electron 能力，坐标流/穿透一律走主进程 ↔ 渲染进程 IPC，
  绝不经过 engine 的 WebSocket（延迟不可接受）。
- **`forward: true` 是命门**：穿透后没有它，渲染进程拿不到 mousemove，括号菜单/渐隐检测全冻结。
  现有 `mouse:passthrough` 开启时已带 forward:true，勿改坏。
- **DPI 铁律**（debug-log 坑 B）：坐标计算全在主进程 DIP 空间完成；渲染层只消费"已算好的相对坐标"和
  "getBoundingClientRect 的 CSS 尺寸"，绝不用 window.screenX 反推窗口位置。
- **性能**：60fps 光标/坐标流 + 区域采样在光标移动时高频触发。用 useFadeOnHover 的 pause()/resume() 门控 +
  Prompt 3 的 getModelRect 快路径，把 GPU readPixels 压缩到"鼠标确实在模型附近"时才发生。
- **穿透与拖动不可兼得**：开启本功能后 mousedown 不送达（forward 只转发 move），模型本体拖动必然失效；
  这是特性取舍不是 bug，注释里写明即可。若未来想两者兼得，需要"按住进入临时可交互"的过渡态，会引入闪烁，暂不做。
- **不改窗口基础配置**：focusable:true 是输入框能聚焦的前提（AGENTS.md/代码注释强调），穿透切换只动
  setIgnoreMouseEvents，不动 focusable。