# S33 — Tool Transaction（文件操作可回滚）

> 状态：**完成**（2026-09-13）。
> 来源：`docs/spec/architecture-goal.md` §3.15（"桌面 Agent 的 Checkpoint 应发展成
> **Tool Transaction**，不是 Git checkpoint"）+ S29 遗留（"Checkpoint 是摘要级，
> 真正的文件级回滚属 `transaction.cpp`，未做"）+ v1.0 收口清单。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 33
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Tool Transaction —— "改错了能撤回"
SURPRISE: 它整理完你的文件夹，你说"恢复刚才的操作"，一切回到原样
ARCHITECTURE:
  一次工具调用 = 一个事务（TxnRecord + TxnOp[]）
  写前备份 → 执行 → 提交（落盘）→ rollback 逆序撤销
  补上安全三件套最后一块：Approval（S11/S29）+ Checkpoint（S29 摘要级）+ Rollback（资源级）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 0. 先补的前置缺口

`native/ops.py` 此前只有 `file_create / file_read / file_write` —— **没有 move / delete**，
而 spec 的 `move_files: dry_run → record original paths → execute → rollback token`
主场景正依赖它们。所以本 Sprint 先补两个文件原语，再谈事务：

| 工具 | 说明 |
|---|---|
| `file_move` | **批量**移动；多文件时 `dest` 是目录（不存在则创建）；目标已存在**不覆盖** |
| `file_delete` | 仅删文件（目录拒绝，避免误伤整棵树） |

## 1. 事务模型

```
Tool call ─┬─ file_create ┐ 写前：备份原内容（仅当目标已存在）
           ├─ file_write  ┤ 执行：真实文件操作
           ├─ file_move   ┤ 成功后：TxnRecord 落盘 + 触发保留策略
           └─ file_delete ┘
                                 ↓
              用户："恢复刚才的操作" → transaction_rollback
                                 ↓
        逆序 undo（move→移回 / overwrite·delete→还原 / create·mkdir→删除）
```

磁盘布局（`[transaction].backup_root`，默认 `.yuiro/txn`）：

```
.yuiro/txn/
├── records/<txn_id>.json      # 事务记录（回滚后原地更新 status）
└── blobs/<txn_id>/<seq>.bak   # 被覆盖 / 删除文件的原始内容
```

## 2. 设计取舍

| 决策 | 理由 |
|---|---|
| **一次工具调用 = 一个事务** | 边界清晰、可测；`file_move(paths=[…])` 的批量语义天然对应"整理一次 → 撤销一次"（spec 的 `move_files`） |
| **只在必要时备份** | `create` 回滚=删除（无需备份）、`move` 回滚=移回（无需备份）—— 少写一份数据就少一处失败点 |
| **备份失败不阻断操作** | 备份写不下时操作照常执行，只是该步不可回滚（回滚时记 partial，而非整体拒绝） |
| **逆序回滚** | 后做的先撤，与人的直觉一致 |
| **重复回滚被拒** | 明确反馈"已回滚过"，绝不静默地去撤别的东西（那才危险） |
| **回滚同样受 CapabilityScope 约束** | 不能借回滚把文件写到越界位置（S19 的边界在回滚路径上同样生效） |
| **保留最近 N 个事务**（默认 20） | 否则备份目录无限增长 |

## 3. 交付报告

### Changed files

**新增**：`engine/yuiro/transaction/`（`models.py` / `store.py` / `__init__.py`）、
`engine/tests/test_transaction.py`（20 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/native/ops.py` | 新增 `file_move` / `file_delete` 原语 |
| `engine/yuiro/native/backend.py` | 四个文件写操作**自动事务化**；`rollback_transaction()` / `list_transactions()`；结果回传 `txn_id` |
| `engine/yuiro/systemd/client.py` | `SystemActionResult.txn_id`（daemon 侧留空，向后兼容） |
| `engine/yuiro/tools/system_tool.py` | 新增 `file_move` / `file_delete` / `transaction_list` / `transaction_rollback`（`SYSTEM_TOOLS` 6 → 10） |
| `engine/yuiro/capability/policy.py` | 风险登记：`file_move` MEDIUM、`transaction_rollback` MEDIUM、`transaction_list` LOW |
| `engine/yuiro/config.py` + `config.toml` + `config.example.toml` | 新增 `[transaction]`（enabled / backup_root / keep） |
| `engine/yuiro/main.py` | 装配 `TxnStore`；启动日志显式打印"文件事务：已启用/未启用"（静默降级比报错更难排查） |
| `engine/yuiro/debug_api.py` | `GET /api/transaction/list` + `POST /api/transaction/rollback` |
| `engine/tests/test_native_backend.py` | 工具集护栏改为**单向包含**断言（native ⊇ daemon） |

### 冒烟证据

真实临时目录上的完整闭环（整理 → 覆盖 → 删除 → 逐个撤销）：

```
BEFORE 下载: ['报告.pdf', '照片1.png', '照片2.png', '笔记.txt']
MOVE   : ok | 已移动 2 项：照片1.png → 图片\；照片2.png → 图片\      ← 批量 = 一个事务
TXN-ID : txn-6aa665c7-6a1c9c
DRYRUN : dry-run | txn: ''                                        ← dry-run 不产生事务
WRITE  : ok | 已写入文件: 笔记.txt（18 字节）
DELETE : ok | 已删除文件: 报告.pdf（17 字节）
AFTER  下载: ['笔记.txt'] | 图片: ['照片1.png', '照片2.png']
VIEW   : total=3 reversible=3
  TXN  : txn-…｜file_delete｜1 步｜已提交｜删除 …报告.pdf
  TXN  : txn-…｜file_write｜1 步｜已提交｜覆盖 …笔记.txt
  TXN  : txn-…｜file_move｜2 步｜已提交｜移动 …照片1.png → …图片\照片1.png；…
