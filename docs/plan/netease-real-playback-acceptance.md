# 网易云扫码后双角色真实搜歌、播放与停止验收

日期：2026-10-24。范围：补齐独立结果卡的真实服务验收；经用户明确授权，局部修复 mpv 状态误判与错误外部回退。不推进 G1，不改角色大脑/音色/人设配置，不重构 Runtime。

后续策略更新：本报告保留为前一轮真实播放证据；权益提示、禁止静默换版，以及“即便 mpv 已确认空闲也不得自动转控外部播放器”，以 [当前通道与客户端桥接报告](netease-channel-client-bridge.md) 为准。

## 结论与范围

**扫码登录成功；Hiyori、Hotaru 的隔离回合真实搜歌 → 独立结果卡 → 原生点选 → 实际播放 → 聊天停止 → 带真实卡片切换清理均通过。** 用户确认：“两段正常，停止后没有残留”。

**同一会话连续重搜仍有 P1 缺口**：模型可能只用文字声称“搜好了”，实际未调用工具、没有新卡。本次不把这种文字回答算成功，也没有用固定样本补卡。最终隔离用例通过正常角色切换建立新会话后，真实调用工具完成；不能据此宣称连续多轮搜歌已整体通过。

最终证据：[music-real.json](detached-ui-artifacts/music-real.json)。首轮通过且有人工听感确认的证据：[music-real-first-pass.json](detached-ui-artifacts/music-real-first-pass.json)。旧样本验收 `music.json` 仍保留，但不再作为真实播放的依据。

## 实测结果

下表为最终有效轮次；测试包含完整 API/LLM/播放器等待，非服务端纯计算耗时。全量 pytest 同时运行，未将其当作独立性能基准。

| 项目 | Hiyori | Hotaru Shiomi |
|---|---|---|
| 首次真实搜索 | Monody TheFatRat，5 条，7.393s | Spectre Alan Walker，5 条，7.379s |
| 实际选中的可播版本 | Monody (BIMONTE Remix) | Spectre |
| 原始歌曲 ID | 1452906755 | 30064263 |
| 原生点击到实际起播/进度可见 | 4.875s | 3.683s |
| 播放证据 | `playing + ready + state_confirmed`，时间轴继续增长 | 同左 |
| 聊天“停止播放音乐”到回读 stopped | 2.521s | 0.329s |
| 拖动模型的物理位移 | x +82 / y +33 px | x +84 / y +34 px |
| 真实结果卡的物理位移 | x +82 / y +34 px | x +83 / y +34 px |
| 再次真实搜索用于切换清理 | Hope Tobu，5 条，7.676s | Sky High Elektronomia，5 条，3.160s |
| 带卡切换 | → Hotaru | → Hiyori |
| 清理及旧点击 | 卡为空、回复隐藏、结果窗隐藏；旧 key 转发 0 | 同左 |
| 切换后播放器 | stopped，未被旧卡重新激活 | 同左 |

实际选择是返回结果中的可播版本；保留其 `song_id/encrypted_id` 原值，不重搜同名歌曲。未声称选中所有版本的原唱或绕过版权。

停止验证不是只看“停好了”文案：脚本通过 mpv 专用 IPC 回读 `playlist-pos=-1`、`queueLength=0`、`state_confirmed=true`。结束再次确认播放器停止、界面与调试台均恢复 Hiyori，连接正常、无切换错误；恢复测试前 UI 偏好和窗口布局。

## 发现的问题及已授权修复

### P0：mpv 正在播放，却误判空闲并转控外部客户端

修复前已真实播放 Monody，独立探针观察到播放进度；但引擎停止工具错误返回 `forwarded=true`，控制了外部网易云客户端，测试 mpv 仍在播放。此轮明确失败，证据：[music-real-stop-before-fix.json](detached-ui-artifacts/music-real-stop-before-fix.json)。随后只用本次测试 mpv 的专用通道停止音乐；未继续使用可能误转 SMTC 的停止指令，未自动恢复外部客户端播放。

源码问题：

- `engine/yuiro/netease/player.py` 原 `_send_ipc_sync` 将任何 JSON 行计作响应，mpv 的 `event` 会提前抵扣等待数量。
- request_id 每批从 0 开始，迟到、重复响应可能被错误当成本批状态；拆开的 JSON/UTF-8 内容未跨读取保留。
- 多个 `asyncio.to_thread` 调用共用常驻句柄，没有整次事务串行化，存在读走其他调用响应的竞争。
- `get_state` 把缺失 `playlist-pos` 当作 stopped；`NeteaseControlTool` 据此自动转去控制外部播放器。

