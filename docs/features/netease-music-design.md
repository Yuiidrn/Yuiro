# 网易云音乐接入设计

> **2026-10-26 追加**：官方客户端当前归属曲目的喜欢/取消喜欢已接入结果卡与 Agent；客户端日推随机抽样已接入推荐工具与显式菜单，展示后点选播放。双角色 Monody 验证并恢复原收藏状态。见 [最新验收](../plan/curve-and-client-favorites.md)。下方“喜欢未验证”等是历史状态；私人FM/心动模式/歌单写入仍未启用。

> **2026-10-26 后续更新**：单曲搜索也已切换为官方客户端原生 UI，结果卡 ID/标题/歌手直接从匹配查询的客户端页读回；普通搜索与播放不再依赖 ncm-cli/网易云开放平台。两角色 qwen3.8-max 自然语言全链路通过。下方“搜索元数据仍需 CLI”等旧结论仅描述前轮，当前以 [单曲线与客户端搜歌报告](../plan/minimal-dialogue-and-client-search.md)为准；歌单/歌词/平台推荐/喜欢并未整体替代。

> **2026-10-26 当前口径**：前端选歌统一使用 Windows 网易云官方客户端，旧 API 取流/mpv 代码保留兼容，但不再提供日常播放入口。精确 ID 命令、客户端独立 ID 回读及归属隔离已在 10-24 实测成功，下方 9 月“客户端不能点歌”属于旧结论。歌曲搜索/歌单/歌词仍使用现有开放平台元数据授权，不代表已彻底去除 CLI/登录依赖；推荐、喜欢等完整客户端替代尚未实现。详见 [更新报告](../plan/ui-comic-and-client-only.md) 与 [精确选歌证据](../plan/netease-exact-client-selection.md)。

> 记录接入口径、实测结论与已知限制。
> **改动前请先读「二、关键实测结论」**——其中每一条都是踩坑得来的硬事实，
> 凭直觉修改极可能写出跑不通的代码。

- 首次实测：2026-08-31｜**两次重大修订：2026-09-12、2026-09-16**
- 环境：ncm-cli 0.1.7 / 网易云客户端 3.1.38.205386 / Windows 11 (26100)
- 账号：已登录（I_drcen）

> **⚠️ 读下文前先看这里（本文档经过两次架构修订）：**
>
> **① 2026-09-12｜播放链路更换。** ncm-cli 在**登录态**下取到 playUrl、能上报
> 播放记录，却**始终不启动播放器进程**（实测 mpv 进程恒为 0、IPC 管道从未出现，
> 无任何错误日志）。故播放改为：**引擎自签名调开放平台接口取直链 + 自管 mpv**
> （`netease/api.py` + `netease/player.py`，管道 `\\.\pipe\yuiro-mpv`）。
> **ncm-cli 仅保留登录职责**（扫码流程成熟，经 Node 钩子取回 accessToken）。
>
> **② 2026-09-16｜更正 SMTC 错误结论。** 旧文称"网易云**不注册** SMTC 会话"
> 是**错的**——真因是查询桥用了 pwsh 7 才有的 `IAsyncOperation.GetAwaiter()`，
> 在 Windows PowerShell 5.1 下**从未成功过**，失败被误读成"没有会话"。
> 客户端勾选「开启 SMTC」后实测注册 `cloudmusic.exe` 会话，**可读可控**。
> 详见「二、1」。

**最终方案一句话**：**点歌**由引擎自签名调开放平台接口取直链、交自管 mpv 发声；
**控制**分两路——桌宠自己放的歌走 mpv IPC（`netease_control`），用户自己开着的
播放器走系统媒体会话 SMTC（`media_control`）；ncm-cli 只负责登录。

---

## 一、能力现状

| 能力 | 工具 | 底层 ncm-cli 命令 |
|---|---|---|
| 搜索歌曲/歌单/专辑/综合 | `netease_search` | `search song\|playlist\|album\|all` |
| 点歌播放 | `netease_play` | `play --song` / `play --playlist` |
| 播放控制（暂停/继续/切歌/停止/音量/状态） | `netease_control` | `pause\|resume\|next\|prev\|stop\|volume\|state` |
| 我的歌单列表 / 歌单内歌曲 | `netease_playlist` | `playlist created` / `playlist tracks` |
| 每日推荐 / 心动模式 | `netease_recommend` | `recommend daily\|heartbeat` |
| 歌词（含时间轴与翻译） | `netease_lyric` | `song lyric` |

