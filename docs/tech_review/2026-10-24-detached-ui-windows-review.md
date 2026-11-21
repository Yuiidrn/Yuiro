# 回复与结果卡拆窗：实现过程与编码技术复盘

日期：2026-10-24。关联 [实施与实机验收](../plan/detached-ui-windows.md)。延续现有 Runtime，仅调整 Electron/Vue 呈现层与必要的输入坐标修正。

## 1. 为什么拆窗口，而不继续放大模型窗口

原气泡和结果卡分别在 `SpeechCloud/ResultCard` 中按 `window.innerWidth/innerHeight` 夹紧。模型窗口即使透明，DOM 也不能画到它外面；内容一多，两张卡最终会挤回角色身上。继续扩大同一个透明窗口会扩大输入/布局复杂度，也把模型缩放、消息宽度和交互范围耦合起来。

本轮让“模型承载窗口”和“信息呈现窗口”各做一件事。并未把 Live2D 拆成新渲染引擎，也没有让多窗口各自连接 Agent。

```text
Engine / 当前会话
       ↓
桌宠 App：回复/语音/结果的唯一所有者
       │ 快照 + 身份/内容 key + 模型 CSS 几何
       ↓
Electron coordinator：建窗、布局、隐藏、路由校验
       ├─ 回复窗口：文本 + 关闭
       └─ 结果窗口：复用来源/选歌组件 + 条目索引
                  ↓ action(key, index)
桌宠再次核验 → 当前原始条目 → 现有 openExternal / media:play
```

独立窗口是 owned top-level BrowserWindow，不是模型 DOM 的子节点；一个回复窗口、一个结果窗口，隐藏复用。新增的是 presenter，不是 Runtime。

## 2. 实现顺序和关键取舍

### 2.1 先保住业务调用链

`App.vue` 继续处理 Engine socket、TTS 播放和取消、结果过期、角色/session/revision。新入口 `detached.html → DetachedApp.vue` 不导入 Live2DCanvas、useVoiceInput 或引擎配置 Store。来源与选歌共用 ResultCard，新增 `detached` 模式解除原来的模型窗口内定位限制。

结果窗口只回传索引，不直接下发歌曲 JSON：用户点击的是当前那张卡的某一条，而不是“让模型再猜一次”。桌宠从当前 `resultCard.items[index]` 取原对象，沿用精确 ID 的 `pickResultItem` 路径。

### 2.2 用快照版本解决异步旧点击

窗口复用意味着上一角色的 renderer 还在。只清 DOM 不够，队列里的点击仍可能稍后到达。

`detachedSnapshot()` 在身份、session/revision、切换状态、结果或回复内容/可见性变化时生成新 key。主进程只接收 pet 的 publish；action 必须来自对应窗口，key 与当前一致，索引在范围内。桌宠处理 action 前重新计算身份键，再取自己的当前条目。

因此下列旧事件都是无效的：上一角色的点击、已经过期的卡片、替换前的回复关闭按钮、伪造窗口发送的命令。这个 key 是 UI 内容版本，不是认证令牌，也不替代引擎的 generation 协议。

### 2.3 先测量，再显示；位置与内容分开更新

新窗口初次启动可能错过第一条消息，因此由 renderer 主动 `ready`，主进程重放当前快照。renderer 在 Vue `nextTick` / ResizeObserver 后上报尺寸及 key，当前版本测量完成前主进程不显示新内容，避免以旧尺寸闪现。

App 以响应式 watch 加 100ms 几何兜底生成快照，序列化一致则不发送。原生拖动不等待这个轮询：主进程窗口 `move/resize` 直接按最近模型几何布局。`setBounds` 仅在整数边界确实变化时调用，避免尺寸—ResizeObserver—IPC 的空转。

权衡：当前按文字整体替换，而非跨窗口 token 级重绘。继续复用原回复生命周期，减少额外时序分支；并不因此宣称已测到完整端到端响应延迟。

### 2.4 布局在主进程，用显示器工作区而不是模型窗口边界

桌宠提供 CSS 模型矩形和 CSS viewport，主进程用 pet bounds / viewport 比率转换为屏幕 DIP。`placeDetached()` 是纯函数：

1. 尝试首选左右侧与偏移；
2. 尝试另一侧和上下方；
3. 两张卡同侧时尝试堆叠；
4. 夹紧到 workArea 后重新做模型/卡片交叉检测；
5. 无合法位置返回 null，隐藏而不覆盖角色。

重要的是“夹紧后再检查”，不能只把左侧越界位置 clamp 回来，否则恰好又压住模型。偏移是偏好，不是强制穿过模型的指令。避让依据模型可见包围盒，较 Alpha 轮廓更保守；轮廓只决定模型输入命中，不让消息在头发空隙里穿插。

