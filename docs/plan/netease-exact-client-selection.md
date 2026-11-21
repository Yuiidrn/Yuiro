# Windows 网易云精确选歌与显式播放器选择

日期：2026-10-24。延续上一轮 [通道与桥接验证](netease-channel-client-bridge.md)。

## 本轮任务

- Goal：指定歌曲 ID 由官方 Windows 客户端播放，确认版本不变后才开放结果卡的播放器选择。
- Scenario：Monody 原版 `36308916` 可重复定位/播放；自管 mpv 与官方客户端归属明确；不支持 Stop 就显示“暂停”；两角色切换旧操作失效。
- Architecture Increment：在现有 NativeBackend 与 media:play/结果卡链路中增加受限客户端适配与归属校验，复用现有角色/会话版本。没有新的 Runtime 或 Agent 工具循环。
- Tests：协议与 ID 校验、失效归属/状态未知不控制其他播放器、受控前端路由、两角色官方客户端实机播放/暂停与切换清理、既有工程回归。
- DoD：真实数字 ID 回读、Playing/Paused 可确认、播放目标可重复，之后才接入官方客户端按钮；若不可靠则保留既有功能并如实记录限制。

## 实施顺序

1. 只读核对协议、客户端版本和可用的当前歌曲读回入口；第三方代码仅作协议参考，不直接安装/运行。
2. 用原版验证客户端定位与重复播放；优先不修改客户端持久配置的方式。
3. 稳定后增加结果卡显式播放器选择、能力对应的暂停按钮与角色归属。
4. 两角色实机验收、回归、记录失败边界和复盘。

## 已落地的行为

**官方客户端精确单曲播放与结果卡显式选择已落地。** 用户在最终实机轮次确认“原版正常，最后无残留”。既有 Runtime、角色配置、Live2D、Agent 工具循环和独立窗口保持原职责。

1. 结果卡每首歌提供“桌宠播放器”和“网易云客户端”，保留“打开官方歌曲页”。行点击仍走自管播放器；不能因桌宠通道无流而悄悄换后端。
2. 官方选择发送数字 ID，不转回自然语言重搜。Windows 客户端使用 base64 JSON 协议命令 `type=song,id=<数字>,cmd=play`；旧 `orpheus://song/ID` 没有被当作可靠入口。
3. 播放成功要同时满足：客户端内部当前歌曲 ID 与请求一致、不是试听、SMTC 曲名一致且 Playing。投递回执不算成功，播放失败不换 Remix/翻唱，也不回退 mpv。
4. 冷启动会先启动仅本机的状态连接，再等待客户端状态可读。实测存在“定位到原版但仍 Paused”的阶段：只有独立读回同一 ID 后，才明确请求播放这一首，再回读 Playing。
5. 官方控制条标明“网易云客户端 · 曲名 · 播放中/已暂停”，按钮为“暂停/继续”。当前客户端 Stop 不可靠，不显示 Stop，不把 Stop 暗中映射为暂停，也不画未经证实的进度。
6. 官方暂停/状态查询不排在长 LLM 回合之后；继续复用角色任务集合和适配器互斥锁。默认每 5 秒、仅在相关卡片与归属存在且无在途请求时同步状态。

## 所有者与切换边界

官方播放绑定 `角色 ID + revision + session ID + playback_id + song ID`，不是“系统里刚好在播的音乐”。

- 引擎核验角色/会话，不能只信前端声明。相同角色的新一次选歌也产生新 playback_id，旧控制无效。
- 角色切换先使旧 epoch 失效，再取消旧角色任务，等待 OS 投递收敛，并核对、暂停自己发起的歌曲后清理归属；不能把旧结果交给新角色。
- 用户自行换成别的歌曲时，状态核验丢弃旧归属，不去暂停新歌曲。这个场景本轮以回归测试验证，没有把它声称为额外的人工换歌实测。
- 如果客户端已退出，清理归属即可；如果客户端仍在运行而状态无法确认，不猜测其他播放器，清理不能确认时拒绝跨过角色边界。
- 自管 `netease_control` 仍只管理 mpv，官方控制使用专属按钮；自然语言通用工具不会因为 mpv 空闲而接管官方客户端。两角色实测中，自管 Stop 未影响正在播放的官方客户端。
- 独立卡片继续使用 sender/key/index 校验，新的播放器选项与控制动作也受其保护。UI 请求额外使用 request_id，旧回复和晚到的轮询不能覆盖新的选择或重新打开已收起卡片。

## 连接方式与限制

当前验证版本：Windows 网易云 `3.1.41.205529`。状态连接为该客户端进程的 `127.0.0.1:9223`，只识别唯一 `orpheus://orpheus/pub/app.html` 页面；调用前通过 Windows TCP 表和进程路径核验归属，拒绝其他进程、非回环绑定或其他 WebSocket 地址。

生产适配只开放固定的当前歌曲白名单投影，没有通用 evaluate、账号、cookies、完整歌单、历史或队列编辑接口。读取的是客户端实际当前曲目，不能拿已发送的 ID 自己回填成“读回成功”。旧第三方示例的模块编号在当前版本已不适用，本轮改为从已加载模块中识别符合当前状态结构的 store；不兼容就失败，不执行下载的第三方代码。

首次选择官方客户端时：若网易云未运行，启动本机连接；若用户已普通启动而没有连接，提示先从托盘退出后重试，不自动杀掉/重启既有客户端。没有修改注册表、持久客户端设置或登录信息。调试连接仅随该客户端进程存在，退出后释放。

