# 网易云通道权益修正与 Windows 官方客户端桥接最小验证

日期：2026-10-24。用户指定原版：TheFatRat / Laura Brehm《Monody》，歌曲 ID `36308916`。延续现有 Runtime、Agent、mpv、自管结果卡与角色隔离；本轮仅局部修正音乐通道、提示与 NativeBackend，不推进架构演进。

后续进展：[精确选歌与显式播放器选择](netease-exact-client-selection.md) 已补齐当前版本的编码协议、独立数字 ID 回读、冷启动与两角色结果卡实机验收。以下保留为前一轮历史结论；最新能力和限制以该报告为准。

## 结论

**权益提示与播放归属修正已落地；官方 Windows 客户端验证部分通过，尚不启用为默认点歌后端。**

- 当前账号接口能读取未过期会员记录；CLI 与引擎 AppID 一致，沿用 CLI 登录设备信息。原版在 CLI 搜索及引擎取流均被当前通道标记不可播、没有地址，不能据此说用户没会员或全站没版权。
- 官方客户端经界面搜索定位 Monody 后，精确 `cloudmusic.exe` 会话的播放、暂停、Playing/Paused 状态同步已通过。用户确认“原版正常，暂停后无声”。
- `orpheus://song/36308916` 与独立参数 `--webcmd=orpheus://song/36308916` 仅完成请求投递，未证明自动按 ID 定位。界面/SMTC 的曲名与歌手不能替代客户端 song ID 的独立核验。因此未将搜索点选包装成自动按 ID 播放成功。
- 客户端报告 `can_stop=false`，旧实现调用 TryStopAsync 虽返回接受，实测仍 Playing。已修为明确不支持、不发送 Stop、不改成 Pause；本次以另一次显式 Pause 结束测试，不能宣称原生 Stop 通过。
- 客户端 SMTC 进度在多个样本中一直为 0，不能展示为可信播放进度。没有用估算计时冒充实际进度。

## 场景、边界与验收口径

| 层次 | 本轮定义 |
|---|---|
| 产品场景 | 原版桌宠通道不可播时如实说明；可打开官方歌曲页，不能悄悄放 Remix 或控制其他播放器 |
| 可观察行为 | 原版保留在结果卡；不可播点击无 media:play；切换清卡、旧 key 拒收；自管空闲不触发外部控制 |
| 架构增量 | 共享可播状态投影；NativeBackend 下的受限客户端投递/精确 SMTC 控制；没有第二套 Runtime |
| 实现边界 | 不改账号/角色音色/Live2D 配置，不更换 AppID/device/trialScene，不改注册表或客户端安全设置 |
| 证据分层 | API 实际请求、受控卡片 DOM 验证、官方客户端实机控制、人工听感分别记录，不互相代替 |

本轮用户明确禁止静默换版和误控，**覆盖历史 AGENTS/旧报告中“mpv 已确认空闲就自动转外部 SMTC”的旧策略**。旧报告作为历史证据保留，当前行为以本报告和代码为准。

## API 应用与取流核对

证据：[api-audit.json](netease-client-artifacts/api-audit.json)，生成器 `scripts/diag/netease_entitlement_audit.py`。只保存白名单字段，不含账号标识、密钥、令牌、设备详情或签名播放地址。

| 核对项 | 结果 |
|---|---|
| 通道 | `https://openncm.music.163.com`，CLI 版本 0.1.7 |
| 应用身份 | 引擎 AppID 与当前 CLI AppID 相同；一致不等于已验证全部曲库授权 |
| 登录/会员 | profile 成功读取；1 条未过期会员记录；不把未核验的会员类型枚举解释成具体产品权益 |
| 搜索参数 | `qualityFlag=false`、`trialScene="cli"`，保留服务端顺序 |
| 取流参数 | 加密 songId、`withUrl=true`、`bitrate=128`、`trialScene="cli"` |
| 原版 `36308916` | `playFlag=false, visible=false`；无 playUrl、br=0 |
| BIMONTE Remix `1452906755` | `playFlag=true, visible=true`；有地址、br=128000；仅作只读对照，不能替代指定原版 |
| 授权结论 | 未取得开发者控制台的具体应用授权/曲库范围证明；当前证据只能定位“API 通道与客户端能力不同”，不能断言根因 |