## 3. 实机揭示的坑

### Windows 非焦点窗口：第一次可点不代表复用后可靠

初版设置 `focusable:false`，Hiyori 首次弹出可以关闭，但切换后 Hotaru 的 click 没有进入 DOM。记录原生 WindowFromPoint、页面 click、owner action 和 key，区分“鼠标没到页面”与“版本校验拒绝”。最终改成 `focusable:true`，自动显示仍用 `showInactive()`；因此出现时不抢键盘焦点，用户主动点击则可交互。主窗口父子 ownership 维护层级，不靠反复 focus。

### 自测尺寸的反馈锁

最初根容器 `max-width:100vw` 导致 170→280 的热更新只改变期望值，实际测量仍为旧窗口 170。窗口 resize 又依赖测量，于是永远无法长大。移除该约束，内容按偏好宽度测量，主进程再定窗；自动化同时断言 DOM 实际宽度与 alpha，不能只看 localStorage 已写入。

复用组件还要避免背景叠两层：结果窗口外壳保持透明，由 ResultCard 自己绘制配置的 alpha；回复窗口由外壳绘制背景。否则 0.65 叠 0.65 会变得接近不透明。两类固定样本截图已检查，见关联 plan。

### 清结果不是清所有呈现

原切换分支清了结果、停了音频，但纯文字气泡不一定消失。拆窗使这一遗漏更明显。三个身份失效入口显式 `hideSpeech()`，让计时器与可见性一起终止；没有在新窗口再加一份“角色清理逻辑”。

### CSS、DIP、物理屏幕像素要分清

页面缩放使 CSS px 与 DIP 不同；Windows 混合 DPI 又使各显示器 DIP 缩放基准不同。仅用 `devicePixelRatio` 全局相乘或简单减 DIP 原点都不稳。

- 消息窗口布局：模型 CSS → pet viewport 比率 → Electron DIP → workArea 布局。
- 鼠标命中：`dipToScreenPoint` / `dipToScreenRect(window, bounds)` 转到相同物理基准 → 窗口内归一化 u/v → renderer CSS。
- 旧 DIP 字段保留，旧 preload 情况可回退；窗口内检查也用 CSS viewport。
- 原生验收主线程和 underlay 线程均显式 per-monitor DPI aware；恢复尺寸走 Electron DIP API，Win32 仅用于物理定位/点击与观察。

这些是输入/呈现边界的局部修补，不是新的运行时协议。纯函数测试覆盖混合 DPI 映射、归一化优先、旧字段回退、负坐标显示器。

### 渐隐与外置 UI 不应互相追逐

模型下面的桌面需要让开，不代表移到旁边的回复也应该消失。外置气泡不再绑定 `shouldFade`，模型仍按 Alpha/靠近范围渐隐并穿透，卡片保持可读、可点击；无须再加一个常驻“功能岛逃生点”。渐隐状态需要恢复模型交互时，沿用托盘开关。

## 4. 验证分层与诚实边界

- 生产函数：布局、sender/key/index 防线、测量后显示、空状态隐藏、Alpha/缩放坐标以及 C0 时序。
- 真实 Electron：Hiyori/Hotaru、原生鼠标点关闭/来源/选歌，拖动前后原生窗口位置，左右边缘交叉检测，渐隐与独立窗口并存。
- 外部服务：网易云预检 `need_login`，不将固定候选卡当成真实搜歌/播放。样本选择在 WebSocket 发送前截断，仍验证原始 ID 与命令字段完全一致。
- Python：本轮定向 36 项，不冒用旧全量报告。
- 失败轮次、DPI 探针问题、锁屏/安全桌面造成的 SetCursorPos 失败均与通过证据分开。Windows 输入桌面恢复由用户确认后再继续，未尝试解锁或切换安全桌面。

详细结果/未验项以关联 plan 和其最终 artifacts 为准。没有在本轮宣称音色、整体演出审美、跨屏长时间拖动、窗口崩溃自动恢复或完整内存基线已验收。

## 5. 维护与后续接口

优先继续小改：在合法空间内增加用户可选的卡片最大高度、边距/首选侧；补登录后的真实音乐播放；补多屏热插拔、长内容与渲染进程崩溃用例。不可把新 UI 入口逐步变成另一个 App/Agent 所有者。

不要继续维护“模型窗口内一套卡、独立窗口又一套卡”的双调用链。旧 SpeechCloud 文件暂保留但已不由 App 渲染；需要恢复旧模式时应走明确产品决策，而不是静默失败回退到遮挡模型。

“轻量”目前可验证的是入口构建体积、没有 WebGL/引擎请求和按需创建，而非 Electron renderer 免费。后续若出现内存/启动成本证据，再衡量合并呈现窗或原生方案；不因追求名义上的“无窗口”直接大规模重构。
