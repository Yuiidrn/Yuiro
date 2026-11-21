# S30 — Personality Baseline（PB0：人格基线）

> 状态：**已完成**（2026-09-13）。
> 来源：`docs/spec/阶段性总评和后续方向.md`（PB0 与 Training Data Pipeline）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    人格基线（PB0）—— 先有尺子，再谈"人格变好了"
SURPRISE: 一条命令跑 24 个固定场景，得到可对比的人格通过率
ARCHITECTURE:
  scenarios/personality_baseline.jsonl（10 类 24 条；进版本控制）
        │
        ▼
  baseline.py：Scenario / judge_reply（规则判定，纯函数）/ summarize（可对比报告）
        │
        ▼
  runner.py：run_baseline(responder, …)  ← responder 由调用方注入
        │                                   （真 LLM / AgentLoop / 假实现）
        ├── CLI：python -m yuiro.eval [--live] [--list]
        └── API：GET /debug/eval/personality/scenarios
                 POST /debug/eval/personality?live=&limit=&include_tools=
  规范原文："PB0 永远先做 Baseline……否则没有实验基线。"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 三条设计原则

1. **可离线测试**：判定逻辑（关键词 / 长度 / 工具调用）是纯函数，不依赖 LLM
   —— 评测器本身有单测，才不会"用坏了的尺子量身高"。
2. **可对比**：报告带 `model` + `prompt_hash` —— 换模型或改 Prompt 后，两份报告可直接比。
3. **只测可判定的**：主观维度（语气够不够毒舌）不在规则里假装修得出来，留给后续 LLM-judge。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：
- `engine/yuiro/eval/{__init__.py, baseline.py, runner.py, __main__.py}`
- `engine/yuiro/eval/scenarios/personality_baseline.jsonl`（10 类 24 条）
- `engine/tests/test_eval_baseline.py`（17 个用例）

**修改**：`engine/yuiro/debug_api.py`（场景列表 / 跑批 API + responder 装配）

### 冒烟证据（CLI 真实执行）

```
$ python -m yuiro.eval --list
场景集：24 条
  [chat     ] chat-01        你好呀
  [comfort  ] comfort-01     我今天面试挂了，好难受
  [sass     ] sass-01        我今天又熬夜到三点了
  ...

$ python -m yuiro.eval --limit 3
[yuiro][eval] [人格基线] 3/3 通过（100%，model=echo，prompt=?）
=== 人格基线（PB0） ===
model=echo  prompt=?
通过 3/3（100%）
  chat       3/3  (100%)
```

### 一个真 bug（测试逼出）

初版把 responder 的**异常**包装成回复串 `"<error: boom>"` 交给判定 —— 结果它长度够长，
**被判为通过**。评测器把"跑失败"算成"答得好"，是最不能接受的错误。
现已强制：responder 异常一律计失败并附原因（`test_run_baseline_responder_error_is_isolated` 锁死）。

### 安全设计

- **默认跳过 `tool` 类场景**（`skip_categories=("tool",)`）：工具场景会**真实执行系统操作**
  （开应用、播音乐），评测不该有副作用；需要时用 `--include-tools` / `include_tools=true` 显式开启。
- CLI 的 `--live` 用**单轮 responder**（不启 AgentLoop），进一步避免工具副作用。

### Tests

- 新增 **17 个**全部通过（含场景集数据质量自检：id 唯一 / 类别合法 / expect 非空）；
- 全量回归 **348 passed / 5 failed / 1 error**（失败集与基线一致）；
- `eval/` 与测试文件 ruff 零告警。

### DoD 对照

- [x] 固定场景集（10 类；JSONL 进版本控制；数据质量有测试护栏）
- [x] 规则判定：长度 / 禁忌表达 / 应调工具 / 不该调工具 / 空回复
- [x] 报告可对比（`model` + `prompt_hash` + 分类通过率 + 失败清单）
- [x] 运行方式：CLI（离线自检 / `--live`）+ 调试 API（`live=false` 可离线验证链路）
- [x] 评测逻辑可离线单测（responder 注入）
- [x] 默认无副作用（跳过工具类场景）

### Human Acceptance（待人工）

1. `python -m yuiro.eval --list` → 看 24 条场景是否符合你对"该测什么"的预期
   （**这条最重要**：场景集代表你对人格的定义）；
2. `python -m yuiro.eval --live --limit 5` → 真跑 5 条，看报告里的失败原因是否中肯；
3. `GET /debug/eval/personality/scenarios` / `POST /debug/eval/personality?live=false&limit=5`；
4. 改一次 `persona_prompt` 后再跑 → 对比两份报告的 `prompt_hash` 与通过率变化。

### 风险 / 遗留

- **场景集只有 24 条**（spec 目标 100–300）：这是**起步集**，扩充需要你的参与
  （新增场景 = 定义"你希望它怎么表现"）；扩充记入 S33；
- **无 LLM-judge**：主观维度（够不够毒舌 / 像不像她）目前完全没测 → S33 引入 judge prompt；
- **无历史报告归档与对比 UI**：报告是即时的，未落盘做趋势（可配合 S31 管理 UI）；
- 规则判定天然**保守**：只能抓"明显不对"，抓不住"味道变了"——这是有意的取舍（先有客观下限）。