用户明确同意局部修复后，改动：

1. 同一管道完整读写事务加 RLock；句柄打开/关闭也受保护。
2. 传输请求 ID 跨批递增，只收本批匹配响应，忽略事件、重复及迟到响应；对调用方保留批内编号，不扩大上层接口改造。
3. 保留跨读取字节缓冲，完整行再解码；检查写入长度、断管和不完整响应。
4. 缺失有效播放位置/暂停状态时返回 `unknown`，不能当作空闲；读取锁等待放到线程，避免阻塞引擎事件循环。
5. unknown 时返回可重试错误，**不操作外部播放器**；确认为空闲时原有外部控制功能保留，不一刀切删除。
6. 控制指令无确认、状态不可确认或停止后仍在播放时，不再返回虚假的成功。

修复仅在播放器传输/状态与控制回退边界，不动 Agent/Voice/Avatar Runtime、不改账号授权存储。已有控制链路继续承担实际播放，不引入第二套播放器。

### P1：连续同会话重搜不一定触发工具

日志确认首轮 LIFE 搜索实际发生过 `netease_search`；之后同一会话的 LIFE、Faded、Monody 请求出现单轮纯文字回复，没有新的工具调用与结果卡。证据：[重复查询](detached-ui-artifacts/music-real-repeat-query-no-card.json)、[新关键词同会话](detached-ui-artifacts/music-real-same-session-no-tool.json)。

最终用例明确采用角色切换生命周期隔离各次搜索，未清空数据库或伪造 Agent 结果。四次最终检索均由当前角色真实 Agent 调用工具生成卡片。这验证了真实服务与 UI/播放链路，但**未解决同会话工具选择问题**。

后续建议单开小任务：对明确“重新搜歌/给候选”的意图保证真实工具调用，或显式复用有身份/有效期的结构化候选；无工具证据时不能声称“刚搜好”。本轮没有顺手改 Agent 决策策略。

## 自动化与人工验收

- 新增 `engine/tests/test_mpv_ipc_integrity.py`，**13 项通过**：事件不算确认、跨批 ID、重复/迟到响应、拆包/UTF-8、事务并发、部分状态不能变 stopped、未知状态不转外部、确认空闲保留外部控制、无 ACK 不报成功，以及管道锁等待不阻塞事件循环。
- 定向 `test_mpv_ipc_integrity + test_s35_s36_s37 + test_character_cards`：**38 passed**。
- 最终 Python 全量：**858 passed in 54.63s**，无跳过。
- 新增测试文件 Ruff 通过。未宣称整个历史仓库 lint 已清零。
- `scripts/diag/detached_music_real_acceptance.py`：最终两角色通过，无 fixture、未截断真实 `media:play`，真实 Windows 点击和拖动、实际 mpv 状态及进度校验、真实结果卡的双向切换与旧动作拒收。
- 用户对首轮完整通过的两段实际音乐确认正常，停止后无残留；最终轮次再次由播放器状态验证。

另一个初始失败是验收脚本只等固定 350ms，冷启动浮层尚未 ready 就找原生窗口。已改为等待 renderer 内容及原生可见状态，记录在 [initial-ready-wait](detached-ui-artifacts/music-real-initial-ready-wait.json)，不冒充产品已通过。

## 复验方式与交付文件

引擎、壳和调试台就绪，网易云已扫码授权后，在项目根目录：

```powershell
. .\config\env.ps1
.\.env-local\engine-venv2\Scripts\python.exe scripts/diag/detached_music_real_acceptance.py
```

脚本严格使用真实服务。会短暂播放音乐、发送停止、切换角色并移动窗口；需要普通 Windows 输入桌面，期间不要手动移动鼠标。登录失效、没有真实卡片、ID 不一致、播放器没有实际起播/停止均直接失败，不降级为样本通过。

修改文件：

- `engine/yuiro/netease/player.py`：管道事务、响应匹配、未知状态、真实控制结果与异步锁探测。
- `engine/yuiro/tools/netease_tool.py`：未知状态禁止错误转控外部。
- `engine/tests/test_mpv_ipc_integrity.py`：新增回归。
- `scripts/diag/detached_music_real_acceptance.py`：真实链路验收。
- 本报告、`docs/plan/README.md`、原拆窗报告的补验链接与证据。

登录凭证继续由 ncm-cli 本地管理，未写入角色卡、聊天报告或 artifacts；报告不保留二维码链接、token、签名播放 URL。扫码后已删除本次临时二维码图片，需重登时可重新生成，CLI 已保存的授权不受影响。没有修改 Live2D 资产、语音配置或推进 G1。