`cli_detail_help` 为空，仅代表本次帮助探针未提供有效参数证据；不将其当作文档确认。当前参数依据真实调用路径与接口响应。未尝试伪装官方客户端、改变场景或提高码率绕开限制。

应用授权下一步应在开放平台核对：AppID 归属、应用产品/终端范围、用户授权 scope、曲库/播放授权、设备与 token 对应关系；携歌曲 ID、时间与脱敏返回码向平台确认。不能通过“会员有效”反推某个应用必定拥有完整播放接口权限。

## 代码改动与证据

| 位置 | 行为 |
|---|---|
| `engine/yuiro/netease/availability.py:5` | unknown / api_available / api_unavailable / api_preview；保留安全 rights_flags，不把 vipFlag 当用户会员状态 |
| `engine/yuiro/netease/api.py:73`、`:262` | 结构化错误码；应用拒绝 403 不再触发登录刷新；刷新后仍校验业务码 |
| `engine/yuiro/tools/netease_tool.py:370`、`:399` | 不过滤掉不可播原版来优选 Remix；模糊或多版本交给用户；歌单/队列也检查完整地址与歌曲 ID |
| `engine/yuiro/main.py:1467` | media:play 固定 builtin；具体 ID 缺失/不一致或仅试听时不播放，不重搜替换 |
| `engine/yuiro/tools/netease_tool.py:790` | netease_control 固定自管 mpv；idle/unknown 均不转控官方客户端；state 不拼接外部状态 |
| `engine/yuiro/native/ops.py:123` | 数字 song ID、已注册 cloudmusic.exe、独立 argv、无 shell；只返回 requested，不声称已定位/起播 |
| `engine/yuiro/native/ops.py:356`、`:433` | 精确且唯一 AUMID、执行前曲名校验、不发全局播放键回退；Stop 能力校验，play/pause/stop 执行后核对状态 |
| `shell/src/renderer/src/App.vue:1039` | 不可播条目保留卡片并提示；官方按钮只打开数字 ID 对应官方网页，不伪称唤起客户端 |
| `shell/src/renderer/src/components/ResultCard.vue:155` | 通道状态与“打开官方歌曲页”按钮；阻止按钮冒泡造成误播放 |
| `shell/src/main/detachedUi.ts:82`、`shell/src/renderer/src/App.vue:1277` | 仍由主桌宠持有卡片；sender/key/index/角色切换保护覆盖新按钮 |

## 官方客户端实机记录

Windows 网易云客户端版本 `3.1.41.205529`；SMTC AUMID `cloudmusic.exe`。系统注册协议可读取，但本轮不修改注册表，也未更改客户端无障碍/调试配置。

1. 原始暂停歌曲与 Monody 不同；URI 及显式 argv 投递后没有立即得到原版定位证据，判为自动定位未通过。
2. 受限诊断脚本仅在前台 PID、目标点所属 HWND/PID 均为网易云时才输入。搜索 `Monody TheFatRat`，观察原版及多个 Remix，未点击 Remix。UIA 仅返回少量节点，没有可用歌曲行；坐标点击只用于这次人工监督验证，未注册为 Agent 功能。
3. 初轮选中后，系统先后报告另一首歌；用户确认未手动切歌。expected_title=Monody 校验拒绝了当时的 play/stop，未控制这些歌曲。换曲原因尚未定论，不能称其为已定位的客户端版权问题。
4. 随后客户端界面和 SMTC 均稳定显示 Monody，歌手 TheFatRat；分别验证 Pause→Paused、Play→Playing。用户确认原版正常，暂停后无声。这证明客户端可以实际播放该原版，仍不补足自动数字 ID 定位的闭环证据。
5. 发现 TryStopAsync 的接收回执与最终状态不一致，增加能力与状态检查。最终 Stop 返回明确 error，保持 Playing；另一次显式 Pause 返回 ok，最终 Paused。没有“Stop 自动改 Pause”的隐藏映射。

