# 独立气泡与结果卡窗口：实施与验收

日期：2026-10-24。范围：当前 Electron/Vue 前端的局部产品调整；不进入 G1，不另建 Runtime，不更换原生渲染框架。

## 交付

- 移除模型窗口右下角常驻的“⋮”功能岛呼出点。原有模型悬停菜单保留；渐隐模式下可从系统托盘关闭渐隐，不再放置额外常驻按钮。
- 回复气泡、结果卡各用一个按需创建的无边框透明窗口；无内容时隐藏复用，桌宠关闭时销毁。结果窗口共用选歌/歌单和联网来源组件，不新增三套业务状态。
- 两个窗口只呈现快照，不加载 Live2D、不打开引擎 WebSocket、不接管语音播放或 Agent。桌宠页面继续拥有会话、文本/音频生命周期、结果与动作。
- 原生拖动时由主进程 `move/resize` 直接跟随；按显示器工作区尝试首选侧、另一侧、上下方及堆叠位置，同时避开可见模型包围盒和另一张卡。空间不足时隐藏，不回落到遮挡模型。
- 调试台 UI 页原有宽度、透明度、位置微调、结果卡左右偏好继续跨窗口即时生效，避让优先于微调。回复最长约 400 CSS px、结果卡约 420 CSS px，高内容可滚动。
- 模型轮廓、穿透、遮罩/阈值/容差设置保留。渐隐只控制模型；独立回复不再随模型悬停消失，保证用户能阅读和点击收起。
- 每张快照携带身份/内容版本键。主进程核验发送者、窗口类型、版本及条目索引；桌宠接到动作后再次核验，并从自己的当前结果中取条目，保留原 `song_id/encrypted_id/playlist_id`，不让浮层自行拼播放命令。

这仍是 Electron 原生窗口组合，不是“没有 HWND”的原生无窗口渲染；不以微信截图是否识别窗口作为已达成结论。

## 源码落点

| 职责 | 源码证据 |
|---|---|
| 快照、身份版本、动作二次核验、保持主页面业务所有权 | `shell/src/renderer/src/App.vue:1244` 的 `detachedSnapshot/publishDetached` |
| 角色切换清回复与结果 | `App.vue:328`、`:564`、`:583` 的三个清理入口 |
| 独立窗口生命周期、发送者/版本校验、坐标跟随 | `shell/src/main/detachedUi.ts:7` |
| 不遮角色/不互相遮挡的屏幕布局 | `shell/src/main/detachedLayout.ts:6` 的 `placeDetached` |
| 独立入口及尺寸测量/操作回传 | `shell/src/renderer/detached.html`、`src/detached/DetachedApp.vue` |
| 复用来源/选歌列表，不再做模型窗口内夹紧 | `shell/src/renderer/src/components/ResultCard.vue` 的 `detached` 分支 |
| 类型化 IPC | `shell/src/shared/detachedUi.ts`、`shell/src/preload/index.ts` |
| Windows 混合 DPI 鼠标归一化 | `shell/src/main/overlayCoordinates.ts`、`useElectronMouse.ts`、`useElectronRelativeMouse.ts` |

## 本轮发现并局部修复的问题

1. 原切换链路清结果、停音频，但纯文字回复没有在所有入口明确收起；切换后可能再次出现。已在三个清理入口补 `hideSpeech()`。
2. 独立窗口初版 `focusable:false` 在 Windows 隐藏后再显示时出现原生点击不进入页面。改用 `focusable:true + showInactive()`：自动出现不抢焦点，用户点击后可正常交互；作为模型的 owned window 保持层级。
3. 根容器 `max-width:100vw` 把测量值锁在旧窗口宽度，无法热更新放大。移除旧 viewport 约束，按实际内容测量后回传，当前版本键测量完成前不显示新内容。
4. 混合 DPI 显示器上的 DIP 点不能无条件与窗口 DIP 原点直接相减。新增物理坐标归一化 `u/v`，再乘 renderer CSS viewport；保留旧 DIP 字段和回退兼容。窗口内判断也统一为 CSS 尺寸。
5. 原生探针补线程 DPI awareness；恢复窗口时通过 Electron 布局 API 恢复 DIP 尺寸，不把 Win32 物理尺寸反向传入。失败轮次单列，不纳入通过统计。

## 验收证据与边界

证据目录：`docs/plan/detached-ui-artifacts/`。其中 `first-run-invalid.json`、`contour/dpi-probe-invalid.json`、`contour/mixed-dpi-before-fix.json` 是失败/修复前记录，不能作为通过依据。

