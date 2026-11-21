# Yuiro 调试与踩坑经验记录（Debug Log）

> 本文件用于沉淀本项目开发过程中遇到的实际问题、根因、修复与教训。
> **约定**：每次排查解决一个问题，就追加一篇；记录要让未来的自己/协作者能直接复用结论。

---

## 通用调试原则（先读）

1. **先复现，再动手**：用最小脚本/单测复现现象（如 `scripts/test_voice_ws.py`、`scripts/test_approval_e2e.py`），别靠猜。
2. **看日志说话**：引擎终端日志（`[yuiro][来源]`）是链路真相，先看它再下结论。
3. **区分"链路断了"与"链路慢"**：很多"无反应"其实是慢（模型加载/网络），先加阶段日志确认走到哪一步。
4. **Windows 三坑**：① 事件循环类型（Proactor vs Selector）决定 asyncio 子进程可用性；② 可执行文件被运行中的进程锁定无法重建；③ 控制台 GBK 编码会让中文日志乱码（`chcp 65001` 或 UTF-8 输出）。
5. **Electron IPC 通道名必须 send 与 on 完全匹配**：`webContents.send(channel, ...)` 与 `ipcRenderer.on(channel, ...)` / `ipcMain.on(channel, ...)` 的 channel 字符串**一字不差**才算同一个通道。引入中转 handler 时极容易把通道名改了却忘了同步另一端，导致一端 send 永远没人 on——表现为"链路完全静默"。**排查"无反应"时，第一步就 grep 通道名在 send/on 两侧是否一致**，比加日志快得多。
6. **控制外部程序前，先查它是什么技术栈**（2026-11-05 补，代价两个月）：
   凡是"要操纵某个桌面程序"，先花 10 分钟确认它用什么框架——这决定**唯一正确的入口类别**：
   | 特征 | 技术栈 | 正确入口 |
   |---|---|---|
   | `resources/app.asar`、`chrome_100_percent.pak`、`libEGL.dll`、窗口类名 `Chrome_WidgetWin_1` | Electron / CEF | **CDP**（`--remote-debugging-port`）+ 内部协议 |
   | .NET / WPF / WinForms | 原生托管 | UI Automation（UIA） |
   | Qt | 原生 | 无通用入口，只能键鼠模拟 |
   > **教训（真实案例）**：网易云 Windows 客户端是 Electron 套壳，开调试端口即可读取内部播放状态、驱动搜索、精确点歌。
   > 而 2026-08-31 我把它当黑盒原生应用，只在"外部协议"里穷举（`orpheus://`、`--webcmd`、`--player orpheus`、SMTC），
   > 四条全失败后就下结论"客户端不可控"，转去做 ncm-cli + mpv —— 绕了两个月，修了一堆本不需要的 bug。
   > **规则：`所有已知入口失败` ≠ `这条路不可行`，它只说明"我枚举的入口类别失败了"。
   > 下结论前必须回答：这个对象是什么技术栈？有没有我还没枚举的入口类别（不是变体）？**
7. **失败清单要记"入口 + 形态 + 参数"，不能记"入口无效"**：
   反过来也成立——只有记清试过哪些形态，才能判断是否真的穷尽。
   > 案例：我写下"`--webcmd` 无效"，其实只试过 `--webcmd="orpheus://song/<id>"`；
   > 而客户端真正接受的是 **base64 JSON**（`{"type":"song","id":"...","cmd":"play"}`）。
   > 同一个入口换个编码就通了——"一个格式失败"不等于"入口失效"。
   >
   > **配套机制（复查点）**：同一模块**修到第 3 个 bug** 时，强制停下来问一句
   > "是不是选错了层？" —— 而不是在这个层继续打补丁。
   > 沉没成本会让人把"修得动"误当成"方向对"，越修越不愿回头。

---

## 2026-08 声控链路（M2）

### 1. "语音链路无反馈"——ASR 首载 10~14s 且无中间事件
- **现象**：说话后界面毫无反应，以为链路断了。
- **根因**：链路是通的，但 faster-whisper **首次加载模型 10~14s**（CPU int8），期间零反馈。
- **修复**：① 全链路阶段事件（vad:state→asr:start→asr:text→llm:start→llm:text→tts:*），每步立即反馈；② **ASR 模型预热**（lifespan 后台 `warmup()`），首载延迟消除（ASR 9.3s→0.66s）；③ 后端终端 vlog 全程日志。
- **教训**：用户体验问题先查"慢"还是"断"；长耗时操作必须有中间反馈。

### 2. ASR 识别成 "You"/乱码——TTS 的 mp3 被当 PCM 解析
- **现象**：中文语音识别结果完全错误（"You"、"字幕by索兰娅"）。
- **根因**：**edge-tts 只输出 mp3**（ID3 头），`TTSProvider` 用 `np.frombuffer(mp3, dtype=int16)` 当 PCM——音频是垃圾，且 **volumes（口型数据）也是垃圾**。
- **修复**：`miniaudio`（纯 wheel 无系统依赖）解码 mp3→float32 PCM；`wav` 字段保留 mp3（前端 decodeAudioData 兼容），volumes 用真实 PCM 计算。
- **教训**：凡是"字节流→数值数组"，先验证字节格式（音频/图像/编解码）；口型数据错误往往源头在格式误判。

### 3. ASR 准确率不足——未指定语言 + 领域提示
- **现象**："打开记事本"识别成"打开计识本"（同音字错）。
- **根因**：faster-whisper 自动检测语言对短音频易误判；无领域引导。
- **修复**：配置化 `language="zh"` + `beam_size` + `vad_filter` + `initial_prompt`（领域词表"请帮我打开记事本、写下待办事项…"）→ **零错误**。
- **教训**：ASR/LLM 类模型效果先查参数（语言/beam/prompt），再考虑换模型。

---

## 2026-08 系统操控（M4）

### 4. 审批弹窗点"允许"无效，引擎仍超时——WS 单循环被长任务阻塞
- **现象**：审批弹窗弹出，点击确认后引擎仍报"审批超时或连接断开"→"审批回传未匹配"。
- **根因**：**架构 bug**。WS 通道单循环 `receive → await 长任务（AgentLoop/审批等待）`——审批等待期间 `receive` 循环被阻塞，`approval:resolve` 消息在缓冲区排队，审批必然超时；resolve 回来时 pending 已清理。
- **修复**：control/audio 通道拆为「**即时处理循环 + 串行 worker 队列**」——`approval:resolve`/`interrupt` 由主循环即时处理，聊天/PCM 长任务进队列；审批超时 30s→120s；壳层 try/finally 保证 resolve 必发。
- **验证**：`scripts/test_approval_e2e.py`（自动批准）端到端通过。
- **教训**：**凡是有"请求-响应"跨消息交互（审批/回调），处理协程绝不能阻塞 receive 循环**；用队列解耦长短任务。

### 5. SystemDaemon 未运行——asyncio 子进程依赖 Proactor 事件循环
- **现象**：`create_subprocess_exec` 抛 `NotImplementedError`，daemon 起不来，工具返回"SystemDaemon 未运行"。
- **根因**：Windows 上 asyncio 子进程**必须 Proactor 事件循环**；用户的 Python 环境（ComfyUI 系）强制 Selector 策略，且 import 时设置策略未必生效（循环可能已创建）。
- **修复**：传输层重写为 **`subprocess.Popen` + 线程内同步读写**（`asyncio.to_thread` 桥接）——与事件循环类型彻底解耦，任何 Python 都能跑；再加**懒连接**（daemon 未运行/崩溃时工具调用自动拉起）。
- **验证**：强制 Selector 策略下 daemon 连接/调用正常；端到端"打开记事本"成功（12.7s）。
- **教训**：**Windows 子进程优先用 subprocess 模块而非 asyncio 子进程**；依赖"运行时可换策略"的修复不可靠。