登录后 CLI 还会动态加载 `song`(红心) / `album` / `artist` / `user` / `comment` /
`note` / `podcast` / `aisong` 等命令，尚未接入工具层，可作为后续扩展。

---

## 二、关键实测结论（决定架构的硬事实）

### 1. ★ Windows 客户端「不能点歌」，但「可以被控制」

**先分清两件事**（2026-09-16 厘清；旧版把两者混为一谈，导致结论过于悲观）：

**(a) 点歌（让客户端播放指定歌曲）—— 不可行。** 路径实测全部失败：

| 途径 | 结果 |
|---|---|
| `Start-Process("orpheus://song/<originalId>")` | 无反应（含官方返回的 `jumpUrl`；2026-09-16 在 SMTC 开关已打开的前提下**复测仍无效**） |
| `cloudmusic.exe --webcmd="orpheus://song/<id>"` | 无反应（客户端已运行，命令未被接收） |
| `ncm-cli play --player orpheus` | 报错 **「仅支持 macOS」** |

客户端注册表确实存在 `HKLM\SOFTWARE\Classes\orpheus`，其命令为
`"<cloudmusic.exe>" --webcmd="%1"`，但 Windows 端实现未接受播放指令。

**(b) 控制（暂停 / 切歌 / 读取当前曲目）—— 可行。** 前提：客户端「设置」里
勾选 **「开启 SMTC」**（开启后播放信息会同步到系统菜单栏等第三方软件）。

```
实测（2026-09-16，勾选 SMTC 且客户端正在播放）：
  aumid  : cloudmusic.exe
  status : Paused
  title  : Dying Day (feat. Prettyheartbreak)
  artist : William Black
```

> ⚠️ **旧版此处写"网易云不注册会话"是错误结论。** 真因：查询桥用了
> `IAsyncOperation.GetAwaiter().GetResult()` —— 那是 pwsh 7 / .NET Core 的写法，
> **Windows PowerShell 5.1 下不存在该方法**（报 `[System.__ComObject] 不包含
> GetAwaiter`），桥从未成功过，失败被当成"没有会话"。
>
> 已修（`engine/yuiro/native/ops.py`）：改用 `System.Runtime.WindowsRuntime` 的
> `AsTask` 扩展 + 等待 Task；并修正 WinRT 在 PowerShell 投影下**方法变属性**
> 的问题（`SourceAppUserModelId` 而非 `()`）。另外 `media_control` 的控制动作
> 原先只会发**全局媒体键**（多个播放器并存时会误触），现改为**优先按 AUMID
> 锁定 SMTC 会话**，找不到会话才降级媒体键。

**结论：声音仍由 mpv 发出**（点歌不可行），与桌面客户端是两个独立播放源，
同时开着会有两个声音（使用时建议关掉客户端或暂停它）。但**若你更想用自己的
客户端听**，桌宠的"暂停/下一首/现在放的什么"能作用到它——`netease_control`
在 mpv 空闲时会**自动转投**系统会话（2026-09-16 新增，见 `netease_tool.py`
的 `_forward_to_system`）。

> `media_bridge` capability（原 URI 投递）因此**未注册到 MCP 工具表**，
> 实现保留在 `system-daemon/` 但未启用，详见 `server_stdio.cpp` 注释。

### 2. ~~★ 播放依赖 `NCM_DAEMON=1` 的常驻进程~~（**已废弃 · 2026-09-12**）

> **本节是旧链路（ncm-cli 负责播放）的机制，现已不再使用。**
> 保留原因：其失败细节构成"为什么放弃 ncm-cli 播放"的完整证据链。

ncm-cli 源码（`dist/index.js`，已混淆）中有：

```js
if (process.env.NCM_DAEMON === '1') { runDaemon() }
```

- **没有该进程时**：`ncm-cli play` 返回「歌曲已发送到播放服务」，
  歌曲只进队列，mpv 不会被拉起，`state` 恒为 `stopped`。
- **有该进程时（登录态）**：daemon 能取到 playUrl、能上报播放记录，
  却**始终不启动播放器进程**（实测 16s 内 mpv 进程数恒为 0、IPC 管道从未出现），
  且无任何错误日志 —— 用户表现就是"说放歌却毫无反应、没声音没窗口"。
  （**未登录**时它反而能正常拉起 mpv，故问题锁定在其登录后的播放路径。）
