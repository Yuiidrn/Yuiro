# Live2D 表演效果测试用例

> 整理日期：2026-10-26
> 适用版本：语义槽位改造后（S53）
> 期望值不是手写的，而是**用当前配置跑一遍解析链**（引擎 `PerformanceResolver` → 模型清单 `avatarSlots`）得到的实测结果。

## 0. 前置条件与当前状态

| 项 | 当前值 |
|---|---|
| 默认模型（`[persona].model_path`） | `/live2d/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json` |
| 可用模型 | Hotaru Shiomi（46 表情 / 67 动作）、Hiyori（8 表情 / 13 动作） |
| `[persona.profiles]` | **空** —— 没有 per-model 档案 |
| 内置表演名（工具 enum） | 13 个：`idle / happy / sad / excited / thinking / bored / angry / celebrate / comfort / greet / surprise / sing / shy` |

因为档案为空：

- **Hotaru** 靠文件名自动推断，表情与动作都完整；
- **Hiyori** 只有表情（动作文件名 `Hiyori_m01` 无语义，推断不出来）→ 所有表演都"只演表情"。
  想让 Hiyori 也有动作，在 `engine/config.toml` 补一份档案（见附录 A）。

启动要求：引擎、桌宠窗口、调试台均已启动；`avatar_perform` 属 external 副作用，能力档位为 `read_only` 时会被拒。

### 观察方法（4 个地方）

1. **桌宠 DevTools → Console**：每次意图都会打一行
   `[live2d] intent celebrate → exp_kime01 Motion#22`
2. **引擎日志**：`[表演] celebrate → 表情 playful / 动作 celebrate（2970ms）`
   （没有具体值时这里显示的是**槽位名**，最终落点看第 1 条）
3. **调试台「表现档案」**：行首 `✗` = 当前模型跑不起来（悬停看原因）
4. **调试台「模型体检」**：槽位覆盖表（8 表情槽 / 10 动作槽各有几个候选）

---

## 1. 资产映射基线（实测）

### 1.1 表情槽位 → 具体表情

| 槽位 | Hotaru | Hiyori |
|---|---|---|
| neutral | `exp_idle01`（5 个候选） | **无** → 回落模型默认脸 |
| happy | `exp_bsmile01`（9） | `happy` |
| sad | `exp_anxiety01`（13） | `sad` |
| angry | `exp_angry01`（3） | `angry` |
| surprised | `exp_panic01`（4） | `surprised` |
| shy | `exp_heart01`（2） | `shy` |
| thinking | `exp_puzzled01`（5） | `think` |
| playful | `exp_kime01`（5） | `playful` |

### 1.2 动作槽位 → 具体动作（优先 `_C` 正面变体）

| 槽位 | Hotaru | Hiyori |
|---|---|---|
| idle | `Motion#19` mtn_idle01_C（6.0s） | 9 个候选，见 §4 |
| greet | `Motion#4` mtn_bye01_C（3.53s） | 未映射 |
| celebrate | `Motion#22` mtn_kime01_C（2.97s） | 未映射 |
| comfort | `Motion#10` mtn_cry01_C（4.47s） | 未映射 |
| surprise | `Motion#61` mtn_surprised01_C（2.03s） | 未映射 |
| thinking | `Motion#40` mtn_question01_C（2.33s） | 未映射 |
| sing | `Motion#49` mtn_sing01_C（4.10s） | `Extra#2` singing（4.70s） |
| angry | `Motion#1` mtn_angry01_C（2.90s） | 未映射 |
| nod | `Motion#31` mtn_nod01_C（2.57s） | 未映射 |
| look | `Motion#7` mtn_check01_C（2.43s） | 未映射 |

### 1.3 13 个表演的最终效果

| 表演 | Hotaru（表情 / 动作 / 保持） | Hiyori（表情 / 动作） |
|---|---|---|
| `idle` | exp_idle01 / — / 2.6s | —（无 neutral）/ — |
| `happy` | exp_bsmile01 / — / 2.6s | happy / — |
| `sad` | exp_anxiety01 / — / 2.6s | sad / — |
| `excited` | exp_panic01 / — / 2.6s | surprised / — |
| `thinking` | exp_puzzled01 / Motion#40 / 2.33s | think / — |
| `bored` | exp_idle01 / — / 2.6s | —（无 neutral）/ — |
| `angry` | exp_angry01 / — / 2.6s | angry / — |
| `celebrate` | exp_kime01 / Motion#22 / 2.97s | playful / — |
| `comfort` | exp_anxiety01 / Motion#10 / 4.47s | sad / — |
| `greet` | exp_bsmile01 / Motion#4 / 3.53s | happy / — |
| `surprise` | exp_panic01 / Motion#61 / 2.03s | surprised / — |
| `sing` | exp_kime01 / Motion#49 / 4.10s | playful / Extra#2（4.70s） |
| `shy` | exp_heart01 / — / 2.6s | shy / — |

