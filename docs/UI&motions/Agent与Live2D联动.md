# Agent 与 Live2D 模型动作联动

> 适用范围：引擎 `engine/yuiro/` + 壳层 `shell/`（pixi-live2d-display / Cubism 4 Core 5.1）
> 整理日期：2026-10
> **定位方式：文件 + 函数/常量名。本文刻意不写行号** —— 项目迭代快，行号必然漂移，
> 搜函数名永远能找到（例如在 IDE 里搜 `applyAvatarIntent` / `resolve` / `_BUILTIN_PERFORMANCES`）。

本文覆盖：从 LLM 一次工具调用（或一次情绪变化）到模型做出表情/动作的完整链路、表现如何解析、调试台怎么用，以及如何自行调参数、配比与循环。

---

## 0. 一张图

```
┌─ 引擎 ────────────────────────────────────────────────────────────────┐
│ A 情绪引擎（自动）      B Agent 工具（LLM 点播）     C 调试台（手动）      │
│ EmotionEngine          avatar_perform            HTTP /  avatar:perform │
│    │                      │                       IPC dev:apply-intent  │
│    ▼                      ▼                              │            │
│  AvatarIntent ──────► AvatarRuntime ──► PerformanceResolver             │
│  (语义：情绪/表情/动作)     │      （表演 → 表情槽位 + 动作槽位 + 时长）    │
│                           ▼                                            │
│      broadcast_control({"type":"avatar:intent", ...})                  │
│      · 有具体名就带 expression / motion  · 否则只带 *_slot              │
└───────────────────────────┬───────────────────────────────────────────┘
                            │ 另有模型清单（主进程）
                            │ live2d:inspect-model → slot → 具体资源
                            ▼
                            │ WebSocket /ws/control
                            ▼
┌─ 壳层 App.vue ────────────────────────────────────────────────────────┐
│ WS 分发：msg.type === 'avatar:intent' ─┐                               │
│ shell 事件：'avatar:perform'  ────────┴──► applyAvatarIntent(...)      │
└───────────────────────────┬───────────────────────────────────────────┘
                            ▼
┌─ Live2DCanvas.vue ────────────────────────────────────────────────────┐
│ applyAvatarIntent                                                     │
│   ├─ resolveExpression(manifest, intent)  具体名(校验) → 槽位 → 不改     │
│   ├─ resolveMotion(manifest, intent)      组#索引(校验) → 槽位 → null   │
│   ├─ playMotion(...)  校验 → startMotion(优先级) → 读真实时长            │
│   └─ scheduleRelease(时长)  到点回到 neutral 并恢复待机调度              │
│ Pixi ticker 每帧：写 ParamMouthOpenY（口型）→ model.update()            │
│ 待机调度：只播 idle 槽位动作，播完停顿 6~12s 再播下一个（不随机变脸）      │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 1. 触发源（三条路，最终汇到同一个入口）

### A. 情绪引擎（自动跟随，不需要 LLM 参与）

主情绪变化时发两条消息：`emotion:set`（壳层显示"当前心情"）与 `push_emotion`（驱动表情）。

| 文件 | 符号 / 位置 | 说明 |
|---|---|---|
| `engine/yuiro/main.py` | 情绪变化回调里的 `broadcast_control({"type": "emotion:set", ...})` | 推给壳层做心情展示 |
| `engine/yuiro/main.py` | 同处的 `await avatar.push_emotion("", changed)` | 推给头像运行时 |
| `engine/yuiro/main.py` | 情绪衰减定时循环（`_decay` 相关） | 同上，周期性也会触发 |
| `engine/yuiro/main.py` | `avatar.push_emotion(session_id, "thinking")` | 说话链路状态也走这条 |
| `engine/yuiro/avatar/runtime.py` | `AvatarRuntime.expression_for()` | 情绪 → 表情名（读生效的 expression_map） |
| `engine/yuiro/avatar/runtime.py` | `AvatarRuntime.push_emotion()` | 组出 `AvatarIntent(priority=EMOTION)` |

### B. Agent 工具（LLM 主动点播一次表演）

| 文件 | 符号 | 说明 |
|---|---|---|
| `engine/yuiro/tools/avatar_tool.py` | `class AvatarPerformTool` | 工具名 `avatar_perform` |
| `engine/yuiro/tools/avatar_tool.py` | `await avatar.perform(task_id, name, source="agent")` | 交给运行时解析 |
| `engine/yuiro/agent/activity.py` | `_ACTIVITY_MOTION` | 工具 → 动作提示的映射（"正在表演…"文案在这里） |

工具描述里写明了推荐用法（用户报喜 / 受挫 / 回来 / 意外 → `celebrate` / `comfort` / `greet` / `surprise`）。
`approval_required = False`，但按 `capability.scope` 对 `avatar_perform` 归为 external 副作用，只读档位会被拒。

### C. 调试台

| 通道 | 文件 / IPC | 是否需要引擎 |
|---|---|---|
| `POST /api/avatar/perform/{name}` | `engine/yuiro/debug_api.py` → `avatar_perform` | **需要** |
| `GET /api/avatar/performances` | `engine/yuiro/debug_api.py` → `avatar_performances` | 需要（列表来源） |
| `dev:apply-intent`（试演直连） | `shell/src/main/index.ts` → 发 `avatar:perform` 事件 | **不需要** |
| `dev:play-motion` / `dev:preview-expression` | 同上 | 不需要 |

直连通道与引擎的 `avatar:intent` 走**同一个渲染入口**：`App.vue` 的 `onShellEvent()` → `applyAvatarIntent`。

---

## 2. 传送与壳层分发

| 环节 | 文件 / 符号 |
|---|---|
| 广播函数 | `engine/yuiro/approval.py` → `broadcast_control()`（遍历所有 `/ws/control` 连接） |
| 意图组包 | `engine/yuiro/avatar/runtime.py` → `AvatarRuntime._broadcast({"type": "avatar:intent", **intent.to_payload()})` |
| 优先级裁决 | `engine/yuiro/avatar/runtime.py` → `if intent.priority < cur.priority: return False` |
| 壳层分发 | `shell/src/renderer/src/App.vue` → WS 分支 `msg.type === 'avatar:intent'` / `'agent:activity'`；`onShellEvent()` 处理 `avatar:perform` |

`agent:activity` 是另一条联动：工具活动 → 状态行 + **动作提示**（前端节流 6 秒最多一个动作，见 `App.vue` 的 `lastActivityMotionAt`）。
壳层优先用 `TapBody` 组，没有就退回该模型第一组。

### 意图载荷（`avatar:intent`）

定义在 `engine/yuiro/avatar/intent.py` 的 `AvatarIntent.to_payload()`，空字段不发送：

```jsonc
{
  "type": "avatar:intent",
  "source": "emotion | speech | agent | system",
  "priority": 1,              // 见下表
  "emotion": "happy",         // 可选：语义情绪
  "expression": "happy",      // 可选：模型表情名；"" = 回落默认；缺省 = 不改
  "motion": "Idle",           // 可选：动作组名
  "motion_index": 4,          // 可选：组内索引；缺省 = 该组随机
  "duration_ms": 5670         // 可选：一次性表演的有效期
}
```

优先级枚举（`intent.py` 的 `AvatarPriority`）：
`IDLE=0 < EMOTION=1 < SPEECH=2 < ACTION=3 < USER=4 < SYSTEM=5`。
低优先级不会覆盖尚未完成的高优先级意图。

---

## 3. 表演如何解析成「表情 + 动作 + 时长」

核心：`engine/yuiro/avatar/performance.py` 的 `PerformanceResolver`。

### 优先级

```
[persona.profiles.<档案>].performance_map   （per-model，最高）
        >  [persona].motion_map              （全局，只改动作组）
        >  内置表演包 _BUILTIN_PERFORMANCES
