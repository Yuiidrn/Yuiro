# S14 — Wave 2 动作通道（motion）

> 状态：**已完成**（2026-09-13，Human 指令"全部进行"）。
> 性质：Wave 2 收尾——表情（S05）+ 动作通道就绪。
> 规范依据：`docs/spec/architecture-goal.md` §3.9（AvatarRuntime Intent/Expression/Motion/Priority）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 14
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    AvatarIntent 动作通道（motion）
SURPRISE: 通道就绪：引擎可发动作意图，前端可播；Alt+M 预览 13 个动作供语义确认
ARCHITECTURE:
  - AvatarIntent 增加 motion_index（组内索引；None = 该组随机）
  - AvatarRuntime.push_action(session_id, motion, motion_index) —— 优先级 ACTION
  - 前端 Live2DCanvas.playMotion(group, index) + applyAvatarIntent 支持 motion
  - Alt+M 逐个预览 TapBody 13 个动作（用户确认语义后配置映射）
  不做：默认动作映射（语义未确认，映射表留空，等用户 Alt+M 确认后填）
FILES:
  engine/yuiro/avatar/intent.py（motion_index）
  engine/yuiro/avatar/runtime.py（push_action）
  engine/tests/test_avatar_action.py（新增 3 用例）
  shell/.../Live2DCanvas.vue（playMotion / cycleMotionPreview / applyAvatarIntent 支持 motion）
  shell/.../App.vue（Alt+M 预览）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 交付报告（2026-09-13 完成）

### Changed files

| 层 | 文件 | 改动 |
|---|---|---|
| 引擎 | `avatar/intent.py` | `motion_index` 字段 + payload 序列化 |
| 引擎 | `avatar/runtime.py` | `push_action(session_id, motion, motion_index)`（ACTION 优先级） |
| 引擎 | `tests/test_avatar_action.py` | 新增 3 用例（payload / 广播 / 优先级不覆盖 USER） |
| 前端 | `Live2DCanvas.vue` | `playMotion(group, index)` + `cycleMotionPreview()` + `applyAvatarIntent` 支持 motion |
| 前端 | `App.vue` | Alt+M 预览循环 |

### Tests

- 引擎新增 **3 个**通过（连同 S05 的 8 个 = 11 passed）；`avatar/` ruff 零告警；前端 typecheck 通过；
- 全量回归 **194 passed**（S13 基线 191 + 3），失败集与基线一致。

### DoD 对照

- [x] 引擎可发动作意图（`push_action`，含组内索引）
- [x] 前端可播放动作（`playMotion`）并在 `avatar:intent` 中消费 motion 字段
- [x] Alt+M 可预览 TapBody 全部 13 个动作（语义确认工具就位）
- [x] 优先级正确（ACTION 不覆盖 USER）
- [x] 回归通过

### Human Acceptance（待人工）

1. **Alt+M** 逐个预览 13 个动作 → 记下每个的语义（招手/点头/唱歌/麦克风开关等）；
2. 确认语义后回填映射（`[persona].motion_map`，预留），让情绪/状态联动动作。

### 风险 / 遗留

- 动作默认映射为空（语义未视觉确认，不擅自绑定）；
- `micon/micoff/singing` 三个语义较明确的动作也未自动绑定（待用户确认后接线）；
- 未做点击交互触发（TapBody 组本意是"点击身体"触发，需要前端命中检测改造）。
