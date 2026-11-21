# S23 — 收敛 + Performance Gallery

> 状态：**进行中**（2026-09-13）。
> 两项遗留：S16b 的 `memory` 存储层抽离 + S18 的前端 Performance Gallery。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 23
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    收敛（memory 存储层）+ 可见性（Performance Gallery UI）
SURPRISE: Alt+G 打开表演库，点一下就现场演出
ARCHITECTURE:
  1. memory/store.py（SQLiteVecStore 逐字抽离）+ memory/constants.py（避免循环导入）
  2. shell App.vue：Alt+G Performance Gallery（列表 + 点击触发）
     数据源：GET /debug/avatar/performances；触发：POST /debug/avatar/perform/{name}
  不做（风险最高）：agent.send() 主体收敛（~380 行）→ 顺延
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 为什么 memory 抽离需要 constants.py

`SQLiteVecStore` 依赖 `DIM / VEC_K / EXPLICIT_PREFIX`；若 `store.py` 从 `yuiro.memory`
导入这些常量，会形成 `memory/__init__ → memory/store → memory/__init__` 的**循环导入**。
故先把常量抽到 `memory/constants.py`，两边都从它导入（单向依赖）。

## 交付报告（2026-09-13 完成）

### 结果

| 文件 | 之前 | 之后 | 手段 |
|---|---|---|---|
| `memory/__init__.py` | **1278 行** | **1070 行**（-208） | 抽离 `memory/store.py`（`SQLiteVecStore` 逐字搬运）+ `memory/constants.py` |
| `memory/store.py` | — | **206 行**（新增） | L2/L3 数据访问层（SQL + 行 → dict） |
| `memory/constants.py` | — | **9 行**（新增） | DIM / VEC_K / DEFAULT_MODEL / EXPLICIT_PREFIX |
| `shell/.../App.vue` | — | +125 行 | Performance Gallery（Alt+G） |

### 冒烟证据

```
constants.py: 9 lines      store.py: 206 lines
__init__.py: 1071 lines (was 1278)
imports ok
same class: True           ← re-export 后 SQLiteVecStore 是同一个类（零行为变化）
```

### Performance Gallery（S23-B）

- **Alt+G** 打开/关闭面板，`GET /debug/avatar/performances` 拉取表演库；
- 点击任一表演 → `POST /debug/avatar/perform/{name}` 现场演出；
- 面板展示每个表演的 `expression` / `motion`（即"这个语义名会用什么资源"），
  这正是 spec 说的"Performance Gallery 兼 Demo + Debug + Asset Preview"。

### Tests

- S23 为**纯搬运 + 前端 UI**，无新增测试；
- 全量回归 **275 passed / 5 failed / 1 error**（与 S22 基线逐项一致 → 搬运零行为变化）；
- `memory/store.py`、`memory/constants.py` 零告警；`__init__.py` 本次引入的 F401/I001/RUF100 已修；
- 前端 `pnpm typecheck` 通过。

### DoD 对照

- [x] `memory` 存储层独立成文件，`__init__.py` 减少 208 行
- [x] re-export 保持全部既有 import 路径可用（`same class: True`）
- [x] 常量抽到 `constants.py`，避免 `__init__ ↔ store` 循环导入
- [x] Performance Gallery 可用（Alt+G；列表 + 现场触发）
- [x] 回归通过；前端类型检查通过

### Human Acceptance（待人工）

1. 桌宠窗口按 **Alt+G** → 右上角出现"表演库"面板；
2. 点击 `celebrate` → 应看到表情 + 动作（引擎日志 `[表演] celebrate → …`）；
3. 点击 `comfort` / `greet` 等逐个确认（这就是真实的 Asset Preview）；
4. 引擎未启动时打开面板 → 显示"表演库为空（引擎未连接？）"而不报错。

### 风险 / 遗留

- **`agent.send()` 主体收敛仍未做**（~380 行：去重 / 限流 / 早停 / 收尾总结）——
  这是收敛主线里**风险最高**的一块（回合策略与状态强耦合），需要单独的 Sprint 与更细的护栏；
- `memory` 的 `Retriever` / `MemorySystem` / `KnowledgeStore` 仍在 `__init__.py`（本次只搬存储层）；
- Gallery 为桌宠窗口内的浮层（未做独立调试台页面）。