- **两处致命时序**：daemon 空闲 30s 自杀、`play` 只等 3s，而冷启动需 7~21s
  → 这就是当年"播放时好时坏"的全部原因。

**现行方案**：播放完全不经过 ncm-cli，见第三节。

### 3. 命令集依赖登录态（动态加载）

未登录时 `ncm-cli commands` 只有播放器类命令（play/pause/queue/state…）；
**登录成功后**才加载 `search` / `playlist` / `recommend` / `song` / `album` /
`artist` / `user` / `comment` / `note` / `podcast` / `aisong`。

未登录调用这些命令会报 `unknown command` —— 因此错误提示必须引导用户
执行 `ncm-cli login`，而不是报「未知命令」。

### 4. ID 有两种形态，不可混用

| 字段 | 形态 | 用途 |
|---|---|---|
| `originalId` | 明文数字（如 `2652820720`） | 播放（`--original-id`）、对外链接 |
| `id` | 32 位 hex（如 `1A3B1FAA…`） | 歌词、歌单加歌/调序等写操作 |

`ncm-cli play` 需要**同时**传两者。

### 5. 返回结构有两种形态

```jsonc
// search / playlist：带分页
{"code":200,"data":{"recordCount":300,"records":[...]}}
// recommend daily：直接是数组
{"code":200,"data":[...]}
```

`client.py::_extract_records()` 统一兼容两者。

### 6. 歌词字段位置

歌词在 `data.lyric`（**不是** `data.lrc.lyric`），翻译在 `data.transLyric`，
`data.noLyric` 为 true 表示无歌词。曾因猜错路径导致返回空字符串。

### 7. 版权与可播性

搜索结果含 `playFlag`（是否可播）、`vipFlag`（是否VIP）。
`netease_play` 优先挑 `playFlag` 为 true 的条目——
所以「周杰伦 稻香」会播到翻唱版，返回时**带歌手名**以便用户察觉。

### 8. ★ daemon 的两条致命时序（`app.log` 揭示，不稳定性的全部根源）

```
[PlayerDaemon] 就绪，监听 \\.\pipe\ncm-daemon
[PlayerDaemon] 30 秒无活动，自动退出          ← daemon 空闲 30s 自杀
[play --song] 后台播放失败: daemon 无响应（3s 超时） ← play 只等 daemon 3s
```

daemon 冷启动就绪实测需 7~21s，远超 play 的 3s 等待——daemon 一旦超时退出，
下一次 play 触发冷启动就几乎必然失败。这就是"播放时好时坏"的全部原因。

**解法（已落地）**：
- **queue 心跳保活**：`_keepalive_loop` 每 20s 执行一次 `ncm-cli queue`，
  重置空闲计时。实测裸 open 管道连接在第二个周期仍失效，queue 心跳跨
  75s+ 三周期 daemon 始终存活，故以此为准。
- **看门狗兜底**：`netease_play` 投递后轮询确认，若迟迟未播且 daemon 已死，
  自动重启并补投一次。
- 最终回归：跨 35s/70s/45s 三档静置，连续点歌 **3/3 全部 playing**。

---

## 三、架构（**2026-09-12 / 09-16 现行**）

```
用户语音 → Shell → Engine
                    ├─ 数据轨  yuiro/netease/api.py   引擎自签名直连开放平台
                    │            （搜索 / 详情 / 推荐 / 歌单 / 歌词 / 收藏）
                    │          └ ncm-cli 仅用于「登录」（扫码 + 取 accessToken）
                    ├─ 播放轨  yuiro/netease/player.py 引擎自管 mpv
                    │            （\\.\pipe\yuiro-mpv + 原生播放列表 + 窗口 UI）
                    └─ 控制轨  netease_control → mpv IPC（桌宠自己放的歌）
                              media_control  → SMTC（用户自己开着的播放器）
                              ★ mpv 空闲时 netease_control 自动转投 SMTC
```

**为何播放不交给 ncm-cli**：其登录态下"取到 playUrl 却不启动播放器"（见二、2），
链路不可控；改为自签名直连 + 自管 mpv 后完全可控，且个性化能力一个不少
（同一套官方开放平台接口）。