```

- 解析入口：`PerformanceResolver.resolve()`
- 表演库 = 内置包 ∪ performance_map 的自定名：`PerformanceResolver.names()` / `library()`

### 取值语法（`performance_map` 的值）

```
"expression7, TapBody#4"   表情 + 动作
"expression6"              只改表情
", TapBody#7"              只改动作
"TapBody#4"                单独写带索引的动作也按动作处理
```

解析规则：以**第一个逗号**分两段；无逗号时含 `#` 视为动作，否则视为表情。

### 时长（决定表情何时回落）

```
运行时真实动作时长（前端探测 motionDurationMs）
    > 引擎时长表 motion_duration_ms(组, 索引)
    > DEFAULT_PERFORMANCE_MS = 2600
```

引擎时长表按**组名（小写）**索引（`performance.py` 的 `MOTION_DURATIONS_BY_GROUP`）：

| 组 | 表 | 适用模型 |
|---|---|---|
| `TapBody` | `TAPBODY_DURATIONS_MS` | 肥牛（13 个）、hiyori（1 个） |
| `Idle` | `IDLE_DURATIONS_MS` | hiyori 官方示例的 9 个 |
| `Extra` | `EXTRA_DURATIONS_MS` | hiyori 的 3 个迁移动作（1.1s / 1.1s / 4.7s） |

