# C0：Hiyori / Hotaru Shiomi 独立角色卡与切换

日期：2026-10-23。源码起点 HEAD `20f524f2e8f7ab50581ff4b13d2fccd23cde843c`；本轮未提交。用户明确将双角色隔离置于正式 G1–G5 演进前。C0 是现有 Runtime 上的局部装配/配置增量，不是第二套架构。

## 1. Goal / Scenario / 交付状态

调试台顶部切换 Hiyori → Hotaru Shiomi → Hiyori，大脑参数、声音、人设、模型、表演配置和角色数据跟随；切回后恢复自己原来的设置与进程内历史。正常切换无需二次确认；有未保存的表单输入时确认丢弃草稿。切换期间禁用选择器，失败明确提示并恢复原角色。

**首版工程已落地，自动化通过；真实设备/云 TTS/Live2D 视觉和端到端切换耗时尚未验收。** 不承诺零延迟、瞬间加载或角色音色已经符合用户审美。已初始化本机两份配置；运行中的旧引擎/旧壳不会自动替换源码，需要重新启动当前版本后使用。

## 2. 独立与共享边界

| 独立于角色 | 实现 |
|---|---|
| LLM 提供商/端点/模型/温度、Agent 预算、Context 预算 | 每卡保存；可共用模型服务，不复制模型权重 |
| TTS provider、音色/参考音频与转写、语言 | 每卡保存；不会只换 persona.voice 而遗留旧克隆参考 |
| 人设、名称、模型及全部表现映射/模型档案 | 每卡保存，整段覆盖，Hotaru 不继承 Hiyori 的表情名 |
| Memory、知识库、关系、任务、会话/事件日志、情绪、Avatar 状态 | 独立 store/对象；Hiyori 保留旧数据归属，不复制给 Hotaru |
| 待机行为 UI 偏好 | 按角色隔离的 localStorage；Hiyori 保留旧键，Hotaru 新命名空间。该类现有界面偏好未搬进 TOML |

| 共用 | 边界 |
|---|---|
| Engine/Electron、VAD/ASR、麦克风、系统后端、权限/审批/事务、通用工具与联网功能 | 不为每张卡复制，角色不能提高权限 |
| Keychain 凭证 | 保留现有公共凭证配置；卡内不复制明文。不同提供商需要不同凭证时，目前须通过已有凭证入口管理，不伪装成独立凭证库 |
| 用户日记 | 日记原文/草稿保留；角色切换刷新点评的 LLM 与当前 memory 绑定；撤销共享时清除两个角色库的对应源条目，包括未热加载的库 |

本机配置文件（已创建，gitignore，含私人提示词/本地路径，不加入源码提交）：

- `engine/characters/hiyori.toml`
- `engine/characters/hotaru.toml`
- `engine/characters/active.json`（仅活动角色指针）

`engine/config.toml` 继续承载公共设置，并保留旧角色段作为兼容回退。读取顺序：旧 AppConfig → 当前角色整段覆盖；保存角色设置只写当前卡，公共设置写回公共文件。首次迁移不覆盖已有卡、不搬动旧数据库。现有 Hiyori 人设/声音保持用户原设置；Hotaru 使用独立、可编辑的初值（Edge 中文 Xiaoyi 音色和简短人设），不是已审定的角色复刻。两卡初始可以使用同一个 LLM，之后分别调整不会联动。

## 3. Architecture Increment / 现有落点

- `engine/yuiro/characters.py`：卡列表、初始化、解析、整段覆盖、原子写文件、active 指针；只接受固定两个 id，不提供任意路径/脚本导入。
- `config.py`：复用现有 AppConfig/TOML 读写，增加角色覆盖，不新增平行配置体系。
- `character_switch.py`：串行切换事务，准备失败不打断旧角色；取消/提交失败回退。
- `main.py`：仍是组合根。注入原有 Agent factory；准备/停止/激活回调接现有 Session、AgentLoop、VoicePipeline、AvatarRuntime 和 Registry。
- `debug_api.py`：新增 GET `/api/characters` 与 POST `/api/characters/switch`；配置读回携带角色 id/revision；旧角色或旧 revision 保存返回 409。切换沿用 shared-secret 鉴权。
- shell：顶栏选择器；切换后重新挂载页面，清旧草稿/会话/审批卡；外观页明确“仅调整当前角色”，不把模型选择伪装成完整角色切换。表演资源异步读取、预览 IPC 携带角色/模型边界。

切换顺序：解析并检查目标资源 → 保存旧配置 → 停止旧播放/录音启动、取消并等待旧连接/回合/朗读任务（3s 收敛预算，超时拒绝）→ 恢复/装配目标 store、Agent、声音、Avatar → 更新 Registry → 提交 active → renderer 重连并读取模型。已发生的外部副作用不因为切换而撤销。

