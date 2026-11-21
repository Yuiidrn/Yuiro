# S09 — Artifact Store（大结果不再"截断即丢弃"）

> 状态：**已批准开工**（2026-09-12，Human 授权外出期间自主连续推进）。
> 性质：补 S06 缺口（spec §3.3 铁律「Tool Result 必须 Context-aware」的完整形态）
> + Wave 6 的 Artifact 一等实体的最小落地。
> 规范依据：`docs/spec/architecture-goal.md` §3.3（Tool Result → Artifact Store → Result Summary）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Artifact Store —— 工具大结果可回查
SURPRISE: 工具返回超长内容时，Yuiro 仍能看到细节（按需读取），而不是"看不全就瞎猜"
USER EXPERIENCE:
  - 行为无感（LLM 侧仍以摘要为主），但需要细节时能按需读取完整内容
  - 工具结果提示从"已截断"升级为"已存入 artifact（可读取）"
ARCHITECTURE:
  - 新增 artifact/ 包：Artifact 实体 + ArtifactStore（内存 + 磁盘 LRU，put/get/read_slice/list/prune）
  - ContextEngine.clip_tool_result 改为"存 artifact + 返回摘要 + 读取指引"
  - 新工具 artifact_read(artifact_id, start, length)：按需读取完整内容/片段（免审批）
  不做：多模态 artifact、artifact 版本/血缘、跨会话共享策略、Artifact 与 Task 绑定
FILES:
  engine/yuiro/artifact/{__init__.py, store.py}（新增）
  engine/yuiro/tools/artifact_tool.py（新增）
  engine/yuiro/context/engine.py（clip_tool_result 接入 store）
  engine/yuiro/agent/__init__.py（装配 ArtifactStore + 注册工具）
  engine/tests/test_artifact_store.py（新增）
CODING AGENT:
  遵循 coding-agent-Protocol：最小改动；无 artifact store 时退化为旧截断行为（兼容）；
  任何 IO 失败不得影响工具链路。
TEST:
  Unit：put/get/read_slice/分片边界 / prune（LRU 上限）/ 落盘与重启 / 
        clip_tool_result 带与不带 store 两种行为 / 工具 schema 与 run / 
        AgentLoop 装配后工具可读回 / 回归（S06/S07/S08 护栏不破）
DEFINITION OF DONE:
  - 超长工具结果存入 ArtifactStore，返回摘要 + artifact_id 指引
  - artifact_read 可按 id 与分片读回完整内容
  - 未注入 store 时行为与 S06 一致（纯截断）
  - 落盘可跨进程读取；LRU 上限生效
  - 回归通过
HUMAN ACCEPTANCE:
  让 Yuiro 读一个大文件 → 工具结果日志出现 artifact_id → 追问"文件里第 X 部分写了什么"，
  它能通过 artifact_read 答出细节
NEXT UNLOCK: Wave 6 权限/沙箱（Capability/Risk/Approval 分级）与 Hooks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 现状基线（S09 前）

- S06 已实现 `clip_tool_result`：超过 `tool_result_max_chars`（默认 2000）**截断并丢弃**；
- 完整内容仅存在于前端 `LLMChunk(tool_result)`（用户可见），**引擎侧 LLM 永远看不到后续细节**；
- 后果：`file_read` 大文件 → LLM 只能基于前 2000 字符回答（可能编造后半段）。

## 交付报告（2026-09-12 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/artifact/{__init__.py, store.py}` | **新增**：Artifact 实体 + ArtifactStore（put/get/read_slice/list/prune、磁盘落盘 + 重启恢复、LRU 上限） |
| `engine/yuiro/tools/artifact_tool.py` | **新增**：`artifact_read` 工具（分片回读，免审批，未注入时降级 pending） |
| `engine/yuiro/context/engine.py` | `ContextEngine(artifacts=...)`；`clip_tool_result` 升级为"存 artifact + 摘要 + 读取指引"（无 store 时退化为 S06 纯截断） |
| `engine/yuiro/agent/__init__.py` | `build_agent_loop(artifact_store=...)`；创建/注入 ArtifactStore + 注册 `artifact_read` |
| `engine/tests/test_artifact_store.py` | **新增** 10 个用例 |

### 冒烟证据

```
ARTIFACT TOOL: ['artifact_read']
[yuiro][artifact] [存入] art_40ce154b file_read（4000 字符）
[yuiro][context] 工具结果存入 artifact: file_read 4000 字符 → art_40ce154b
ARTIFACT ID: art_40ce154b
READBACK: ok 4000 字符 | 行内容 行内容 …
```

### Tests

- 新增 **10 个**全部通过；全量回归 **144 passed**（S08 基线 134 + 10），失败集与基线一致；
- `artifact/`、`tools/artifact_tool.py`、`context/`、测试文件 ruff 零告警。

### DoD 对照

- [x] 超长工具结果存入 ArtifactStore，返回前 N 字符 + `artifact_id` 读取指引
- [x] `artifact_read` 支持按 id 与分片（start/length）读回，并提示剩余字符与续读位置
- [x] 未注入 store 时行为与 S06 一致（纯截断，含"已截断"文案）
- [x] 落盘可跨进程读取（新实例恢复）；LRU 上限生效
- [x] 回归通过（S06 等价性 / S07 显式记忆 / S08 Task 护栏不破）

### Human Acceptance（待人工）

1. 让 Yuiro `file_read` 一个大文件 → 日志出现 `工具结果存入 artifact: file_read N → art_xxx`；
2. 追问"文件后半部分写了什么" → 它应调用 `artifact_read` 并答出细节（而非编造）。

### 风险 / 遗留

- artifact 仅支持文本（多模态留给后续）；无版本/血缘；
- 无跨会话共享策略（当前按 id 全局可读，本地单用户场景）；
- 未与 Task 绑定（artifact 不自动归属某个目标）。
