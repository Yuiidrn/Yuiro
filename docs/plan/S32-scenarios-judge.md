# S32 — 场景集扩充 + LLM-judge（主观维度）

> 状态：**已完成**（2026-09-13）。
> 来源：S30 的两项遗留（场景只有 24 条、主观维度完全没测）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 32
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    让评测从"能跑"到"能信"
SURPRISE: 跑一次基线，能看到"她有多像她"（人格一致性 / 情绪贴合 / 自然度 / 简洁）
ARCHITECTURE:
  A. 场景集 24 → 60 条（10 类每类 ≥5；仍向 100–300 推进）
  B. judge.py：LLM-as-judge 四维度（1–5 分 + 理由），严格 JSON 契约
       judge 回调注入 runner；**只对通过规则判定的场景评分**（成本控制）
       CLI：--judge（用独立 system prompt "你是严格评审"，避免自评自夸）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 四个维度（贴合她的人设与"桌面宠物"场景）

| 维度 | 5 分是什么样 | 1 分是什么样 |
|---|---|---|
| `persona` 人格一致性 | 明显是"她"（表面乖巧、实则腹黑毒舌、思维跳脱） | 完全像通用客服 |
| `emotion` 情绪贴合 | 安慰时温柔、被夸时得意、被否定时有骨气 | 情绪错位（安慰时说"哈哈"） |
| `naturalness` 自然度 | 像真人随口说话 | 明显 FAQ / 客服腔 |
| `conciseness` 简洁 | 该短就短 | 长篇大论（桌面场景很烦） |

**关键**：prompt 里写了**每档的锚点** —— 没有锚点的打分不可信（这是 S30 定下的
"只测可判定的"原则在主观维度的延伸：不能判定的，就明确写清"什么算几分"）。

## 交付报告（2026-09-13 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/eval/scenarios/personality_baseline.jsonl` | **24 → 60 条**（每类补到 6 条） |
| `engine/yuiro/eval/judge.py` | **新增**：`build_judge_prompt`（含锚点）/ `parse_judge_json`（严格）/ `judge_reply` / `make_llm_judge` / `aggregate`（均分 + 总体 + 最差项） |
| `engine/yuiro/eval/runner.py` | `judge` 回调参数（**只对 passed 的场景调用**）；报告新增 `judge` 段 |
| `engine/yuiro/eval/__main__.py` | `--judge`（用独立"严格评审" responder，不复用人设 prompt） |
| `engine/yuiro/eval/__init__.py` | 导出 judge 相关（并简化掉一版写复杂的 `__getattr__` 延迟导入） |
| `engine/tests/test_eval_judge.py` | **新增** 17 个用例 |

### 冒烟证据

```
$ python -m yuiro.eval --list
场景集：60 条
  [chat     ] chat-01        你好呀
$ python -m yuiro.eval --limit 2
  chat       2/2  (100%)

$ pytest tests/test_eval_judge.py tests/test_eval_baseline.py -q
34 passed
```

### 三条工程约束（写进了 judge.py 模块说明）

1. **严格解析**：非法 / 越界 / 缺维度的评分一律跳过 —— 不猜、**不用 0 分污染平均**
   （`test_aggregate_ignores_failed_scores` 锁死）；
2. **评审失败不影响跑批**：judge 抛异常只记日志，规则结果照常输出；
3. **成本控制**：只对通过规则判定的场景评审（明显不合格的没必要花 token）；
   且一次请求评完四维（而非四维四次请求）。

### Tests

- 新增 **17 个**全部通过；全量回归 **375 passed / 5 failed / 1 error**（失败集与基线一致）；
- `eval/` 与测试文件 ruff 零告警。

### DoD 对照

- [x] 场景集 ≥60 条，10 类每类 ≥5（`test_scenario_set_expanded` 护栏）
- [x] 四维度评分 + 评分锚点 + 严格 JSON 契约
- [x] 聚合：每维度均分 / 总体 / **最差项**（直接指出问题场景）
- [x] runner 集成（judge 回调，只评通过者）；CLI `--judge`
- [x] 评审用独立 system prompt（避免"自评自夸"）
- [x] 回归通过

### Human Acceptance（待人工）

1. `python -m yuiro.eval --live --judge --limit 5` → 看主观评分是否符合你的直觉
   （**维度定义与锚点是否合你的标准，是这次最需要你看的部分**）；
2. 若某维度分数普遍偏低（如 `conciseness`），说明它的回复确实啰嗦 → 改 persona_prompt 后再跑对比；
3. `python -m yuiro.eval --list` 检查新增的 36 条场景是否符合你的预期。

### 风险 / 遗留

- **场景集 60 条**（spec 目标 100–300）：继续扩充需要你的参与（新增场景 = 定义"你希望它怎么表现"）；
- **judge 未接调试台面板**（S31 的基线面板目前只展示规则结果）—— 面板加 judge 需要处理
  "一次跑批 = N 次额外 LLM 请求"的等待与成本，属后续；
- **judge 未做校准**：LLM 评审本身有偏见（偏向长回复、偏向自己的风格），
  理想做法是拿人工标注的样本校准它 —— 属 PB1（数据工厂）的范畴；
- judge 用的是同一个模型（自评同源）→ 跨模型对比时应换用第三方模型评审。