两张卡缓存各自的轻量状态和客户端；再次切换复用已装配对象。相同 embedding 配置借用同一个嵌入 worker，SQLite store 不共享。设备与语音识别不随角色重载。公共凭证/配置更改后使非活动角色的 provider/工具装配缓存失效，避免恢复旧 key/旧工具清单；数据 store 仍复用。外部手改非活动且已缓存的角色卡时拒绝混用新配置与旧对象，要求重启加载。

必要边界修复：音频 decode 前后检查播放 epoch，旧 finally 不改新轮计数；模型异步装载检查 revision，迟到实例销毁；等待语音启动期间切换后不再迟到开麦。关闭路径释放角色 store/共享 worker，同时修复既有 `daemon` 未定义的 teardown 问题。仅为本场景补这些屏障，不宣称 G1 全部竞态已完成。

## 4. Tests / 本轮证据

- **全量 Python：790 passed / 46.11s**，含真实 BGE 集成，不是排除慢项后的快测。[JUnit](C0-character-artifacts/pytest.xml)。此前 G0 的 772 项不作为本轮结果；耗时变化不等于产品延迟改善。
- 新增 **18 项** C0 测试：配置 A→B→A/重启、共享与独立边界、非法 id、准备失败、激活/提交失败回退、切换中取消与串行化、旧保存拒绝、切换鉴权、共享 embedder 下真实 SQLite 隔离，以及真实 main 装配回调（fake LLM factory、真实本地 store、无用户数据/云请求）。测试实际验证 Registry、history 隔离与恢复、旧任务取消、热 memory 复用、日记草稿保留和跨角色撤销隐私。
- Node：**3 个真实前端函数的确定时序场景通过**（迟到 decode/旧清理不影响新轮；A/B 模型加载乱序只安装 B；配置回读不抹掉已下发的新 Session）。不是完整浏览器 E2E。
- shell：`pnpm typecheck`、`pnpm build` 通过。`ruff` 新 Python 文件 F 检查及 main F821 通过；不是全仓 lint 清零。

复现：引擎目录先 `. ..\config\env.ps1`，再用 `..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q --disable-warnings -p no:cacheprovider --junitxml=../docs/plan/C0-character-artifacts/pytest.xml`；只跑本切片用 `tests/test_character_cards.py`。根目录 `node scripts/diag/c0_frontend_test.cjs`；shell 目录加载同一环境后运行 `pnpm typecheck` 和 `pnpm build`。

## 5. DoD / 待人工验收与限制

后续实机进展以 [C0-live-acceptance.md](C0-live-acceptance.md) 为准：已按用户授权为 Hotaru 使用现有 SiliconFlow 独立音色并调用真实云服务。下列“未调用付费云接口”等描述仅属初始实现阶段历史状态，不代表当前续验。

工程隔离、持久化、失败回退和现有回归已通过。以下仍待实机验证，不写成“无感/极速已达标”：

1. 重启引擎与壳后，在调试台顶部连续 A→B→A：分别调整大脑、音色、人设、表演，确认回切与重启均保留；确认公共设备/权限不变化。
2. 在说话、等待回答、开麦、调试表演时切换：旧声音/嘴型/动作不复活；检查后端切换耗时、重连、模型 ready、首个新角色音频四个独立时间，不拿本地函数耗时代替整体体验。
3. 两个调试窗口同时打开：角色同步；旧草稿保存拒绝；无映射/加载失败有明确提示，不残留上一角色候选。
4. 实际 Hiyori / Hotaru casual 的视觉与声音审定仍需要用户完成。首次模型纹理/音频服务冷启动不可消除；本轮未自动下载音色、没有为实测切换生产 provider 或调用付费云接口。
5. 本地 GPT-SoVITS 的说话人模型如果在外部服务启动时固化，切卡不能凭 HTTP 配置把它变成另一音色；需要独立可用的服务端点或后端支持。未具备时只能明确报告，不宣称两套本地权重自动热换已完成。

DIY：保留 CharacterStore 的 list/resolve/save 与切换回调接口；创建器、导入包、角色商店、多角色同时在线暂缓。下一步是双角色实机验收和按用户选择调好 Hotaru 声音/人设，不扩展插件平台或重写 AgentLoop。

回退：停止新版本后保留两卡备份，移开 `engine/characters/active.json` 可禁用配置覆盖（新 main 启动会按初始化策略再次启用，若要回退代码需一并撤回 C0 接入）。旧 config.toml 与数据库未迁移/删除；不要删除角色数据库来“修复”切换。未执行 commit/push。