### 6. 工具执行成功但无最终回复——LLM 请求挂起无超时
- **现象**：工具结果 ok，但 AgentLoop 永不返回最终回复（日志停在"工具结果"）。
- **根因**：openai 客户端默认**无限等待**；qwen 兼容端点（阿里云 MaaS）在 tool 续问时偶发挂起，`async for` 永不结束。
- **修复**：`OpenAIProvider` 显式超时（`openai.Timeout(connect=10, read=60, write=30, pool=10)`）；worker 加异常兜底（回复错误而非静默）。
- **教训**：**所有外部 API 调用必须显式超时**；兼容端点（非官方）更要防挂起。

### 7. API key 401 invalid——keychain 与当前 key 不一致
- **现象**：诊断脚本直接调 LLM 报 `AuthenticationError 401`（key 尾号 ****FA2Y invalid）。
- **根因**：keychain 里存的 key 与当前有效 key 不一致（用户换过 key 未重配，或 key 失效）。
- **处置**：用户在调试台重新配置 key（PUT 会覆盖 keychain）。
- **教训**：key 持久化后若更换 key，必须在调试台**重新 PUT 覆盖**；诊断 401 优先怀疑 key 而非代码。

### 8. 可执行文件被锁无法重建（Permission denied）
- **现象**：`cmake --build` 报 `cannot open output file yuiro.exe: Permission denied`。
- **根因**：yuiro.exe 正被运行中的 daemon 子进程占用（引擎 spawn 的）。
- **修复**：先停引擎（或 kill daemon 进程）再重建。
- **教训**：Windows 下重建 exe 前确认无进程占用。

### 9. Qt 工具链——本机无 cmake/编译器但有现成工具
- **现象**：AGENTS.md 说 cmake/编译器未装，SystemDaemon 无法构建。
- **发现**：`D:\software\Qt\Tools` 自带 CMake 3.29 + MinGW 11.2/13.1 + Ninja——**无需安装**。
- **注意**：MinGW 的 `HINSTANCE` 是指针类型，`static_cast<intptr_t>` 编译失败，须用 `reinterpret_cast`；`std::filesystem::weakly_canonical` 不自动绝对化相对路径，需先 `fs::absolute`。

---

## 2026-08 测试/质量

### 10. TranscriptBuffer 测试从未跑过（同步回调被 await）
- **现象**：3 个测试传同步 lambda 给 `flush`，而实现 `await self._flush(text)` → 非 awaitable 抛 TypeError，测试必挂（疑似从未运行）。
- **教训**：新代码/新测试要**实际运行**验证；"测试存在"≠"测试通过"。

### 11. AGENTS.md 部分声明已过期
- **现象**：声称"唯一可跑纯逻辑是 response_categorizer"（实际 audio/memory/agent 均已实现）、"存在过期 .js 副本"（实际不存在）。
- **教训**：文档声明要随实现更新；以源码为准。

---

## 2026-08 媒体控制（网易云音乐）