ROLLBK : True | 已回滚 …（1 步全部撤销）：删除 …报告.pdf：已还原原内容
ROLLBK : True | 已回滚 …（1 步全部撤销）：覆盖 …笔记.txt：已还原原内容
ROLLBK : True | 已回滚 …（2 步全部撤销）：移动 …：已移回原位；…
RESTORE下载: ['报告.pdf', '照片1.png', '照片2.png', '笔记.txt']
RESTORE图片目录存在: False                                        ← 新建的空目录也一并删除
NOTE内容   : 内容:笔记.txt                                        ← 原内容回来了
REPORT存在 : True
SMOKE: PASS ✅ 全部回到操作前
```

### 冒烟抓出的两个真问题（本次修复）

1. **批量移动时"目标目录不存在"被预检拒绝** —— 而"整理下载夹 → 新建图片目录"**正是主场景**。
   测试先红（`test_move_batch_rollback_restores_all`）；修正为：只拒绝把**文件**当目录用，
   目录不存在则创建。
2. **撤销后留下空目录**：新建的 `dest` 目录没被记录 → 用户会在磁盘上看到一个多出来的空文件夹。
   修正：`file_move` 若创建了目标目录，就在事务首位记一条 `mkdir` 操作，逆序回滚时（若已空）删除。

> 第 2 个只有**看真实文件系统**才会发现（单测里 `os.path.isdir` 为真也算"回滚成功"）。
> 这正是冒烟脚本不可替代的地方 —— 也是本项目第 6 个由冒烟/测试抓出的静默类问题。

### Tests

- 新增 **20 个**全部通过：覆盖写还原 / 新建回滚删除 / delete 回滚恢复 / 单个与批量 move /
  新建目录回滚删除 / 已有目录保留 / **重启后仍可回滚**（落盘）/ 重复回滚被拒 / 保留策略 /
  dry-run 无事务 / 失败操作无残留事务 / 目标冲突时整体不动手 / 把文件当目录被拒 /
  原位置被占 → partial 且不覆盖外部改动 / 目录不可删除 / 视图形状 / 工具层端到端 /
  关闭开关后明确报错；
- 全量回归 **394 passed / 5 failed / 1 error**（失败集与基线一致，均为既有问题）；
- `transaction/`、`native/`、`tools/system_tool.py`、测试文件 ruff 零告警。

### DoD 对照

- [x] 文件写操作自动事务化（create / write / move / delete），落在**真实执行点**（NativeBackend）
- [x] `rollback(txn_id | "last")` —— 对应 spec 的用户原话"恢复刚才的操作"
- [x] 落盘 + **重启后仍可回滚**
- [x] 批量移动 = 单个事务（`move_files` 语义）
- [x] dry-run 不产生副作用（也不产生事务）
- [x] 回滚受 CapabilityScope 约束；重复回滚明确拒绝
- [x] LLM 侧工具（`transaction_list` / `transaction_rollback`）+ 调试台 API
- [x] 保留策略（keep=20），备份不无限增长

### Human Acceptance（待人工）

1. 让 Yuiro「**把下载文件夹里的图片都移到"图片"子文件夹**」→ 它应给出计划（S29）→ 批准后执行；
2. 接着说「**恢复刚才的操作**」→ 预期：文件全部移回、**"图片"目录也消失**（若它原本不存在），
   回复里说明撤销了哪几步；
3. 说「**你刚才改了什么**」→ 预期它调 `transaction_list` 并如实汇报（而不是猜）；
4. 访问 `GET /api/transaction/list` 看事务；`POST /api/transaction/rollback?txn_id=last` 现场撤销；
5. 降级验证：`[transaction].enabled = false` → 重启 → 说"恢复刚才的操作" →
   应明确回答"事务未启用"（而不是静默失败）。

### 风险 / 遗留

- **C++ daemon 侧未同步**（`transaction.cpp` 仍是 spec 目标）：daemon 是可选后端，
  切到 `backend = "daemon"` 时没有事务能力。native 已是默认后端，实际使用不受影响；
- **非文件操作不可回滚**：`app_open` / `media_control` 无副作用可撤销（也无需撤销）；
- **整文件备份**：超大文件（GB 级）会占用等量磁盘；如遇到再引入"元数据 + 差异备份"；
- **回滚非原子**：多步回滚中途失败会停在 partial（如实报告），不回滚已完成的步骤
  （避免"回滚的回滚"这种不可理解的状态）；
- **无前端 UI**：事务视图只在调试台/API（与 S18 Performance Gallery 的位置策略一致）。