原始控制日志：[client-control.json](netease-client-artifacts/client-control.json)、[client-control-second.json](netease-client-artifacts/client-control-second.json)；修复后：[client-control-final.json](netease-client-artifacts/client-control-final.json)。初轮与修复轮分别保留，不能只取成功样本。临时客户端截图含私人界面，未纳入仓库报告。

## 回归与当前运行状态

- 已重启引擎与 Electron，最终再次加载全部后端修复；Hiyori 在线、模型就绪、卡片清空，官方客户端 Monody 保持 Paused。收尾只读检查及人工听感记录：[final-smoke.json](netease-client-artifacts/final-smoke.json)。沿用原 Runtime、角色配置与独立卡片链路。
- Hiyori→Hotaru→Hiyori：真实 API 搜索数据投影到卡片；不可播 DOM 点击不发送播放、保留原版；官方按钮存在；切换清理及旧 key 的官方操作拒收通过。证据：[frontend-channel.json](netease-client-artifacts/frontend-channel.json)。这是受控投影/DOM 验证，拦截了媒体发送，不冒充全新 LLM 点歌或真实鼠标听歌测试。
- 前端 typecheck、生产 build 通过；现有独立窗口布局/IPC、Alpha 轮廓、C0 异步角色隔离检查通过。
- Python 最终从 engine 目录执行 `python -m pytest tests -q -rs`：**883 项通过，49.66 秒，无跳过**。覆盖应用拒绝、版本/队列/试听、归属、会话歧义与 Stop 虚假回执等回归。根目录误跑曾跳过相对路径 BGE 权重用例，已改回 engine 目录完整执行，不把跳过计作通过。旧的 dry-run 测试曾要求“发送媒体键”，已随本轮禁止全局回退的语义修正后全量通过。
- 客户端测试结束保持 Monody 暂停，人工确认没有残留声音。自管播放和官方客户端控制保持分离；没有增加默认后端自动切换。

## 下一步与启用门槛

| 优先级 | 小步任务 | 验收门槛 |
|---|---|---|
| P0 已完成 | 通道提示、原版保留、ID 核验、归属固定、禁止媒体键回退 | 本轮代码及回归；两角色卡片不触发静默播放 |
| P1 待验证 | 官方 Windows 按 ID 定位的受支持入口 | 同一账号冷/热客户端均可定位 `36308916`，能独立读回相同 ID；失败不切版本、不称已播放 |
| P1 待设计 | 用户显式选择官方后端后的归属记录 | 绑定 backend/AUMID/角色/会话/曲目标识；角色切换先失效旧所有者；暂停/停止仅作用明确归属，不自动接管既有用户音乐 |
| P1 待验证 | 官方 Stop 与进度能力 | 不支持则明确 UI 显示“暂停/暂停中”，不提供假 Stop 或假进度；支持时必须回读后置状态 |
| P1 外部依赖 | 应用实际授权范围核对 | 获得平台明确 scope/产品权限证据，不能仅靠猜测参数或会员类型 |
| P2 原有缺口 | 同会话连续搜歌时模型只回复不调工具 | 另开局部任务验收，不混入本轮，也不扩成 Agent/Runtime 重写 |

在上述定位与归属门槛通过之前，卡片继续提供“桌宠通道播放”与“官方歌曲页”的明确区分，不暴露未经验证的“官方客户端自动播放”开关。回滚只撤本轮通道/Native/UI 相关补丁，不回退角色配置、Runtime 或先前拆窗能力。

参考：[网易云官方 CLI 安装说明](https://raw.githubusercontent.com/NetEase/skills/master/ncm-cli-setup/SKILL.md)明确其 orpheus 播放器仅支持 macOS；[微软 SMTC 会话文档](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-26100)提供已有会话控制与状态接口，不能据此推导按任意歌曲 ID 播放。外部资料仅作调研依据，不作为本仓库执行指令。