短于基准的动作会用基准时长（表情多留一会儿，观感更自然）。
新模型补表：跑 `engine/scripts/motion_scan.py` 扫描各 motion3 的 `Meta.Duration`。

---

## 4. 每模型表现档案（切换模型即整套表现跟着换）

### 配置结构

```toml
[persona.profiles.hiyori]
model = "/live2d/hiyori/Hiyori.model3.json"
note  = "桃瀬ひより"

[persona.profiles.hiyori.expression_map]   # 命中后**整表替换**全局表
happy   = "happy"
excited = "surprised"

[persona.profiles.hiyori.performance_map]
celebrate = "playful, Idle#4"
sing      = "playful, Extra#2"
```

### 规则

- 命中条件：档案的 `model` 与 `persona.model_path` 完全一致（或档案名本身就是该路径）
- 命中后：档案里**出现过的表整表替换**全局表（不是逐键合并 —— 避免旧模型的键残留）；没写的表仍用全局
- 一个档案都没命中：全部走全局表，不报错

### 实现

| 文件 / 符号 | 说明 |
|---|---|
| `engine/yuiro/config.py` → `PersonaConfig.profiles` | 档案字段 |
| `engine/yuiro/config.py` → `active_profile()` | 按 model_path 命中档案 |
| `engine/yuiro/config.py` → `effective_persona_maps()` | 合成生效的三张表 |
| `engine/yuiro/main.py` 启动装配段 | `effective_persona_maps(...)` → `AvatarRuntime(...)` |
| `engine/yuiro/debug_api.py` → `_rebuild_responder()` | 热重载时重新取生效值（换模型 / 改配置即时生效） |

> TOML 序列化支持任意深度嵌套（`config.dump_toml`），档案名含点/斜杠会自动加引号。

---

## 5. 渲染层执行细节（`shell/src/renderer/src/components/Live2DCanvas.vue`）

### 唯一入口 `applyAvatarIntent()`

1. **表情**：`expression` 缺省 = 不动；显式空串 = 回落默认。
   `applyExpression()` 会先对照 `listExpressions()` 校验，名字不存在只 `warn`，不会静默。
2. **动作**：`playMotion()` 校验组名与索引越界；用 `MotionPriority.FORCE`（值 3）确保能打断待机/其它动作。
   返回运行时读到的真实时长（`motionDurationMs()`）。
3. **回落**：`scheduleRelease()` 在时长到点后自动 `resetExpression()`。
   规则是"**带 duration 才算一次表演、不带就是常驻状态**"——与引擎语义一致（`perform` 带 duration，`emotion:set` 不带）。

### 口型

`ParamMouthOpenY` **每帧在 `model.update()` 之前**写入（在 `ensureApp()` 注册的 ticker 回调里）。
不要在 `watch(props.mouthOpen)` 里写：动作曲线每帧都会重设参数，只写一次会被覆盖（表现为"嘴张不开"）。

### 资源枚举

`listMotions()` / `listExpressions()` 从运行时 `motionManager.definitions` /
`expressionManager.definitions` 读取，任何模型都适用（组名为空串的情况已过滤）。

### 状态暴露

`getAvatarState()` 返回 `{ expression, motion, motionIndex, until }`，供调试台显示"现在在演什么"。

---

## 6. 待机调度（S53 重构）

位置：`Live2DCanvas.vue` → `startIdle()` / `stopIdle()` / `releaseToIdle()`。