---

## 2. A 类：自然语义触发（LLM 应**主动**调用）

工具描述只教了这 4 种，所以最稳定。以 **Hotaru** 为期望值（Hiyori 只演表情）。

| # | 输入（可直接粘贴） | 期望调用 | 期望表现 | ✔ |
|---|---|---|---|---|
| A1 | 我升职了！今天终于拿到 offer 了！ | `celebrate` | exp_kime01 + mtn_kime01_C（2.97s） | ☐ |
| A2 | 我把这事全搞定了，从列清单到归档一条不落 | `celebrate` | 同上 | ☐ |
| A3 | 唉……忙了一整天结果全白做了，好难受 | `comfort` | exp_anxiety01 + mtn_cry01_C（4.47s） | ☐ |
| A4 | 我回来了，刚下班 | `greet` | exp_bsmile01 + mtn_bye01_C（3.53s） | ☐ |
| A5 | 早呀，好久不见 | `greet` | 同上 | ☐ |
| A6 | 你猜怎么着？楼下那只猫居然会开门 | `surprise` | exp_panic01 + mtn_surprised01_C（2.03s） | ☐ |
| A7 | 什么？！服务器整个被清空了？ | `surprise` | 同上 | ☐ |

**判定**：DevTools 出现 `[live2d] intent celebrate → exp_kime01 Motion#22` 才算通过。
只出现文字回复、没有 intent → 是**工具调用策略**问题（不是渲染）。

---

## 3. B 类：显式指令触发（其余 8 个）

| # | 输入 | 期望调用 | 期望表现（Hotaru） | ✔ |
|---|---|---|---|---|
| B1 | 给我看看你开心的样子 | `happy` | exp_bsmile01（无动作） | ☐ |
| B2 | 做一个难过的表情 | `sad` | exp_anxiety01 | ☐ |
| B3 | 生气一下给我看 | `angry` | exp_angry01 | ☐ |
| B4 | 表现得兴奋一点 | `excited` | exp_panic01 | ☐ |
| B5 | 你现在是不是很无聊？演一个 | `bored` | exp_idle01 | ☐ |
| B6 | 装出正在思考的样子 | `thinking` | exp_puzzled01 + Motion#40 | ☐ |
| B7 | 唱首歌吧 | `sing` | exp_kime01 + mtn_sing01_C（4.10s） | ☐ |
| B8 | 害羞一个 | `shy` | exp_heart01 | ☐ |

> 这 8 个依赖模型"愿意照做"。若只回文字，先确认 B1 这类直白指令是否稳定，
> 再回头调 system prompt / 工具描述 —— 与 Live2D 无关。

---

## 4. C 类：自动通道（不经过 `avatar_perform`）

| # | 场景 | 触发条件 | 期望 | ✔ |
|---|---|---|---|---|
| C1 | 语音链路的思考态 | **语音**说话时收到 `llm:start` | `thinking`：exp_puzzled01 + Motion#40 | ☐ |
| C2 | 互动累积 | 每轮回复 happy +0.03 / bored −0.02，**主情绪变化**时才推 | happy 表情 | ☐ |
| C3 | 工具活动动作 | 读/写/移动文件 → `look`；打开应用/播放 → `greet`；**6 秒节流** | Hotaru：look → Motion#7 / greet → Motion#4；Hiyori：无动作 | ☐ |

C3 的输入（同时验证工具确实执行）：

- `列一下我桌面有什么文件` → `file_list` → look
- `读一下 README 前 20 行` → `file_read` → look
- `在桌面新建一个 test.txt 写个 hello` → `file_write` → look
- `打开记事本` → `app_open` → greet
- `放一首周杰伦的歌` → `netease_play` → greet

注意：**文字聊天不会触发 thinking**（`llm:start` 只由语音链路发出）；C2 的文本内容**不会**直接改变情绪表情
（情绪引擎不做文本情感识别，只有互动加成与衰减）。

---

## 5. idle（待机）测试

