# S05 — AvatarIntent 通道（表情随回答变化）

> 状态：**已批准开工**（2026-09-12，Human 指令"继续"＝按推荐做 AvatarIntent）。
> 性质：Wave 2 第一步（Era 1 Perform 的核心："表情随回答变化"）。
> 规范依据：`docs/spec/architecture-goal.md` §3.9、`docs/spec/target-file-preview.md` §3.7。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 05
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    AvatarIntent 通道 —— 表情随回答变化
SURPRISE: Yuiro 的表情跟着它说的话变（开心/低落/兴奋/无聊/生气/思考）
USER EXPERIENCE:
  - 主情绪变化 → 表情随之切换（不再是"只打日志、脸不动"）
  - LLM 等待期显示"思考"表情（顺便掩盖 TTFT 延迟）
  - Alt+E 可逐个预览模型表情（确认语义后自行调整映射）
ARCHITECTURE:
  - 新增 avatar/ 包：AvatarIntent（语义层）+ AvatarPriority + AvatarRuntime（意图工厂 + 仲裁 + 广播）
  - 通道：情绪变化 → avatar:intent（EMOTION 优先级）；LLM 等待 → thinking → 回落主情绪
  - 分层原则：引擎只发**语义 + 表情名**（来自 [persona.expression_map] 配置）；
    前端 adapter 负责翻译为 Live2D 调用并在缺资源时容错
  不做：motion 动作通道（语义未视觉确认，预留字段）；duration 过期回落（持续型表情不需要）
FILES:
  engine/yuiro/avatar/{__init__.py, intent.py, runtime.py}（新增）
  engine/yuiro/config.py（expression_map 默认值修正为真实可用表情名）
  engine/yuiro/main.py（装配 + 两处情绪推送 + _emit_event 桥接）
  shell/src/renderer/src/components/Live2DCanvas.vue（applyAvatarIntent / 预览）
  shell/src/renderer/src/App.vue（avatar:intent 处理 + Alt+E）
  engine/tests/test_avatar_intent.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动、兼容优先（emotion:set 保留）、加测试。
  禁止重写 EmotionEngine；禁止让前端成为优先级权威。
TEST:
  Unit：intent payload 裁剪 / 映射命中与未命中回落 / 优先级不覆盖 / 无 broadcast 不崩
  + 回归（对照基线：5 failed 集不变）+ 前端 typecheck
DEFINITION OF DONE:
  - 情绪变化 → avatar:intent 广播（expression 名来自配置映射）
  - 未映射情绪 → expression=""（前端 reset 语义），不崩
  - LLM 等待期 thinking → 出结果回落主情绪
  - 前端表情真实切换；缺资源时容错（不影响渲染）
  - Alt+E 预览可用；回归通过
HUMAN ACCEPTANCE:
  连续对话：确认表情跟着情绪变；用 Alt+E 找到"笑/哭/生气"的真实编号并回填 config.toml
CUSTOM ASSET:
  模型表情语义确认（expression2~7 → biaoqing1~6 的真实含义）——由 Human 用 Alt+E 视觉确认
NEXT UNLOCK: Wave 2 的动作通道（motion）与"会表演"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 资产事实（调研结论，写死在 Plan 中备查）

| 资源 | 实际状态 |
|---|---|
| `expression1` | **空表达式**（Parameters: []），不可用于恢复默认 |
| `expression2~7` | 分别驱动自定义参数 `biaoqing1~6`（语义未知，需视觉确认） |
| Motions | `Idle` 1 个（Hiyori_m01）+ `TapBody` 13 个（Hiyori_m01~m10 / micon / micoff / singing） |
| `expression_map` 旧默认 | `joy/sadness/excitement/boredom/anger` —— **模型里不存在**（映射从未生效的根因） |
| 恢复默认 | `expressionManager.resetExpression()`（前端 adapter 负责） |

## 交付报告（2026-09-12 完成）

### Changed files

**新增**：`engine/yuiro/avatar/{__init__.py, intent.py, runtime.py}`、`engine/tests/test_avatar_intent.py`（8 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/main.py` | 装配 `AvatarRuntime`（映射来自 `persona.expression_map`）；两处情绪推送点（互动奖励 / 定时衰减）追加 `push_emotion`；`_emit_event` 桥接（`llm:start`→thinking，`llm:text`→回落主情绪） |
| `engine/yuiro/config.py` | `expression_map` 默认值修正（joy/… → `expression2~7`，**模型真实可用**） |
| `engine/config.toml` + `engine/config.example.toml` | 同步修正实配与模板（旧值在模型里不存在） |
| `engine/yuiro/emotion/__init__.py` | `_DEFAULT_EXPRESSION_MAP` 同步修正（+thinking） |
| `engine/yuiro/debug_api.py` | 人设热重载同步更新 AvatarRuntime 映射（`update_expression_map`） |
| `shell/.../Live2DCanvas.vue` | `applyAvatarIntent`（expression / `resetExpression` + 容错）+ `cycleExpressionPreview` + defineExpose |
| `shell/.../App.vue` | `avatar:intent` 处理（→ canvas + 日志）；Alt+E 预览；监听器卸载清理 |

### 关键根因修复（冒烟抓出）

- 旧 `expression_map`（`joy` / `sadness` / …）**在肥牛模型里根本不存在** —— 这意味着即使前端接线成功，表情也会静默失败；
- 已修正为模型真实可用的 `expression2~7`（6 项，含 `thinking`），并同步 **4 处**：代码默认 / 实配 `config.toml` / 模板 / 热重载。

### 冒烟证据

```
[yuiro][avatar] 头像运行时已装配（表情通道；映射 6 项）
MAP happy -> expression2
MAP thinking -> expression7
PUSH thinking: True {'type': 'avatar:intent', ..., 'expression': 'expression7'}
PUSH happy:    True {'type': 'avatar:intent', ..., 'expression': 'expression2'}
```

### Tests

- 新增 **8 个**全部通过；全量回归 **97 passed**（失败集与基线一致）；
- ruff 全绿；前端 `pnpm typecheck` 通过。

### DoD 对照

- [x] 情绪变化 → `avatar:intent` 广播（expression 来自配置映射）
- [x] 未映射情绪 → `expression=""`（前端 reset 语义），不崩
- [x] LLM 等待期 thinking → 出结果回落主情绪（`_emit_event` 桥接）
- [x] 前端表情真实切换；缺资源容错（不影响渲染）；广播失败静默
- [x] Alt+E 预览可用；回归通过

### Human Acceptance（待人工）

1. 重启引擎 + 壳层 → 连续对话：确认**表情跟着情绪变**（日志 `[avatar] 表情: happy → expression2`）；
2. **用 Alt+E 逐个预览 7 个表情**，记下 `biaoqing1~6` 的真实含义；
3. 按实际含义调整 `engine/config.toml` → `[persona.expression_map]`（调试台改人设也会热重载）。

### 风险 / 遗留

- 表情语义未视觉确认（默认按序映射，用户可用 Alt+E 校正）；
- `expression1` 为空表达式（预览无变化，属预期）；
- motion 动作通道预留未触发（13 个动作语义待确认，Wave 2 后续）。