**旧行为（已废弃）**：`startRandomMotion('Idle')` 播完立即续播 → 整组随机、永不停歇；
Hiyori 会把 8.6s 的全身动作当待机反复播，观感像"乱动"；没有 `Idle` 组的模型则完全不播。

**现行为**：

- 候选池 = 模型清单里的 **idle 语义槽位**，并按「动作时长上限」过滤（默认 4.5s）
- 播一个 → 停顿 `随机(6s ~ 12s)` → 再播下一个
- 表情固定在 `neutral` 槽位（模型没有就回落默认），**不再随机跳动**
- 表演进行中（`avatarState.until > now`）主动让位，播完 `releaseToIdle()` 回到 neutral 并重启调度
- 模型没有 idle 资源 → 完全静止（只呼吸/眨眼）；有资源但都超过时长上限 → 退化为只播最短的那个

参数在调试台「外观」页的 **「待机行为」** 卡片里调，存 localStorage、两个窗口实时同步：
`enabled / intervalMinMs / intervalMaxMs / maxDurationMs`（`composables/useAvatarIdlePref.ts`）。

```ts
// 关键：只从 idle 槽位取，且播完停顿
const pool = idleCandidates(manifest.value, idlePref.maxDurationMs.value)
const pick = pool[Math.floor(Math.random() * pool.length)]
const played = playMotion(pick.group, pick.index, 2 /* NORMAL，不打断表演 */)
idleTimer = setTimeout(tick, (played || pick.durationMs) + randomIdleDelay(min, max))
```

---

## 7. 调试台「外观」页操作手册

页面顺序：**桌宠形象 → 表现档案 → 模型体检 / 导入**。

| 卡片 | 能做什么 | 是否需要引擎 |
|---|---|---|
| 桌宠形象 | 切模型（写入 `persona.model_path` + 通知桌宠换装）；试播任意动作（组#索引）；预览任意表情；显示引擎在线状态与最近一次试播 | 换装不需要；写配置需要 |
| 表现档案 | 为当前模型**新建/删除档案**；编辑「情绪 → 表情」；编辑「表演 → 表情 + 动作」；行首 `✗` 是资源体检；`▶` 直连试演 | 读表演库需要引擎；试演不需要 |
| 模型体检 / 导入 | 校验引用完整性 / 大小写 / 中文文件名 / moc3 版本；导入外部模型目录（自动 ASCII 化目录名） | 不需要 |

### 关键交互约定

- **换模型不被引擎阻断**：先 IPC 换装（必成），再尽力写配置；写失败只给软提示，不回滚已换好的模型
- **试演直连**：调试台自己解析表演并经 `dev:apply-intent` 下发，引擎离线也能演
- **资源体检**：表情名 / 动作组 / 索引逐项对照当前模型，缺什么直接标在行首

### 快捷键（桌宠窗口）

| 键 | 作用 |
|---|---|
| `Alt+E` | 循环预览表情 |
| `Alt+M` | 循环预览动作组 |
| `Alt+G` | 打开表演库面板 |

---

## 8. DIY 速查

### 8.1 调表情的浓淡 —— 改 `exp3.json`

位置：`public/live2d/<模型>/expressions/*.exp3.json`

```json
{
  "Type": "Live2D Expression",
  "FadeInTime": 0.4,
  "FadeOutTime": 0.4,
  "Parameters": [
    { "Id": "ParamEyeLSmile", "Value": 1,    "Blend": "Add" },
    { "Id": "ParamEyeLOpen",  "Value": 0.55, "Blend": "Multiply" }
  ]
}
```

`Blend` 三种：`Add` 叠加（眉 / 口 / 脸颊）、`Multiply` 乘算（**开眼程度**用它）、`Overwrite` 强制覆盖。
`FadeInTime/FadeOutTime` 控制表情切换的过渡，改"切换生硬"就调这里。

### 8.2 参数速查（Hiyori，符号取自 Live2D 官方《标准参数列表》）