观察 30 秒以上，计数：

| 模型 | 候选池（时长 ≤ 4.5s） | 期望行为 | ✔ |
|---|---|---|---|
| Hotaru | 3 个 idle 动作均为 6.0s → 全部超上限 → 退化为只播最短的 `Motion#19` | 每 ~12–18s 播一次 mtn_idle01_C；表情保持 exp_idle01；**不随机变脸** | ☐ |
| Hiyori | Idle#7(1.6s)、#5(1.9s)、#6(2.1s)、#8(4.2s)、#2(4.2s) | 随机播这 5 个之一，播完停 6–12s；表情回落到模型默认脸（无 neutral 槽位） | ☐ |

调整入口：调试台「外观」→「待机行为」（开关 / 最短·最长停顿 / 动作时长上限）。

**负例**：把「播放待机动作」关掉 → 模型完全静止（只剩呼吸与眨眼）。
**负例**：把时长上限调到 1s → 池子为空 → 退化为只播最短的那个（Hiyori 的 m09，1.6s）。

---

## 6. D 类：边界与负例

| # | 操作 / 输入 | 期望 | ✔ |
|---|---|---|---|
| D1 | 今天天气不错 | **不调用**工具；表情不变（普通情绪波动不用调） | ☐ |
| D2 | 连说三件开心事 | 最多一次 `celebrate`（工具描述要求一次只选一个） | ☐ |
| D3 | 让 LLM 输出 `avatar_perform("dance")` | enum 里没有 → 调用被拦；即使绕过，解析为"未登记名字" → 无表情无动作，不崩溃 | ☐ |
| D4 | 切到 **Hiyori** 后点「表现档案」的 `▶` | 只演表情；`✗` 不出现（槽位无候选属于正常降级） | ☐ |
| D5 | 能力档位设为 `read_only` 后要求「打开记事本」 | `avatar_perform` 与 `app_open` 均被拒 | ☐ |
| D6 | 在档案里把 `celebrate` 的动作写成 `TapBody#5`（Hotaru 没有该组） | 行首 `✗`；`[live2d]` 提示动作组不存在；表情照常 | ☐ |
| D7 | 表情名改成不存在的 `expression7` | 行首 `✗`；回落到槽位候选（若没有则回落默认），不静默 | ☐ |
| D8 | 拔掉引擎后打开日记/调试台 | 不白屏；试演仍可用（直连桌宠） | ☐ |

---

## 7. 回归清单（每轮改动后勾一遍）

- [ ] Hotaru：A1/A3/A4/A6 四个动作都正确（可对照 §1.3 表格）
- [ ] Hotaru：`sing` 播 mtn_sing01_C，表情维持到动作结束（约 4.1s）
- [ ] Hiyori：表情全部正确（无动作不报错）
- [ ] idle 30 秒内：动作有间隔、表情没有无端跳动
- [ ] 工具活动：look 动作能触发，且 6 秒内不连播
- [ ] 切换模型后，表现自动跟着换（无需重启）
- [ ] 所有异常只出现在 `[live2d]` warn 里，界面不崩

---

## 附录 A：让 Hiyori 也有动作（可选项）

当前档案为空，所以 Hiyori 的动作槽位没映射。把下面这段加到 `engine/config.toml`，
保存后引擎会热重载：

```toml
[persona.profiles.hiyori]
model = "/live2d/hiyori/Hiyori.model3.json"
note  = "桃瀬ひより"

[persona.profiles.hiyori.motion_slots]
greet     = "Idle#6"    # m08 招手
celebrate = "Idle#4"    # m06 手部动作
comfort   = "Idle#2"    # m03 温和歪头
surprise  = "Idle#8"    # m10 抬头
thinking  = "Extra#0"   # 1.1s 微动
sing      = "Extra#2"   # singing
look      = "Idle#8"    # 工具活动：抬头看
```

也可以在调试台「表现档案」卡里手动配（保存即生效）。

## 附录 B：为什么没有"说难过就变难过"的用例

情绪引擎**不做文本情感识别**：它只有「每轮 happy +0.03 / bored −0.02 + 指数衰减」，
并且只在**主情绪发生变化**时才推送表情。所以表情只有两个来源：

1. LLM 主动调 `avatar_perform`（本文 A/B 类）；
2. 语音链路的 `thinking` 与主情绪回落（C 类）。

写用例时不要按"用户说什么 → 她什么表情"来设计，否则会把正常行为误判为 bug。