| 项目 | 结果与证据 |
|---|---|
| Hiyori、Hotaru 原生点击收起回复 | 两角色通过；`live.json`，Win32 鼠标事件，不是 DOM `.click()` |
| 来源标题/摘要/日期、原生点击文档链接 | 两角色通过；固定展示样本，实际走系统浏览器打开 DeepSeek 文档，不冒充实时联网检索；`live.json` |
| 实际模型拖动与窗口跟随 | 两角色通过；记录拖动前后 Win32 窗口位置，约 82–84 物理 px 横向移动，气泡/卡片同步移动；`live.json` |
| 宽度/透明度跨调试台热更新 | 两角色通过：280 CSS px / alpha 0.65；结束恢复原偏好；`live.json` |
| 角色切换与旧动作拒收 | 双向切换清卡/回复，两个窗口原生隐藏；旧 key 转发数均为 0；`live.json` |
| 左右屏幕边缘避让 | 两角色 × 两侧通过，模型、两类浮层均不互相遮挡，浮层留在工作区；`edges.json` |
| 渐隐时独立回复仍可见 | 两角色通过，模型淡出而回复生命周期/窗口仍可见；`edges.json` |
| 选歌点击与准确 ID 路由 | 两角色固定样本通过；原生点击后清卡，ID 原样进入 `media:play`，样本在网络发送前截断；`music.json` |
| 真实搜歌/实际播放 | 首轮 `need_login`，当时不能宣称播放通过。**扫码后已完成双角色隔离回合真实补验**，含播放器停止误判修复及人工听感确认；同会话连续重搜仍有独立 P1 缺口。详见 [真实补验](netease-real-playback-acceptance.md) |
| 轮廓/穿透最终复测 | 最终两角色透明点各 5/5；正常实心点各 0/3 误穿透；渐隐后实心位置各 1/1 穿透；遮罩可视化与 180 阈值 / 7 容差热更新通过。证据 `contour/live.json` 含点击时原生目标窗口与实际输入轨迹；过程中的失败记录不并入 |

已通过：`pnpm typecheck`、`pnpm build`；`detached_frontend_test.cjs` 的 48 个边缘/负坐标显示器布局场景与协调器校验；轮廓函数/混合 DPI 换算/归一化优先与旧协议回退；C0 前端 3 个时序场景。Python 定向回归 `test_character_cards.py + test_search_presentation.py` 为 **36 passed**。本轮未重跑全部 Python 用例，不沿用旧报告的全量数量。

最终轮廓短采样：两角色各 3 秒 / 24 次；Hiyori 单次平均约 **2.94ms**，Hotaru **3.54ms**；开启采样的 RAF p95 约 **7.3 / 8.4ms**，暂停采样时约 **6.5 / 6.8ms**。这是当前设备局部观察，不代表零开销、长时压力或语音端到端延迟达标。

已查看独立窗口的固定样本截图：[回复](detached-ui-artifacts/speech-preview.png)、[来源卡](detached-ui-artifacts/results-preview.png)，确认文字/日期/关闭按钮未裁切；卡片外壳为透明背景，避免和 ResultCard 自身背景叠加导致不透明度失真。截图不含用户聊天内容，不等同双角色整体桌面美感的人工审定。

## 复验入口

在项目根目录加载 `config/env.ps1`，引擎与壳就绪、打开调试台后：

```powershell
node scripts/diag/detached_frontend_test.cjs
node scripts/diag/contour_frontend_test.cjs
node scripts/diag/c0_frontend_test.cjs
.\.env-local\engine-venv2\Scripts\python.exe scripts/diag/detached_acceptance.py
.\.env-local\engine-venv2\Scripts\python.exe scripts/diag/detached_edges.py
.\.env-local\engine-venv2\Scripts\python.exe scripts/diag/detached_music_acceptance.py
.\.env-local\engine-venv2\Scripts\python.exe scripts/diag/contour_acceptance.py --out docs/plan/detached-ui-artifacts/contour
```

原生输入测试串行运行，期间不要锁屏、停留安全桌面或进行代码 HMR。测试会临时移动角色、切换身份、调整 UI 偏好；`finally` 恢复。来源测试会打开两个文档浏览器标签。真实账号已登录时音乐脚本允许短暂实际播放，并发送停止指令；未登录则明确标注样本且不实际播放。

## 未扩大范围 / 后续

- 用户扫码后已补实际搜索—选择—播放/停止与听感验收，见 [补验报告](netease-real-playback-acceptance.md)；保留同会话多轮重搜不调工具的 P1，不代用户完成账号认证。
- 视觉自然度、长回答的阅读习惯仍需用户在自己的桌面审定；固定样本排版截图已检查，但不宣称整体人工审美已验收。
- 屏幕热插拔监听已接入，但未实机拔插显示器；极端小屏、旋转屏、跨 DPI 长拖动与窗口渲染崩溃恢复可继续专项验收。
- JS 独立入口产物约 7.95 kB（不含共享 Vue/样式块）；“轻量”指不重复加载 Live2D/引擎，**不是**声称 Electron 新 renderer 的常驻内存已量化或为零。
- 主进程/Preload 变更需要重启壳；调试台偏好可直接热更新。开发态代码 HMR 后使用完整页面刷新/重启作为正式验收起点，避免旧单例存储监听污染结果。
- 没有手动改写角色大脑/音色/密钥配置；实机聊天和角色切换自然产生的会话事件、关系与记忆运行数据保留，不通过回滚数据库掩盖测试影响。

技术过程和取舍见 [独立轻量 UI 窗口技术复盘](../tech_review/2026-10-24-detached-ui-windows-review.md)。