| 参数 | 范围 | 正方向 |
|---|---|---|
| `ParamAngleX / Y / Z` | ±30 | X 右转头 / **Y 抬头** / Z 向右倾 |
| `ParamEyeLOpen / ROpen` | 0~1（可超） | 睁眼；建议 Multiply |
| `ParamEyeLSmile / RSmile` | 0~1 | 笑眼 |
| `ParamEyeBallX / Y` | ±1 | X 右看 / **Y 上看** |
| `ParamBrowLY / RY` | ±1 | **+ 扬眉 / − 压眉** |
| `ParamBrowLAngle / RAngle` | ±1 | **− 生气**（内端下垂） |
| `ParamMouthForm` | ±1 | **+ 笑 / − 怒** |
| `ParamMouthOpenY` | 0~1 | 张嘴（口型通道，勿在表情里钉死） |
| `ParamCheek` | 0~1 | 脸红 |
| `ParamBodyAngleX / Y / Z` | ±10 | 同头部方向 |

### 8.3 配比（情绪→表情 / 表演→表情+动作）

- 推荐：调试台「表现档案」卡，保存即热重载，行首 `✗` 直接告诉你资源缺失
- 手改：`engine/config.toml` 的 `[persona.profiles.<档案>.expression_map]` / `.performance_map`
- 语法与优先级见第 3 节

### 8.4 动作文件（`motion3.json`）

```jsonc
{
  "Version": 3,
  "Meta": { "Duration": 5.37, "Fps": 30.0, "Loop": true },
  "Curves": [
    { "Target": "Parameter", "Id": "ParamAngleX", "Segments": [0, 0, 1, 0.111, 0] }
  ]
}
```

- `Loop`：待机动作应为 `true`，一次性表演建议 `false`
- `Target`：`Parameter`（参数）/ `PartOpacity`（部件透明度）/ `Model`（整体不透明度）
- `Segments` 段类型：`0` 线性、`1` 贝塞尔、`2` 阶梯、`3` 反贝塞尔
- 淡入淡出不在动作里，而在 `model3.json` 的动作声明（`FadeInTime/FadeOutTime`）

---

## 9. Live2D 文件清单

以 `public/live2d/hiyori/` 为例：

| 文件 | 必需 | 作用 |
|---|---|---|
| `*.model3.json` | ✅ | 入口清单：资源引用 / 动作组 / 表情表 / Groups / HitAreas |
| `*.moc3` | ✅ | 模型本体（二进制，第 5 字节是版本号） |
| 贴图（`*.2048/*.png`） | ✅ | 图集 |
| `*.physics3.json` | 建议 | 头发 / 饰品摆动 |
| `*.pose3.json` | 建议 | 部件互斥（如左右手臂） |
| `*.cdi3.json` | 建议 | 参数显示名（纯调试，不影响运行） |
| `*.userdata3.json` | 可选 | ArtMesh 标签 |
| `motions/*.motion3.json` | 可选 | 动作 |
| `expressions/*.exp3.json` | 可选 | 表情 |
| `.cmo3` / `.can3` | — | **编辑器源工程，不随模型分发** |

`model3.json` 的顶层 `Groups` 很关键：运行时靠 `LipSync → ParamMouthOpenY`、
`EyeBlink → ParamEyeLOpen/ROpen` 做口型与眨眼。自制模型若改了参数名却没在这里登记，口型/眨眼会静默失效。

---

## 10. Cubism Editor 5.3 / Viewer 要点

### ⚠ moc3 版本兼容（最容易踩的坑）

- Editor **5.3** 导出的 moc3 版本字节 = **6**
- Cubism **5 SDK（R4 及更早，含 5.1 / 5.2）只能读 ≤ 5**
- 本项目运行时为 **Core 5.1.0**，加载 ver 6 会直接失败：
  `csmReviveMocInPlace is failed. The Core unsupport later than moc3 ver:[5]. This moc3 ver is [6].`

对策（三选一）：

1. 用 5.1 / 5.2 版编辑器导出（最省事）
2. 升级本项目运行时到 5.3 Core（注意 5.3 SDK 的 Renderer 类有重命名变更）
3. 若导出界面提供 moc3 目标版本选项，选旧版（以实际界面为准）

无论哪种，导出后先跑调试台「模型体检」——它会直接读版本字节并标红。

### Editor DIY 要点

- 参数尽量用**标准 ID**（项目的口型 / 眨眼 / 表情套件全部按标准 ID 工作）
- 待机动作放 `Idle` 组（Loop=true），交互 / 表演放 `TapBody`（Loop=false）
- 导出的动作记得补 `FadeInTime/FadeOutTime`（约 0.5s）
- 贴图 2048 起步，单张不要超 4096