### 12. orpheus:// URL scheme 在 Windows 不可控——改用全局媒体键
- **现象**：用户提出用网易云官方 `ncm-cli`（@music163/ncm-cli）的 orpheus:// scheme 控制桌面客户端（播放/上下首/指定歌曲）。
- **调研结论（联网验证）**：
  - `ncm-cli` **真实存在**（npm @music163/ncm-cli 0.1.6 + 官方 [NetEase/skills](https://github.com/NetEase/skills) 仓库，含 ncm-cli-setup / netease-music-cli 两个 skill）——Windows 播放器用 **mpv**；orpheus（云音乐 App）官方 SKILL 标注**仅 macOS**。
  - 但**实测本机**：Windows 网易云客户端（D:\software\CloudMusic）**确实注册了 `orpheus://` scheme**（`cloudmusic.exe --webcmd="%1"`）。
  - **实测 orpheus:// 各变体**（play/next/prev/play/next?songid 等 6 种）→ **窗口标题（显示歌名）均无变化，协议不响应基础控制**。
- **根因**：Windows 客户端的 orpheus:// webcmd 实现不响应 play/next 等基础控制（可能仅用于特定唤起场景）；ncm-cli 源码混淆无法提取格式。
- **最终方案（实测有效、零依赖）**：**全局媒体键**（网易云客户端默认注册媒体键监听）——
  - `VK_MEDIA_NEXT_TRACK` 0xB0（下一首）、`VK_MEDIA_PREV_TRACK` 0xB1（上一首）、`VK_MEDIA_PLAY_PAUSE` 0xB3（播放/暂停）、`VK_VOLUME_UP/DOWN/MUTE`（音量）
  - SystemDaemon 新增 **`media_control` capability**（SendInput，比 keybd_event 规范），action: play_pause/next/prev/volume_up/volume_down/mute
  - **实测验证**：窗口标题（歌名）在 next/prev 后变化 → 协议生效
- **教训**：① 官方文档说"仅 macOS"≠ Windows 不可用，但**必须以实测为准**（注册表 scheme 存在≠控制命令有效）；② 外部方案先做最小可行验证（窗口标题作观测锚点）再落地；③ **控制桌面媒体优先试全局媒体键**（零依赖），再考虑 ncm-cli/mpv/CDP（[opencli CDP 方案](https://github.com/Astro-Han/opencli/blob/worktree-describe-command/docs/adapters/desktop/neteasemusic.md) 是另一种完整控制途径）。

### 13. LLM 工具续问挂起——openai 流需总时限 + 显式关闭
- **现象**：工具执行成功（如 media_control 切歌生效）但最终回复缺失/极慢；引擎日志停在"工具结果"。
- **根因**：兼容端点（阿里云 MaaS qwen）在 tool 续问时可能**持续发空 chunk 或挂起**——httpx `read` 超时只测「两次数据间隔」，**空流不触发**；`asyncio.timeout` 上下文在 async 生成器内也未能可靠打断；且中断后 openai 流未显式关闭会残留挂起协程。
- **修复（三层）**：
  1. `OpenAIProvider.stream_text` **内部总时限 30s**（`loop.time() > deadline` break）+ **finally 显式 `await stream.close()`**（根治挂起）；
  2. `AgentLoop` 工具续问 `wait_for(anext(stream), 剩余时限)` 逐 chunk（单测验证：假挂起 LLM 30s 兜底 ✓）；
  3. `_agent_reply` 空结果兜底语（"已经帮你执行了…"）。
- **验证**：真实 qwen 端到端"下一首"→ 切歌生效 + 回复"好嘞！下一首更带感哦～"（此前多次无回复）。
- **教训**：流式外部 API 必须「总时限 + 显式关闭」，不能只依赖 read 超时（空流绕过）；兼容端点问题要一层层在 provider/loop/UI 三处兜底。

### 14. 记忆框架接线（M3 RAG）——MemorySystem 门面 + AgentLoop 写入钩子
- **调研灵感**（同类前沿项目）：架构共识 = SQLite + FTS5 + 向量 + RRF 混合检索（eidetic-memory/memento/HoardCore 同款）；记忆分类（EPISODE vs 用户事实/偏好，借鉴 agentic-memory）；写入策略 salience 加权（借鉴 memory-hygiene）；级联检索（AgentIR）。
- **实现**（框架版，调优留后续）：
  - `MemorySystem` 门面（memory/__init__.py）：持久化 SQLite（sqlite-vec 可用则向量）+ L2 情景（Retriever RRF）+ L3 用户事实（FactsStore）+ `remember()`（salience 启发式写入 + 正则抽取偏好入 facts）+ `retrieve()`（情景+事实合并注入）
  - AgentLoop 加 `memory_writer` 钩子（每轮对话后写入）；`build_agent_loop` 接受 `memory_system`（检索/写入一体）
  - config [memory] 加 `db_path`（默认 data/yuiro_memory.db，*.db 已 gitignore）+ `facts_subject`
  - 框架版用 md5 降级向量（不下载 BGE-M3）；调优换真嵌入 + LLM 抽取替换正则
- **验证**：`scripts/test_memory_system.py`——写入"我叫小明/喜欢火锅"→ 事实抽取（名字/喜欢/身份）→ **新实例读同一 db（模拟重启）检索命中** ✓；engine 测试 34 passed
- **教训**：记忆/RAG 先跑通"写入→持久化→检索注入"闭环，再上真嵌入与 LLM 抽取；回调签名与调用方严格对齐（remember 少 session_id 参数即崩）。

### 15. key 401 + model 改名——排查"静默挂起"先验证鉴权
- **现象**：LLM 首轮调用挂起无日志（引擎端连 30s 限时日志都不出）；隔离诊断直接调 LLM 报 `AuthenticationError 401 key ****FA2Y invalid`。
- **根因**：keychain 里的 key 已失效（阿里云拒绝），且 config.toml 的 llm.model 被改为 `deepseek-v4-flash`（非该端点模型名）。
- **处置**：用户在调试台重新配置有效 key（PUT 覆盖 keychain）；确认 model 名在该端点存在。
- **教训**：**排查"无日志挂起"先做隔离单测（直接调 LLM 一个最小请求）**——401/网络/挂起三者的表现可能都是"没反应"；key 与 model 名必须与端点匹配。

---

## 2026-08 壳层 / 悬停渐隐（Shell Fade-on-Hover）

### 16. 托盘切换「悬停渐隐」完全无反应——IPC 通道名 send 与 on 不一致
- **现象**：渐隐开启后，右键托盘 →「关闭悬停渐隐」点击无任何效果，窗口仍卡穿透态、功能泡不响应。渲染层日志里 `enabled` 始终为 `true`，且主进程 `fade:toggle` 日志从未出现。
- **根因**：引入 `ipcMain.on('fade:toggle')` 中转时把通道名搞混了——托盘菜单 `click` 闭包直接 `petWindow.webContents.send('fade:toggle', !fadeOn)` 给渲染层，而渲染层 `onFadeSet` 监听的是 **`'fade:set'`** 通道。两端 channel 对不上 → 渲染层永远收不到；那个 `ipcMain.on('fade:toggle')` 中转 handler 成了**死代码**（托盘 click 根本不经过 `ipcMain`）。问题被"逻辑对、状态机对、穿透控制对"层层表象掩盖，一度误判为穿透状态机竞争（其实穿透那侧代码是对的）。
- **修复**：① 托盘 click 发送通道由 `'fade:toggle'` 改正为 `'fade:set'`，与渲染层监听一致；② 删掉无用的 `ipcMain.on('fade:toggle')` 中转；③ 保留主进程兜底——托盘关闭时直接 `petWindow.setIgnoreMouseEvents(false)` 强制关穿透（不依赖渲染层链路）。
- **验证**：`pnpm typecheck` 通过；完全重启 `pnpm dev`（主进程代码不热更新，必须停掉重开）后，托盘开/关自如切换，`enabled` 实时翻转、菜单文案「开启/关闭悬停渐隐」同步。
- **教训（最重要的一条，已写入上方"通用调试原则 5"）**：**Electron IPC 通道名 send 与 on 必须一字不差**；引入中转/改名时极易只改一端。排查"无反应"第一步就 `grep` 该通道名在 `send`/`on` 两侧是否一致——比加一堆日志快得多。本次纯靠推理绕圈，正是漏了这步肉眼核对。

### 17. 渐隐"只穿透不淡出"——决策语义反了（旧坑，已修）
- **现象**（历史）：开启渐隐后只是 click-through，模型/功能泡没淡出。
- **根因**：原 `shouldFade = fadeEnabled && mouseInWindow && !transparentAtCursor`，要求"光标下是透明像素才渐隐"——等价于鼠标移到模型（不透明）上反而更不渐隐，与免打扰直觉相反；且 `.fade-hidden{opacity:0}` 类虽已接好，但 `shouldFade` 几乎恒 false 所以从不被触发。
- **修复**：改为免打扰语义 `shouldFade = fadeEnabled && mouseInWindow && !uiOpen && !nearBorder`（鼠标进窗口即淡出+穿透，移出/贴边恢复）；并修 `useMouseAroundWindowBorder` 的 AND→OR 判定（贴任一边即保留可拖动）；`useBracketMenu` 加 `fadeEnabled` 守卫（开启后功能泡不再呼出）。
- **教训**：「特征到底该什么时候触发」先和业务语义对齐再写条件；像素采样这类"精巧"判定若与直觉相反，多半是需求理解错了。

### 16. 记忆管理 API（GET/DELETE /api/memory）
- **需求**：调试台需要观察三层记忆内容（facts + 情景），并支持清除。
- **实现**：`GET /api/memory`（facts + 最近 20 条情景）；`DELETE /api/memory`（清空 messages/messages_fts/facts，保留表结构）；`app.state.memory` 挂载 MemorySystem 实例。
- **验证**：实测返回真实数据（facts 2 条：名字=小明/喜欢=吃火锅 + 2 条情景）。
- **教训**：记忆这类"隐形状态"必须提供**可观察端点**，否则用户无法确认功能是否生效。

---

### 17. 正则事实抽取误报 + 双引擎共享 db + 诊断脚本读错配置
- **现象**：用户问"我叫什么名字？"被误存为事实"名字: 什么名字"；双引擎（8200+8201）同时打开同一 memory.db 时引擎内 LLM 调用偶发挂起；诊断脚本报 401 但用户配置实际有效。
- **根因**：① 抽取正则 `我叫(.+?)` 不区分陈述/疑问；② SQLite 未设 busy_timeout，多进程共享 db 锁竞争时等待行为不确定；③ 诊断脚本在仓库根跑，`load_config()` 读到仓库根过时的 config.toml（deepseek 端点），与引擎实际用的 engine/config.toml（阿里云 qwen）不一致 → 用阿里云 key 打 deepseek 端点必然 401，**误判用户配置**。
- **修复**：① 疑问句跳过（结尾？/吗/呢 或含"什么/啥/哪个"等疑问词）；② `PRAGMA busy_timeout=5000`；③ 诊断一律显式在 engine/ 目录或显式传 config 路径。
- **教训**：① 规则抽取要防"提问当事实"；② 诊断工具必须与运行时**同一工作目录/配置**，否则结论南辕北辙；③ 共享 SQLite 文件必须设 busy_timeout。

---

### 19. RAG 基础调优（BGE-M3 真嵌入 + Markdown 标题切块 + 引用溯源）
- **评估结论**：四项调优中，真嵌入/标题切块/引用溯源**低复杂度高收益**（做）；PDF-网页源扩展与 rerank 模型**暂缓**（桌宠场景少用；top_k=3 小规模重排无意义，YAGNI）。
- **实现**：
  1. **BGE-M3 启用**：`Embedder(model)` 默认 BGE-M3（子进程隔离），模型未下载/加载失败**自动降级 md5**（实测：未下载时 embed 0.00s 返回 1024 维，不阻塞不崩）；config `[memory] embedder = "bge-m3" | "md5"` 显式可选。
  2. **Markdown 标题切块**：`#/##/###` 为界，标题链作前缀（`[里程碑 > M3 记忆]\n...`），纯文本回退固定长度；实测 3 标题文档切 3 块带链。
  3. **引用溯源**：知识注入附 `（来源: xxx.md）`，检索结果 meta 保留 source。
- **教训**：真嵌入用「可用则用、不可用降级」双轨，避免大模型下载阻塞功能；Markdown 切块按标题比固定长度显著提升检索质量。

### 18. 知识库 RAG 框架（KnowledgeStore + 双路注入）
- **实现**：`KnowledgeStore`（文档切块 500 字符/50 重叠 → 向量+FTS5 入库 → RRF 检索；独立表 knowledge_chunks/knowledge_vec/knowledge_fts 不混情景记忆）；`MemorySystem.retrieve` 合并「情景记忆 + 用户事实 + 知识库」三路注入（"（知识库）"前缀标注）；API：`POST /api/knowledge/ingest`（text 或 path）、`GET /api/knowledge?q=`、`DELETE /api/knowledge`。
- **验证**：`scripts/test_knowledge_rag.py`（ingest→检索命中→注入 kinds）通过；API 实测导入 docs/init/milestones.md（3 块）→ 查"M5 情绪"命中里程碑内容。
- **坑**：① 导入路径不存在——用户重构了 docs 目录（milestones 移到 docs/init/），先确认文件真实位置；② 测试脚本 TemporaryDirectory 清理失败——多实例（MemorySystem 又开连接）未全部 close 导致 db 文件锁。
- **教训**：路径类参数先 `os.path.isfile` 自查再下结论；SQLite 连接要成对 close。

### 20. M5 情感引擎接线（EmotionEngine + 互动奖励 + 表情推送）
- **实现**：`emotion/__init__.py` 完整实现——五维情绪指数衰减（decay 按真实时长）、boost/钳位、`style_hint()`（主情绪→语气提示注入 prompt）、Character 亲密度分段/经验连续升级（修复 while 内 return 只升一级的 bug）；main.py 装配 + 每轮对话互动奖励（happy+0.03/xp+5/affinity+0.1）+ 60s 定时衰减 + 主情绪变化广播 `emotion:set`；壳层显示"当前心情"。
- **验证**：`scripts/test_emotion.py`（衰减/加成/style_hint/连续升级）通过；typecheck 通过。
- **教训**：升级类循环里 return 会提前退出——累计多次升级要用"标志位 + 循环后返回"。

### 21. UI 优化第一轮（日志标准件 + 智能滚动）
- **研究**：两份参考项目 UI 报告（`.ua/deep-dive/ui-study-airi.md`、`ui-study-my-neuro.md`）——my-neuro 前端真身在 live-2d/（full-hub 是后端）；airi 的 stage-tamagotchi + stage-ui。
- **现状盘点**：ChatBubble（AIRI 入场动画）、FloatingBubble（LERP 跟随 280px 上限）用户已自行实现——避免重复改。
- **本轮落地**：① 日志四档配色（info #93c5fd/success #86efac/error #fca5a5+底纹/warning #fbbf24）+ 关键词自动判级 + 时间戳 + "全部/仅错误"过滤（my-neuro 标准件）；② 聊天智能滚动（贴底 24px 阈值才跟随，回看历史不打扰——airi scroll hook 模式）。
- **教训**：参考项目报告落地前先盘点现状（用户可能已吸收部分设计），只补缺口；日志分级靠关键词判级即可，不必结构化日志系统。

---

### 22. M5 Proactive 骨架（定时观察→决策→打招呼）
- **实现**：`proactive/__init__.py` 三件套——`AttentionObserver`（随机间隔 + SystemDaemon 截图，未接线降级无视觉观察）、`ProactiveDecider`（LLM 未就绪时 15% 概率启发式，避免打扰）、`ProactiveScheduler`（asyncio 循环 + 单轮异常不终止）；config `[proactive] enabled/min/max_interval_s`；main.py lifespan 装配启动，greet 经 `proactive:greet` 广播壳层显示为助手消息。
- **验证**：调度器短间隔测试（运行/停止/启发式决策）通过；typecheck 通过。
- **教训**：主动互动框架先跑通「定时→决策→推送」闭环，视觉观察/LLM 决策留调优（观察数据在框架版不参与决策）。

### 27. 气泡皮肤系统扩展（5 套风格 + 快捷键）
- **实现**（my-neuro 皮肤思路）：ChatStyle 扩展为 5 套——default/glass/**soft**（暖色柔和圆润）/**neon**（青紫霓虹光感）/terminal；tokens.css 补 soft/neon 双主题变量（含 dark 覆写）；`useChatStyle` 加 **Alt+1~5 键盘切换** + localStorage 持久化；App.vue 风格按钮改用 `styleLabel` 动态映射（不再硬编码三套）。
- **验证**：typecheck 通过。
- **教训**：皮肤系统 = ChatStyle 联合类型 + CSS `[data-chat-style]` 变量覆写 + 单一 composable 管理（状态/持久化/快捷键三合一）；按钮 label 用映射表而非模板硬编码三目。

### 26. 打字逐字动画 + 面板展开模型避让
- **打字动画**（airi PoppinText 模式）：ChatBubble 文本按 grapheme 切分（`Intl.Segmenter`，正确处理 emoji/组合字符）→ 逐字 span → 每字 translateY(3px)→0 + opacity 0→1 错峰（18ms/字，总 delay 封顶 900ms）——与原有边框缩放入场组合成两阶段动画。
- **模型避让**：Live2DCanvas 加 `avoidPanel` prop——面板展开（activePanel/islandOpen）时模型缩至上方 82% 区域（scale × 0.82），收起恢复；watch 驱动重新布局，与右下角面板不再抢位。
- **验证**：typecheck 通过。
- **教训**：中文打字动画必须按 grapheme 切分（不能按 code unit，否则 emoji/组合字会断开）；避让联动用 prop + watch 重新布局即可，无需复杂动画协调。

### 25. 窗口贴合模型（1:1）+ 功能岛抽屉精致化
- **需求**：模型窗口 420×560 固定但模型只占 55%——大量透明空白；要"窗口 ≈ 模型"。
- **实现**：全链路 `fitWindowToModel`——Live2DCanvas 首次量出模型真实 bounds → preload `window:fit-to-model`（invoke）→ 主进程 `window:fit-to-model` handler `setSize(模型宽, 模型高 + 56px 功能区)` + `fillRatio=1`（缩放归一，真一比一）；`fitReported` 标志防循环上报；异常值防御（80~1600px）。
- **注意**：主进程/preload 改动**不经过 vite HMR**——必须重启 `pnpm dev` 才生效（渲染层 .vue 才 HMR）。
- **教训**：窗口贴合用"渲染层量尺寸 → 主进程 resize → appearance:update 回渲染层"闭环；量尺寸只上报一次，避免 setSize→resize→layout 的循环。

### 24. UI 视觉重设计（面板轻量化 + 配置页防堆砌）
- **痛点**：功能岛聊天面板（320px 宽 / 72% 高）遮挡模型严重；dev 配置页 8 张卡片双列平铺像"堆砌"。
- **方案**（airi/my-neuro 报告落地）：
  1. 桌宠面板：272px 宽 / 44% 高 / **rgba(12,12,16,0.66) 更透** + blur 18px saturate + 细描边（1px 而非 2px）+ 贴边 12px + 气泡区紧凑（gap 6px/min-height 96px）——遮住也轻盈不"堵"
  2. 桌宠窗口默认暗色玻璃（`.shell-root` 变量覆写，不影响 dev 窗口）
  3. dev 配置页：**单列 760px 居中 + 三组分组标题**（核心/语音链路/系统与记忆）+ SectionForm **默认折叠**（只显标题+项数，点击展开；有未保存修改不可收起）——一屏尽览不堆砌
- **验证**：typecheck 通过（vite HMR 自动热更桌宠/dev 窗口）。
- **教训**：桌宠 UI 的"轻盈感"= 半透明 + 强模糊 + 细边框 + 紧凑尺寸四件套；配置页防堆砌 = 分组 + 默认折叠 + 单列窄宽。

### 23. 配置面板优化（SectionForm 折叠卡 + hint 文案 + proactive 段）
- **实现**：SectionForm 折叠卡（点击头部收起/展开 + 未保存圆点提示）；字段 hint 说明渲染（引擎 FIELD_META 的 hint 字段——之前只有数据无消费，本次补 UI）；sectionTitles 补 proactive；config.py 的 FIELD_META 补 proactive 段元数据（含 hint）。
- **验证**：py_compile + typecheck 通过。
- **教训**：元数据驱动表单的"hint"字段是**半成品常见坑**——引擎侧定义了、UI 没消费；新增配置段时记得同步 sectionTitles + FIELD_META 两处。

---

### 28. 悬停唤出括号菜单 + 模型拖动「窗口逐渐膨胀」连环坑（Electron/Windows）

> 背景：桌宠窗口去掉了 `-webkit-app-region: drag`（见下），改用 JS 实现「悬停模型→括号功能岛菜单」「按住模型→拖动」。这两组交互在 Windows + 透明无边框 + HiDPI 下踩了一串坑。

#### 坑 A：悬停菜单唤不出——`-webkit-app-region: drag` 在 OS 层吞掉 mousemove
- **现象**：悬停模型区域不弹括号菜单（capture 监听也收不到）。
- **根因**：`.shell-root { -webkit-app-region: drag }` 是 **OS 层拦截**——drag 区域内的 `mousemove`/`click` **根本不派发到 JS**（连 `window` 的 capture 监听都收不到）。模型区又是 `pointer-events: none`，所以 mousemove 永远不触发 → 菜单永不唤出。能拖动只是因为 mousedown 走 drag 系统本身。
- **修复**：移除全局 drag；拖动改由 JS 实现（mousedown 命中模型矩形 → 跟随鼠标主进程移动窗口）。移除后 mousemove 正常派发 → 菜单可唤出。
- **注意**：`bm-icon` 上的 `no-drag` 在去掉全局 drag 后无副作用，可保留。

#### 坑 B：拖动漂移/放大——坐标系换算累积误差（两版都错，最终弃用增量法）
- **现象**：拖动时窗口/模型「不自然且逐渐放大、抖动漂移」。
- **走过的弯路（记录以免再犯）**：
  - 第 1 版：`window.screenX` 反推窗口位置 + `setPosition`。**错**——`window.screenX`/`e.clientX` 是 CSS 逻辑像素，`BrowserWindow.setPosition` 收物理像素，DPI≠100% 时累积放大。
  - 第 2 版：渲染层发「相对上帧增量 dx,dy（CSS px）」+ 主进程 `dx * scaleFactor` 换算。仍**错**——`scaleFactor` 换算方向/取值不可靠，且 `sendSync` 阻塞导致 mousemove 合并、单帧 dx 巨大 → 跳变。
  - **决定性方案**：拖动改「主进程读 OS 光标绝对坐标」三阶段（`dragPetStart` 记 `光标 - 窗口左上角` 偏移；`dragPetMove` 每帧 `setPosition(光标 - 偏移)`；`dragPetEnd` 结束）。`screen.getCursorScreenPoint()` 与 `getBounds()`/`setPosition()` **同一物理像素坐标系**，零换算、零累积。
- **教训**：Electron 窗口定位**一律在主进程用物理像素**；渲染层坐标只用于「判定命中区域」，绝不参与「反推窗口位置」。跨进程传坐标做位移必然踩 DPI 换算。

#### 坑 C：窗口「逐渐膨胀」的真凶——Windows 下 setPosition 会偷偷啃大尺寸
- **现象**：**即使鼠标不动、只是长按按住**，窗口尺寸也持续 +2×+2 每帧膨胀（日志实证 `getBounds()` 从 `438×579` 一路涨到 `505×644`）。
- **根因**：Windows 上 `BrowserWindow.setPosition()` 在 **`transparent: true` + `autoDensity`** 组合下，坐标在 DPI 缩放下反复舍入，**会把窗口尺寸也带偏、缓慢长大**。而 `onWinMouseMove` 在鼠标抖动下持续触发 `dragPetMove` → 每帧 `setPosition` → 每帧啃大一点。（这也解释了「长按不动也膨胀」：不是光标移动，而是 mousemove 抖动事件持续触发 setPosition。）
- **修复**：拖动改用 **`setBounds({ x, y, width: dragStartW, height: dragStartH })`**——每帧**显式钉死**拖动开始时的真实尺寸，`setPosition` 的尺寸漂移再无可乘之机。`dragStartW/H` 在 `drag-start` 用 `getBounds()` 记录。
- **验证**：主进程加 `[main] WARN 拖动中窗口尺寸变化` 日志，修复后该日志不再出现 → 膨胀消失，拖动跟手、尺寸恒定。

#### 坑 D：功能泡漂移——拖动冻结 modelRect 的副作用
- **现象**：拖动/长按期间状态泡（StatusOrb）漂移到旧位置，松手归位。
- **根因**：为防膨胀，曾给 `layoutModel`/`handleResize` 加整段「拖动冻结」（`__yuiroDragging` 时 return）。但 `modelRect`（模型包围盒，功能泡/悬停区定位源）依赖 `getBoundingClientRect()`，窗口移动后坐标就旧了——冻结导致其不更新 → 漂移。
- **修复**：拖动期间 `layoutModel` **不整体冻结**，而是拆成「拖动分支只更新 `modelRect`（用缓存的 `layout.cx/cy/w/h` 重算相对视口坐标），不碰 `scale`、不读 `getBounds`、不触发 `fit`」；`handleResize` 尺寸不变时也调 `layoutModel`（走拖动分支）。窗口移动时功能泡实时跟随，缩放系数完全冻结。

#### 坑 E：Live2DCanvas 的 layoutModel 反馈闭环（本轮已修，记以防回归）
- **教训**：`layoutModel` 里**绝不用 `getBounds()` 实时测「已缩放的包围盒」再算 scale**——一旦因 DPI 测量偏差，下一帧基于偏差值再缩放 → 模型尺寸单向漂移膨胀。改为：**首次量出 `baseModelW/H` 后永久缓存**，之后布局只用基准尺寸算 scale；`handleResize` 加 `lastW/lastH` 尺寸守卫，尺寸无变化不重排，避免 ResizeObserver 在 resolution/resize 抖动下自激振荡。
- **注意**：`fitWindowToModel` 用 `fitReported` 标志只上报一次（setSize→resize→layout 闭环），但本轮证明膨胀**不在**这里（长按期间无 `[live2d]` 日志），根因是坑 C 的主进程 `setPosition`。

#### 调试方法论（本轮关键）
- **日志要看对地方**：渲染层 `console.*` 在 Electron 窗口的 **DevTools Console**（按 **F12** 打开，已加 F12 快捷键 `before-input-event` → `openDevTools({mode:'detach'})`），**不在 shell 启动终端**。主进程日志（`console.log` in main）**在 shell 终端**。两者分开看。
- **先定位「哪个进程/哪个函数」在改尺寸**：在 `setSize`/`setPosition`/`fit-to-model` 入口加日志，实测（如坑 C 日志）直接锁定真凶，比推测快 10 倍。
- **Windows 透明窗口三连坑**：① drag 区域吞 mousemove（坑 A）；② setPosition 偷偷改尺寸（坑 C）；③ DPI 下坐标系换算（坑 B）。做桌宠窗口交互时默认这三处都会出问题。

### 29. 整窗白屏 + 模型加载不出来 + 悬停唤出「没接上」三连环（Electron/Vite/文件同步）

> 背景：上一轮（第 28 篇）做完悬停唤出 + 拖动后，工作区经历了一次"沉寂"，期间文件被部分还原/不同步。重启 `pnpm dev` 后出现：① 窗口在但**整个前端 UI 白屏**；② **模型不加载**；③ F12 无效。逐一定位。

#### 坑 A：整窗白屏——composable 接口不同步，setup 阶段抛错
- **现象**：窗口存在（微信截屏能看到），但连 Vue 外壳/功能岛都不渲染，全透明白屏。
- **根因**：`App.vue` 是修复后新版，调用 `useMousePassthrough({ activePanel, islandOpen, petCanvas })` 并解构 `syncForcedInteractive/forceInteractive/updateFromPointer`；但磁盘上的 `useMousePassthrough.ts` 被还原成**旧版**（接收 `chatOpen/menuOpen/getModelRect` 且**末尾无 return**）→ 第 72 行解构 `undefined` → 第 84 行 `watch([...], undefined)` 抛错 → Vue `setup()` 阶段崩 → 整个 App 挂载失败 → 白屏。
- **修复**：重写 `useMousePassthrough.ts` 对齐 `App.vue` 期望的接口（参数 + 返回三个方法）。
- **教训**：**"之前能跑、沉寂后不能跑"优先怀疑文件被还原/不同步**，先 `pnpm typecheck`——TS 报的"属性不存在/参数不匹配"就是运行时崩溃点；`script setup` 里解构返回值拿到 `undefined` 会在 setup 阶段直接崩成整窗白屏，而不是局部报错。

#### 坑 B：F12 无效——DevTools 快捷键根本不在代码里
- **现象**：按 F12 没反应，无法开 DevTools 看报错。
- **根因**：`src/main/index.ts` 里原本**没有**注册 `before-input-event` → `openDevTools`（被还原丢了）。
- **修复**：在 `createOverlayWindow` 里加 F12 → `openDevTools({mode:'detach'})`；同时加 `did-fail-load` / `render-process-gone` 日志，白屏时主进程终端直接打出加载失败原因。

#### 坑 C：模型加载不出来——模型目录不在 public 下，`/live2d/...` 404
- **现象**：模型区域空白，窗口在但模型没渲染。
- **根因**：electron-vite 渲染层静态根是 `src/renderer/public/`（默认 `publicDir`），代码和 `model_dict.json` 用 `/live2d/肥牛/feiniu.model3.json` 访问，但模型文件在 `src/renderer/live2d/`（不在 public 下）→ dev server 对该 URL 返回 404 → `loadModel` 里 `fetch` 失败，`loadError` 显示"HTTP 404"。
  **历史溯源（git 铁证）**：模型早期（`8f9f365`）就在 `public/live2d/`（正确位置）；后来（`a7166b7`）被复制到 `src/renderer/live2d/`（非 public）；工作区的 `public/live2d` 被清理后，`/live2d` 就 404 了。
- **修复（最终方案，一劳永逸）**：**把模型目录直接迁移到 electron-vite 静态根 `src/renderer/public/live2d/`**，真实文件进 git，dev/build 永远可用，不依赖 junction。
  ```powershell
  # 删 junction（若之前建过），再把真实目录移到 public 下
  Remove-Item "src\renderer\public\live2d" -Recurse -Force
  Move-Item "src\renderer\live2d" "src\renderer\public\live2d"
  ```
  移完后 `src/renderer/public/live2d/` 是**真实目录**（`d----`），`MODEL_PATH='/live2d/肥牛/...'` 直接命中。
- **教训（关键）**：**模型等大静态资源必须放在 `src/renderer/public/` 下**，这是 electron-vite 唯一官方静态根。`.moc3/.png/.json` 这类被 `/xxx` URL 引用的文件，绝不能放 `src/renderer/` 根（源码目录，不提供静态服务）。**不要用 junction**——junction 不被 git 跟踪，换机/重装/清理就丢，会静默回到 404。

#### 坑 D：悬停唤出「写了但没接上」——BracketMenu 组件闲置
- **现象**：第 28 篇记录的"悬停唤出括号菜单"没生效，跑的还是旧岛屿抽屉。
- **根因**：`BracketMenu.vue` + `useBracketMenu.ts` 已写好，但 `App.vue` 仍装配旧的岛屿抽屉（`.island`/`collapse-btn`），两套 UI 并存但没切换。
- **修复**：`App.vue` 接入 `BracketMenu` + `useBracketMenu`——`useBracketMenu` 返回 `menuOpen`，模板用 `<BracketMenu :open :center-x :center-y .../>`，`centerX/Y` 从 `Live2DCanvas.getModelRect()` 算模型中心；删掉岛屿抽屉相关函数与模板；`useMousePassthrough` 改回接收 `{ chatOpen, menuOpen, getModelRect, getFallbackRect }`。
- **注意**：**必须移除 `.shell-root` 的 `-webkit-app-region: drag`**（见第 28 篇坑 A）——它吞掉 mousemove，悬停唤出永远触发不了。移除后 mousemove 正常派发。

#### 调试方法论（本轮）
- 白屏定位顺序：① `pnpm typecheck`（TS 报的接口不匹配=运行时崩溃点）→ ② 主进程加 `did-fail-load`/`render-process-gone` 日志 → ③ 渲染层 `loadModel` 已内置 fetch 探活（`loadError` 会显示 HTTP 状态码）。
- electron-vite 的静态资源：**`/xxx` 路径 = `src/renderer/public/xxx`**，模型等大资源**必须放 public 下**（真实文件，git 跟踪）；别放 `src/renderer/` 根下，也别用 junction（不跟踪、易丢）。

### 30. 模型无待机动作 + 加载"报错但模型在"——model3.json 动作路径大小写不匹配（Windows）
- **现象**：模型能显示（站立眨眼），但**没有待机动作**（不背手/抬眼）；且 UI 偶尔出现红色报错条，Console 有 `[MotionManager(肥牛)] Failed to load motion: motions/hiyori_m01.motion3.json` + `NetworkError: Network error`。
- **根因**：`feiniu.model3.json` 的 `Motions` 引用是小写 `motions/hiyori_m01.motion3.json`，但**磁盘文件名是大写 `Hiyori_m01.motion3.json`**。Windows 文件系统不区分大小写 → XHR 请求能命中（HTTP 200），但 **pixi-live2d 内部按 JSON 里的大小写去校验/映射时失败** → `motionLoadError` → 动作全部加载失败 → 没有 idle 动作可播 → 模型只眨眼。
  - **注意**：HTTP 200 ≠ 加载成功。`Status 200` 但 `Failed to load as json`，是**大小写不匹配**的典型表现，容易误判为"网络/文件缺失"。
- **修复**：把 `model3.json` 里所有 `motions/hiyori_` 引用改为 `motions/Hiyori_`，与磁盘文件名完全一致（`replace_all` 13 处，micoff/micon/singing 本就是全小写不动）。
- **附加坑 A（loadError 残留）**：`loadModel` 的 catch 设置 `loadError`，但**成功路径从不清空** → 之前某次失败的报错条会在后续成功加载后仍显示，误导排查。修复：`loadModel` 开头 `loadError.value = ''`，fetch 200 也清空。
- **附加坑 B（Vue 多余属性警告）**：`Live2DCanvas` 未定义 `avoid-panel` prop 但 App.vue 传了 → 组件多根节点无法自动继承，Vue warn。修复：移除多余属性（组件根本没用它）。
- **教训**：① Live2D 模型动作"加载了但不动"，先看 **Console 的 `motionLoadError`**——它是动作加载失败的铁证；② `Status 200` 不一定是成功（大小写/内容校验失败也会 200）；③ 静态资源文件名与 JSON 引用**必须精确一致**（尤其 Windows 下大小写看似"通"实则校验失败）；④ 调试日志转发（console-message）Electron 33 是**旧式数字参数** `(level,message,line,sourceId)`，不是对象——按 d.ts 推断对象形式会错。

---

## 2026-08 本地 CosyVoice2 TTS（GPU 推理 + 零样本克隆）

> 背景：桌宠语音从 edge-tts（云）迁到本地 CosyVoice2-0.5B（GPU），独立 tts-server 进程，engine 经 httpx 调用。完整设计见 `docs/tts-local-upgrade.md` 与 `docs/tts-cosyvoice-migration.md`，下载脚本 `scripts/download_cosyvoice_modelscope.py`。本篇只沉淀**搭建过程中实际踩的坑**。

### 31. 环境搭建连环坑（Python 3.13 + RTX 3060 + venv2）

#### 坑 A：PyPI 的 cosyvoice 包在 3.13 下无法构建 wheel
- **现象**：`pip install cosyvoice` 在 CPython 3.13 报构建失败（源码有 3.13 不兼容语法/依赖）。
- **根因**：官方 PyPI 包未跟进 3.13；venv2 是独立完整 CPython 3.13.11，无法用预编译 wheel。
- **修复**：改用 **gitclone 镜像克隆 FunAudioLLM/CosyVoice 源码**，`sys.path.insert` 把仓库根 + `third_party/Matcha-TTS` 加进去（见 `tts-server/app.py`）。**不要走 PyPI 的 cosyvoice 包**。
- **教训**：遇到"包在目标 Python 不可装"，先查是否有源码克隆路径；AI 项目常带 submodule（`third_party/Matcha-TTS`）需一并加入 path。

#### 坑 B：torch 2.4GiB CUDA wheel 官方源超时断流
- **现象**：官方 pypi 装 `torch` cu126 时大包（2.4GiB）下载超时 / 断流，反复失败。
- **根因**：官方 CDN 国内不稳定；阿里云 / npmmirror 镜像**无 torch 2.13 cu126 对应 wheel**（镜像同步滞后）。
- **修复**：① 用户开网络加速器；② 用 `curl -C -` 断点续传从 `download.pytorch.org` CDN 拉 wheel，**本地装**（`uv pip install ./torch-xxx.whl`）——比 pip 直连稳。装完删掉本地 wheel 避免污染（已清）。
- **教训**：超大 wheel（torch/cuda）国内优先**下载到本地再装**；镜像缺失时官方 CDN + 断点续传比 pip 直连可靠。注意 npmmirror 的 PyPI 路径会 404，**PyPI 镜像用 aliyun 而非 npmmirror**。

#### 坑 C：缺 Matcha-TTS submodule
- **现象**：import CosyVoice2 报 `No module named 'matcha'`。
- **根因**：CosyVoice2 的 flow 依赖 Matcha-TTS，是 git submodule，clone 主仓时未带下来。
- **修复**：镜像克隆 Matcha-TTS 到 `CosyVoice/third_party/Matcha-TTS`，加入 `sys.path`（已写入 app.py）。
- **教训**：克隆带 submodule 的项目，先 `git submodule update --init` 或手动补 third_party；报找不到 `matcha` 就是这条。

#### 坑 D：torchaudio 2.11 强制 torchcodec（DLL 加载失败）
- **现象**：CosyVoice 的 `load_wav` 走 torchaudio，但 venv2 的 torchaudio 2.11 依赖 torchcodec，Windows 上 DLL 加载失败。
- **根因**：新版 torchaudio 把音频解码拆到 torchcodec（独立二进制），本机缺对应 DLL。
- **修复（关键）**：改写 `CosyVoice/utils/file_utils.py` 的 `load_wav`，**改用 soundfile 读 wav → float32**，仅重采样处保留 torchaudio（CPU 轻量 resample 不触发 codec）。参考音频传**文件路径字符串**给 frontend，让它内部用 soundfile 版 load_wav 加载。
- **教训**：① 能用纯 wheel（soundfile）就别碰 torchcodec 这类带原生依赖的；② 改第三方库内部函数是大招，需注释清楚（已在 file_utils.py 标注）。

#### 坑 E：onnxruntime CPU 慢 → 装 onnxruntime-gpu
- **现象**：合成单句 17~23s，明显偏慢。
- **根因**：CosyVoice 的 onnxruntime 默认 CPU EP；3060 闲着。
- **修复**：装 `onnxruntime-gpu`（CUDAExecutionProvider 自动生效），**装前先停 tts-server 释放 DLL**（否则 DLL 被锁）。验证：CUDA provider 在 provider 列表首位，显存占用上升。
- **教训**：GPU 机器上 onnxruntime 必须装 **-gpu** 版，否则白瞎显卡；换 onnx 包前停服务释放 DLL。

#### 通用经验（本轮）
- **区分"下载"和"安装"**：权重/代码往往已下载好，卡在"安装/编译"环节——别把"装得慢"误判成"没下载"。排查时先看磁盘文件是否到位，再查 pip/编译日志。
- **进度可见**：下载/安装大包时务必加进度日志（`curl -#` / `tqdm` / pip 的进度条），否则"无输出"会让人以为卡死。本机 venv2 用 uv（无 pip），大包走 `curl 本地 → uv pip install ./xxx.whl`。
- **逐步补依赖**：cosyvoice/funasr/diffusers/lightning/gdown 等缺什么补什么（阿里云镜像），别一次性猜全。

### 32. 接口接线坑（CosyVoice2 调用）

#### 坑 A：原版 `CosyVoice` 类加载 v2 权重报缺 yaml
- **现象**：用 `from cosyvoice.cli.cosyvoice import CosyVoice` 加载 `cosyvoice2-0.5B` 权重报找不到 `cosyvoice.yaml` / speech_tokenizer 版本不匹配。
- **根因**：v2 权重（iic/CosyVoice2-0.5B）须用 **`CosyVoice2` 类**，原版类只读 v1 命名。
- **修复**：`from cosyvoice.cli.cosyvoice import CosyVoice2`，`CosyVoice2(model_dir, fp16=True)`（fp16 省显存，3060 6GB 可行；实测 ~4.8GB）。

#### 坑 B：`inference_zero_shot` 第 4 参误传 language 致 KeyError
- **现象**：调用 `inference_zero_shot(text, prompt_text, prompt_wav, "zh")` 报 `KeyError: 'zh'`。
- **根因**：该参数不是 language，是 `zero_shot_spk_id`（说话人 id），传 `"zh"` 被当 key 查表失败。
- **修复**：传**空串 `""`**——动态用参考音频构建音色，不指定固定 spk id。

#### 坑 C：参考音频传 tensor 报 Invalid file
- **现象**：`_infer` 把参考音频读成 tensor 传入，frontend 报 Invalid file / 无法加载。
- **根因**：frontend 内部 `load_wav` 期望**文件路径**（内部自己读），传 tensor 反而坏。
- **修复**：`_infer` 只校验 `Path(prompt_wav).exists()`，把**路径字符串** `str(prompt_wav_path)` 传给 inference 接口。

#### 坑 D：`inference_instruct` 仅原版支持 → 改 `inference_instruct2`
- **现象**：想用指令式合成（语气控制）调 `inference_instruct` 报属性不存在。
- **根因**：`inference_instruct` 属原版 CosyVoice；CosyVoice2 对应的是 `inference_instruct2`。
- **修复**：有 instruction 时走 `model.inference_instruct2(text, instruction, prompt_wav, "")`，无指令走 `inference_zero_shot(text, prompt_text, prompt_wav, "")`。

#### 坑 E：推理结果是生成器，需 next() 取首段
- **现象**：`result["tts_speech"]` 报生成器不可下标。
- **根因**：CosyVoice2 推理接口返回 **yield 单条结果的生成器**（支持流式多句）。
- **修复**：`first = next(iter(result))`，再取 `first["tts_speech"]`，`squeeze(0)` 后 `detach().cpu().numpy()` → soundfile 写 24kHz PCM16 wav 返回。

#### 验证结果
- 端到端打通：engine `CosyVoiceProvider.synthesize_segment('你好世界')` → HTTP → tts-server → CosyVoice2 GPU → 192044 bytes wav；volumes（口型 RMS）长度 200，父类逻辑零改动复用。
- 样本：`tts-server/samples/sample_zh.wav`(13.6s) / `sample_en.wav`(7.2s)，需人工试听确认音色与 `assets/voices/neuro_prompt.wav` 一致。
- 显存 4857/6144 MiB（79%），未 OOM；onnxruntime-gpu CUDA provider 生效。
- 遗留：合成 ~17-23s/句（flow matching 为主 + fp16 权重未真转半精度），桌宠偏慢但功能可用；如需提速可后续研究 batch/量化。

#### 启动方式（固化）
目录已归并：推理核心抽到 `engine/yuiro/audio/cosyvoice_engine.py`（共享模块，仅独立 tts 进程 import），薄壳在 `engine/yuiro/tts_server/server.py`（`yuiro` 子包，`python -m yuiro.tts_server.server`）。

**一条命令起全部**（推荐，理解 2：双进程但单脚本编排）：
```powershell
# 在仓库根目录执行，同时拉起引擎(8200) + 本地 TTS(5005)，仍是两个独立进程
& .\scripts\engine\engine_start.ps1
#   仅起引擎、不同步 TTS： & .\scripts\engine\engine_start.ps1 -NoTTS
#   停止：& .\scripts\engine\engine_stop.ps1   （会连带清理 5005 TTS 进程）
```
TTS 服务独立启动（如需单独调试）：
```powershell
. .\engine\yuiro\tts_server\start_tts_server.ps1
& .env-local\engine-venv2\Scripts\python.exe -m yuiro.tts_server.test_voice   # 验证音色
```
> **隔离原则（红线）**：`engine/yuiro/audio/__init__.py` 的 `CosyVoiceProvider` 只发 HTTP，**绝不 import `cosyvoice_engine`**；torch 推理只在 tts 子进程加载，避免与 SenseVoice ASR 抢显存/GIL。故 TTS 不并入 `uvicorn yuiro.main:app` 同进程。
> `start_tts_server.ps1` 已配置 CUDA DLL PATH + venv2 激活 + TQDM_DISABLE；改代码后**重启该服务**才生效（uvicorn 不带 --reload）。

---

## 常用验证工具（scripts/）

| 脚本 | 用途 |
|---|---|
| `test_voice_ws.py` | 语音链路端到端（可 `--tts-text` 用真实中文语音） |
| `test_approval_e2e.py` | 审批端到端（自动批准，验证审批不超时） |
| `diag_tool_continuation.py` | 诊断 LLM 工具续问（两轮对话） |
| `test_memory_system.py` | 记忆框架验证（写入→事实抽取→跨实例检索） |
| `test_knowledge_rag.py` | 知识库 RAG 验证（切块→检索→双路注入） |
| `test_emotion.py` | M5 情感引擎验证（衰减/加成/养成） |


---

## 2026-08 GPT-SoVITS 本地 TTS（v2ProPlus 角色模型）

### 33. GPT-SoVITS 接入（CosyVoice 太慢的替代方案）
- **背景**：CosyVoice2 首次加载 + 推理延迟高，交互卡顿。引入 GPT-SoVITS 作为新 TTS provider，保留 CosyVoice/edge-tts 共存（config `[tts].provider` 切换）。
- **资源现状（关键）**：用户提供的外部 Bundle `E:\AI\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604` 里**没有 Fake Neuro 训练模型**，只有 v2ProPlus 日系角色（MyGO_要乐奈 / Roselia_今井莉莎 / ppp_戸山香澄 / ppp_有咲_吐槽特化 / 诗歌剧）。文档设想的"复用 merge.pth"实际不存在 → 用现成角色模型验证链路（用户已确认）。
- **启动**：`scripts/start_gptsovits.ps1`（可选 `-Role` 切换角色），用 Bundle 自带 `runtime\python.exe api.py`，端口 5000。参数：`-g GPT权重.ckpt -s SoVITS权重.pth -dr 参考音频 -dt 参考文本 -dl auto`。参考音频用 `assets/voices/neuro_prompt.wav`（Fake Neuro 音源），音色主体由说话人模型决定。
- **engine 侧**：`GPTSoVITSProvider`（`engine/yuiro/audio/__init__.py`）只重写 `_synthesize_audio`，POST `{text, text_language}` 到 `/`，返回 wav 字节；synthesize_segment/口型/解码全继承父类（miniaudio 解 44.1kHz wav，volumes 照算）。**不 import 不复制 Bundle**。
- **编排**：`engine_start.ps1` 读 config.toml `[tts].provider` 自动分支（gptsovits→5000，cosyvoice→5005）；`engine_stop.ps1` 清理 8200/5005/5000。

### 34. GPT-SoVITS 接入踩坑
- **坑 A（关键）：PowerShell .ps1 必须 UTF-8 BOM**。`replace_in_file` 改写 .ps1 后可能丢失 BOM，导致 PowerShell 以 GBK(936) 读取 UTF-8 中文 → 中文注释/字符串乱码 → 解析错误（"Missing terminator"）。**每次改完 ps1 后用 Python 检查/补 BOM**（`EF BB BF` 头）。
- **坑 B：GPT-SoVITS 权重文件名带版本后缀**。如 `MyGO_要乐奈_v2pp.ckpt`（不是 `MyGO_要乐奈.ckpt`）。脚本需按角色名前缀模糊匹配（`Get-ChildItem -Filter "$Role*.ckpt"`），不能硬编码后缀。
- **坑 C：服务就绪检测不能用 HTTP HEAD**。GPT-SoVITS `/` 端点 HEAD 会异常，改用 TCP 端口监听检测（`Get-NetTCPConnection -State Listen`）。
- **坑 D：engine_start.ps1 读 config provider** 不能简单 `Select-String provider` 取第一个（会误匹配 [asr]/[hard_of_hearing] 的 provider），要按 `[tts]` 段切分后取段内 provider。
- **坑 E：首次合成慢（冷启动 10~25s），稳定后 ~2.5s**。GPT-SoVITS AR 架构首包延迟是固有瓶颈；调试台 TTS 测试每次新建 provider 会触发冷启动，属正常。运行时 provider 常驻，稳定延迟 ~2.5s（优于 CosyVoice）。
- **坑 F：debug_api.py 热重载/测试需按 provider 分支**。`_apply_config` 和 `_test_tts` 原只处理 cosyvoice/edge-tts，切 gptsovits 后会被覆盖回 edge-tts。已补 gptsovits 分支；`/api/status` 的 tts 段也补了 provider 字段。

### 验收结论
- `engine_start.ps1` 标准启动：引擎 8200 + GPT-SoVITS 5000 双进程；`/api/status` 报告 `provider=gptsovits`；debug 台 TTS 测试返回 wav + volumes（口型正常）；GPT-SoVITS 直接 POST 合成 200/RIFF。CosyVoice/edge-tts 仍可经 provider 切换回退。