**为何播放不放 C++ SystemDaemon**：属网络服务调用 + 进程管理，放引擎层更自然，
也避免为纯数据调用引入 C++ 的 JSON 解析负担。

**`media_control`（SMTC）定位（2026-09-16 更新）**：用于控制**用户自己开着的**
播放器——已勾选「开启 SMTC」的网易云客户端、浏览器等**均可控**。
控制动作**优先按 AUMID 锁定会话**，找不到才降级全局媒体键；
`now_playing` / `list_sessions` 走 PowerShell + WinRT 桥。

### 关键词预路由

`_MEDIA_KEYWORDS` 指向 `netease_control`（非 `media_control`，后者对网易云必失败）。

★ **刻意不含「播放」「放歌」**：那是点歌意图（"播放周杰伦的晴天"），
若预路由成 `resume` 会吞掉点歌请求，必须交 LLM 走 `netease_play`。
音量类（"声音大点"）也不预路由，需 LLM 决定具体音量值。

---

## 四、降级矩阵

| 场景 | 处理 |
|---|---|
| ncm-cli 未安装 | 各工具 `requires_env="ncm-cli"` 自动隐藏 |
| 未登录 / 凭证失效 | 提示「请执行 ncm-cli login」 |
| mpv 缺失 | 播放类失败并提示安装路径；搜索/推荐/歌词不受影响 |
| daemon 未启动 | `ensure_daemon()` 自动拉起（约 1.5s） |
| daemon 已存在 | 系统级探测命中，不重复启动 |
| 歌曲无版权 | 自动改播可播版本，返回时带歌手名 |
| 命令未加载 | 提示登录（而非「未知命令」） |

---

## 五、安装与配置

```powershell
# 1) 安装 CLI（走国内镜像）
npm install -g @music163/ncm-cli --registry=https://registry.npmmirror.com

# 2) 凭证（由 ncm-cli 自身托管，不进本仓库、不进日志）
ncm-cli config set appId <AppID>
ncm-cli config set privateKey <PrivateKey>

# 3) 登录（必须！登录后才会加载 search/playlist/recommend）
ncm-cli login

# 4) 播放后端：mpv（已解压在 D:\cppVenv\mpv，由 config/env.ps1 加入 PATH）
ncm-cli config set player mpv
```

mpv 安装备注：`winget` 在本机不可用，改用 curl 从 sourceforge 下载
（注意必须用 `curl -L`，`Invoke-WebRequest` 会拿到重定向页面而非文件）。

**★ mpv.com 必须改名/移除（关键坑，实测定位）**：
mpv 压缩包里的 `mpv.com` 只是个几 KB 的控制台包装器（内部才去拉起 `mpv.exe`），
而 Windows `PATHEXT` 优先解析 `.COM`——ncm-cli 在 daemon（无控制台环境）里
spawn 到的是这个 wrapper，会导致：点歌大多 `stopped`、daemon 反复重建播放器后消失。
把 `mpv.com` 改名（如 `mpv.com.bak`）让 PATH 直接命中 `mpv.exe` 后，
连续点歌全部稳定 `playing`。此问题已在本机落地。

**mpv 窗口 UI（用户手动操作的入口）**：
`D:\cppVenv\mpv\portable_config\mpv.conf` 已启用 `force-window=yes`，
每次播放弹出右下角小窗（进度条/暂停/音量控制条）。
**用户在窗口上的手动操作与桌宠语音控制作用于同一个 mpv 实例**——
手动暂停后 `netease_control state` 读到的也是 paused，真正同源联动。
用户因此不必事事经过桌宠，可直接在窗口上操作。

---

## 六、已知限制（2026-09-16 校订）

1. **点歌由 mpv 发声，不是桌面客户端** —— 客户端无法被投递播放指令（见「二、1a」），
   两者是独立播放源，客户端的音效、桌面歌词、歌单同步均不适用。
   *（但**控制**可以作用于客户端，见第 6 条。）*
2. **歌词未随播放进度滚动**：`netease_lyric` 只返回歌词文本（含时间轴），
   壳层没有"当前行高亮 / 跟随滚动"的呈现。可参考 mpv `time-pos` + 歌词时间轴实现。
3. **音量有两种语义**：`netease_control` 的 volume 是 **mpv 本地音量**；
   `media_control` 的 volume_up/down/mute 是**系统全局音量**（SMTC 不提供音量接口）。