### Viewer (for OW) 用法

1. 拖入 `.model3.json` 即可预览；**加载失败 = 资源问题**（与运行时同源，适合做导入前预检）
2. 参数面板逐个拖，确认语义（写 exp3 前的功课）
3. 表达式叠加预览：提前发现 Blend 叠加过头、表情互相打架
4. 动作播放：验证 Loop、核对真实时长（对齐引擎时长表）

### 推荐流水线

```
Editor 导出 → 放入 public/live2d/<名字>/
  → 调试台「模型体检」（引用 / 大小写 / 中文名 / moc3 版本）
  → 「桌宠形象」选用 + 试动作 / 试表情
  → 「表现档案」新建档案 → 配情绪 / 表演 → 保存（热重载）
  → 行首无 ✗ 且试演正常 → 完成
```

---

## 11. 故障排查表

| 症状 | 最可能的原因 | 处置 |
|---|---|---|
| 点了表演没反应 | 动作组 / 索引在当前模型不存在；表情名不存在 | 看「表现档案」行首 `✗` 的悬停说明；或看桌宠 DevTools 的 `[live2d]` warn |
| 换模型后表情全不对 | 该模型没有档案，沿用了全局表（全局表对齐默认模型 Hiyori） | 为它新建档案，填 expression_map |
| 表情一直挂着不消失 | 意图没带 `duration_ms`（被当作常驻情绪） | 表演请用 `perform`（带时长）；或确认前端 `scheduleRelease` 生效 |
| 表演动作被待机顶掉 | 旧版本用默认优先级 | 现版本统一 FORCE；若仍出现，检查是否有自定义 `startRandomMotion` 调用 |
| 嘴不动 | 口型写在了 `watch` 里被动作曲线覆盖；或模型没在 Groups 登记 LipSync | 确认每帧写入；检查 `model3.json` 的 `Groups` |
| 只有某个模型"加载不出来" | 窗口贴合尺寸超出屏幕 / moc3 版本不符 / 资源缺失 | 「模型体检」+ 主进程日志（`[ui-settings]` / `[window]` 的夹紧打印） |
| 中文 / 空格文件名模型不显示 | URL 未编码 → 404 | 改纯 ASCII 目录名，或用「模型体检 / 导入」（导入会自动 ASCII 化）；路径含空格时渲染层会转义，一般无需处理 |
| 待机不动 / 只有呼吸 | 模型没有 idle 语义动作；「待机行为」被关闭；或时长上限把候选全过滤了 | 看「模型体检」的槽位表 idle 有几项；在「待机行为」卡调大时长上限或开启 |
| 换模型后动作全没了 | 该模型文件名无语义，档案里没有 `motion_slots` | 「表现档案」→「按模型自动生成」，或手配 `motion_slots` |
| 动作播到风马牛不相及的内容 | 旧配置里写死了别的模型的 `组#索引` | 删掉档案里的具体坐标，改用语义槽位 / 重新自动生成 |

---

## 12. 语义槽位与接入新模型（S53）

### 12.1 为什么需要槽位

旧实现把**模型私有坐标**写进引擎：`celebrate → TapBody#5`、活动联动 → 动作索引 `5/7/9`。
这些只对肥牛（TapBody 13 个动作）成立：

- Hiyori 的 `TapBody` 只有 1 个 → 索引越界，动作静默不播；
- Hotaru 只有单一 `Motion` 组（67 个动作）→ 索引 5/7/9 会播到完全无关的动作。

槽位把"要什么语义"和"用哪个资源"解耦：

```
引擎（语义）            模型清单（主进程）                 渲染层
celebrate  ──────►  motion_slot "celebrate"  ──────►  mtn_kime01_C (Hotaru)
                                                    Idle#4         (Hiyori，档案指定)
```

### 12.2 两套槽位

| 表情槽位（8） | neutral / happy / sad / angry / surprised / shy / thinking / playful |
|---|---|
| **动作槽位（10）** | idle / greet / celebrate / comfort / surprise / thinking / sing / angry / nod / look |