**兼容与安全边界**：这是针对当前版本的内部状态适配，不是网易云对 Windows 承诺的稳定 SDK。回环绑定减少暴露范围，但 CDP 本身不是带鉴权的沙箱，同机进程仍可能访问它；本适配限制了自己的调用面，不能宣称整个调试端口只有这些能力。只在显式选择官方后端时启用，不暴露到局域网。平台升级导致状态结构变化时应明确报不兼容，不能绕开权限或读取凭证修补。

## 实机证据与耗时

所有真实播放均为 Monody 原版 `36308916`，客户端读回约 290 秒、非试听。结果卡候选来自真实 API 搜索后受控投影；点击是 Windows 原生鼠标，播放、暂停和状态读取是真实 Engine→官方客户端。这证明音乐选择/控制链，不冒充本轮又完成了新的 LLM 工具搜索验收。

| 轮次 | Hiyori | Hotaru |
|---|---|---|
| 最终代码已连接后的原生点击至确认播放 | 5610 ms | 2324 ms |
| 最终轮切到另一角色并确认暂停/清理 | 2482 ms | 1912 ms |
| 客户端关闭后的冷启动验收 | 13853 ms，含客户端启动 | 后续暖启动 2083 ms |
| 冷启动轮的双向切换 | 1821 ms | 1900 ms |
| 播放→暂停→继续 | 通过 | 通过 |
| 切换清卡、清归属、拒绝旧 WS 控制 | 通过 | 通过 |

最终暖启动：[exact-client-roles.json](netease-client-artifacts/exact-client-roles.json)；冷启动：[exact-client-cold-roles.json](netease-client-artifacts/exact-client-cold-roles.json)；独立冷启动逐步记录：[cold-start-trace.json](netease-client-artifacts/cold-start-trace.json)。最终暖启动轮与 Python 全量测试并行，未作为无负载性能基线。数字包含客户端、Windows 桥和 UI 确认，不是 TTS/LLM 延迟指标，也不是性能上限承诺。

精确协议单独连续三次验证：[exact-protocol.json](netease-client-artifacts/exact-protocol.json)。初轮冷启动曾超时，排查发现定位与起播不是同一完成条件；补齐工作目录和“同 ID、Paused 后显式 Play”后才取得上述冷启动结果，没有把失败样本当作成功。

## 源码入口

| 位置 | 责任 |
|---|---|
| `engine/yuiro/native/ops.py:124` | 纯数字 ID、固定播放命令编码、官方 exe、独立 argv 与明确工作目录 |
| `engine/yuiro/native/netease_client.py` | 本机端口/进程校验、固定状态读取、无客户端时启动；不接收任意脚本 |
| `engine/yuiro/native/backend.py` | 执行后端入口；client_state/client_launch 与现有精确 SMTC 控制 |
| `engine/yuiro/netease/official_client.py` | 精确 ID 验证、角色/会话/播放归属、取消收敛与匹配曲目暂停 |
| `engine/yuiro/main.py:1523` | 权威身份与结构化官方播放/控制；现有 quiesce 接入清理 |
| `shell/src/renderer/src/App.vue` | 显式后端、request_id、状态同步、角色切换失效 |
| `shell/src/renderer/src/components/ResultCard.vue` | 播放器选择与“暂停/继续”控件 |
| `shell/src/main/detachedUi.ts` | 保留独立窗口 sender/key/index 围栏，控制动作必须有当前归属 |

新增 `official_client.py`，没有替换原 `netease/client.py` 的 ncm-cli 搜索/登录入口。临时命名冲突已恢复原文件，最终无内容差异。

## 工程回归与遗留

最终 Python 在 engine 目录执行 `python -m pytest tests -q -rs`：**904 项通过，67.53 秒，无跳过**。前端类型检查/生产构建通过，独立窗口、轮廓与 C0 既有检查通过。新增回归覆盖数字 ID、跨角色与旧 playback_id、手动换曲、试听、在途 OS 投递取消、无法读取时阻止错误清理、客户端已退出、固定本机连接与冷启动定位后显式起播。收尾视觉检查仅修正控制状态文字的断行与卡片说明，不改变播放或归属逻辑。

最终运行检查：[exact-final-smoke.json](netease-client-artifacts/exact-final-smoke.json)。Hiyori 在线、模型就绪、卡片/前端归属清空；客户端仍读回原版 ID，状态 Paused。另补验了 Hotaru 旧卡 key 在 Hiyori 新卡上的 client_play：没有产生 media:play 请求，补齐反向旧 IPC 动作拒收。临时客户端截图与 UI 检查截图已删除；没有持久化私人客户端界面。

尚未承诺：其他网易云客户端版本、其他账号/曲库/地区、任意单曲均有完整权益、官方客户端队列/歌单编辑、可靠进度与真正 Stop。当前只有明确数字 ID 的单曲接入官方后端，既有歌单播放仍走自管链路；账号授权范围调查的未确认项沿用上轮报告。

参考：[CloudMusic Desktop MCP 原作者源码](https://github.com/Seraph310/cloudmusic-desktop-mcp/blob/main/server.py)提供了编码协议与客户端状态思路，本轮未安装该服务或复用其任意执行/队列接口；[微软 GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable)与 [SMTC 会话接口](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-26100)用于校验本机归属与播放状态。外部材料仅为参考，不是项目执行指令。