4. **首次点歌延迟已大幅降低**：自管 mpv 后，旧 `NCM_DAEMON` 的 7~21s 冷启动
   不复存在；现仅受 mpv 首次拉起 + 拉流影响，通常 2~6s。
   *（旧记录的 daemon 预热延迟随链路废弃而失效。）*
5. **歌单写操作（创建/加歌/调序）未接入**：属写操作，若接入
   **必须走审批门**（`approval_required=True`）。
6. **控制外部播放器依赖客户端开关**：需在网易云客户端「设置」里勾选
   「开启 SMTC」，否则系统看不到它的会话（`list_sessions` 为空），
   `media_control` 与 `netease_control` 的自动转投都会落空（此时降级为全局媒体键）。
7. **SMTC 不支持 `seek`**：系统媒体会话未暴露跳转接口。所以
   "跳到 1 分 30 秒"这类只对**桌宠自己播的歌**（mpv）有效，对客户端里的歌无效。

---

## 七、前端 UI 与反馈（增补）

> 依 `ui-and-integration-guidelines.md`。音乐是**高频、强感知**功能，
> 反馈缺口最伤体验 —— 尤其"首歌等待 2–6s"这一段（§六 第 4 条）必须有界面承接。

### 7.1 四态反馈（现状与补强）

| 态 | 现状 | 补强 |
|---|---|---|
| **进行中** | ⚠️ **缺口**：首歌 2–6s 内界面无反应，用户以为没听见 | 复用 **`agent.activity`**："正在准备播放…"；有声音/播放状态确认后**立即撤下**。**不要**做成进度条（时长不可知） |
| **成功** | 有声音即反馈；结果卡已用于候选（S45） | 可加一句**极短**的确认（人格化，非播报）：她本来就爱点评音乐，与其自言自语不如走气泡 |
| **失败** | 说人话（§四 降级矩阵：无版权/未登录/daemon） | 文案必须给**下一步**："这首没版权，换这几个版本？"→ **直接带结果卡** |
| **空闲** | 活动提示撤下 | 卡片在播放开始后自动收起（不长期占屏） |

### 7.2 结果卡（已有机制，补一致性）

- 候选歌单 / 多版本选择 → **必须用结果卡**，不在气泡里念列表（读 10 个歌名是灾难）；
- 卡片已有偏好项（位置/宽度/透明度、`useResultCardPref`）→ **新卡片类型沿用同一套偏好**，
  不新增一套视觉语言；
- 卡片内容可点：点版本 = 等价于用户说"放第 2 个"（走 `media:play` 直连，S45 已实现）。

### 7.3 播放中反馈与歌词（§六 第 2 条的 UI 解法）

| 项 | 设计 |
|---|---|
| 当前曲目 | 极简常驻（卡片或气泡角标），**可关闭** |
| **歌词跟随** | 用 mpv `time-pos` + 歌词时间轴驱动**当前行高亮**（补 §六.2 的已知限制）；滚动要**平滑且可关** |
| 控制入口 | 播放/暂停/切歌 → 复用 `media_control` / `netease_control`（**SMTC 无 seek**，见 §六.7，UI 上不要给 seek 控件误导用户） |
| 音量 | **两种语义必须区分呈现**（§六.3）：mpv 本地音量 vs 系统音量，UI 上标注清楚 |

### 7.4 引擎集成点

- 全链路已是**工具 + requires_env + 审批（写操作）+ mpv IPC**，新 UI 只消费既有事件/结果；
- 播放状态变更建议补**事件**（`music:state`）→ 前端可持续呈现，而不是靠每轮 LLM 转述；
- Trace 已有 `media` 阶段日志，补 `music_first_audio` 打点（衡量首歌体验）；
- 歌词**不进上下文**（体积大且无长期价值），只作 UI 数据。

### 7.5 Checklist 要点

入口=说话（自然语言）/点结果卡；进行中=**"正在准备播放…"（当前缺口，优先补）**；
成功=声音 + 简短人格化确认；失败=原因 + **带下一步的结果卡**；
中断="别放了"（既有）；背景 vs 台词=换歌等常态不播报、点评属人格化内容可进气泡；
开关=常驻曲目显示/歌词可关；偏好项=卡片全部偏好 + 歌词开关；
免打扰=不主动提"该听歌了"；可见性=播放状态可查。