情绪 → 表情槽位固定映射：happy→happy、sad→sad、angry→angry、excited→surprised、
bored→neutral、thinking→thinking。

### 12.3 自动推断规则（`shared/live2dInfer.ts`）

1. **动作文件名**：`mtn_<word><NN>_<C|L|R>` / `misc_<word>` / 裸名字 → 词表映射；
   `_C`（正面）优先，`_L/_R` 是侧面变体。
2. **组名启发**：整个组叫 `Idle` → 组内动作视为 idle（Hiyori 靠这条）。
3. **表情名**：`exp_<word><NN>` / 裸语义名 → 词表映射。
4. **认不出的名字 → 留空，不猜**（肥牛 `expression2..7`、Hiyori `Hiyori_m01` 必须靠档案）。

解析优先级（引擎侧 `PerformanceResolver.resolve`）：
`performance_map` 具体值 > `motion_map` > `motion_slots[槽位]` > 空（由壳层按模型清单解析）。

### 12.4 idle 规则

见第 6 节：只播 idle 槽位 + 时长上限 + 6~12s 停顿，表情固定 neutral。

### 12.5 接入一个新模型的检查清单

1. 把模型目录放进 `public/live2d/<名字>/`（**建议目录名纯 ASCII**；含空格可用，渲染层会转义）
2. 调试台「外观」→「模型体检」
   - 引用完整性 / 大小写 / moc3 版本（**≥6 是 Cubism 5.3 导出，当前 Core 5.1 读不了**）
   - 槽位覆盖表：8 表情槽 / 10 动作槽各有几个候选
3. 若「未识别」较多（文件名无语义）→ 「表现档案」点 **「按模型自动生成」**，
   会把 `expression_map` + `motion_slots` 写进该模型的档案；之后可逐项手改
4. 试演几个表演，确认表情/动作都正确；行首 `✗` 会指出资源缺失
5. 若目录里有多个外观变体，在 `model_dict.json` 给非主模型加 `"hidden": true`
   （扫描结果也会被一并屏蔽）

### 12.6 Hotaru Shiomi 的接入结果（实例）

| 项 | 值 |
|---|---|
| 主模型 | `Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json` |
| moc3 | **版本 5**（与 Core 5.1 兼容） |
| 表情 | 46 个，命名 `exp_<语义><NN>` → **8 个槽位全部有候选** |
| 动作 | 单一 `Motion` 组 67 个，`mtn_<语义><NN>_<C/L/R>` → **10 个槽位全部有候选** |
| idle | `mtn_idle01/02/03`（三方向各一） |
| 隐藏变体 | `016_live_01`、`016_child_casual_spring_01_still`、`016_live-mode_live_01(_low)` |
| 授权 | **外部资源，使用/分发前请自行确认授权** |

> 该模型的 18/67 个动作未能推断语义（如 `nervous` / `denial`），这不影响已有槽位；
> 需要时可在档案里手配（`performance_map` 或 `motion_slots`）。

### 12.7 工具活动联动的槽位

`activity.py` 只给槽位，主进程先按档案解析成具体动作，解析不出再由清单推断：

| 工具 | 槽位 | 语义 |
|---|---|---|
| `file_list` / `file_read` / `file_write` / `file_move` / `file_delete` | `look` | "它在看着/处理" |
| `app_open` / `netease_play` | `greet` | 对外操作前的招呼 |

（原实现对写文件类映射到 TapBody#5"手部动作"、对外操作映射到 #7；改用语义槽位后
不再保证每个模型都有对应动作 —— 没有就**不播动作**，好过播一个语义不搭的。）

## 13. 相关测试

| 测试 | 覆盖 |
|---|---|
| `engine/tests/test_performance.py` | 表演解析、时长、优先级 |
| `engine/tests/test_motion_mapping.py` | 时长表（TapBody / Idle / Extra）与动作索引 |
| `engine/tests/test_config_profiles.py` | 档案命中、生效表合成、TOML 深层往返 |
| `engine/tests/test_debug_api_panels.py` | `/api/config` 契约（含提示词内置文案回传） |
| `docs/UI&motions/Live2D表演测试用例.md` | **手工回归用例**（13 个表演 × 2 个模型的实测期望值、idle/活动/负例） |
