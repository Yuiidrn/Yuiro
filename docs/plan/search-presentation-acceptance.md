# 联网来源卡意图分流与语音正文：双角色验收

日期：2026-10-23。前后端增量调整，复用现有 `agent.result` / `agent:result` 通道、结果卡、TTS 出口和角色切换，不新增 Runtime 或架构阶段。

## 行为与职责

- **需要资料入口/核验来源**：用户提到文档、官网、链接、来源、教程、资料、证据、比较/选购等时，成功搜索后展示来源卡。规则直接读本轮原始用户意图，不用搜索工具改写后的关键词，不额外调用分类模型。
- **普通事实回答**：例如联网确认天气、版本等，搜索仍正常用于主模型回答，但不默认弹卡。明确“不用来源/不要卡片/只要答案”优先抑制卡片。
- 这是一套保守启发式，不宣称所有自然语言都能正确识别；规则集中在 `engine/yuiro/search_presentation.py`，可按后续实际交互调整。
- `agent/__init__.py` 在每轮 send 中计算意图，在真实工具结果转换成卡片时使用；媒体卡不受来源意图影响。来源卡不展示不等于搜索未执行或结果未进入 LLM。
- `ResultCard.vue` 补标题、域名、三行摘要与发布时间；未知日期明确显示“发布时间未知”，不伪造日期。来源条目支持点击/键盘 Enter，复用系统浏览器打开路径；不在桌宠中嵌浏览器。来源卡默认停留 40s，其他媒体卡仍 20s。

## 角色与迟到结果防护

此前 `_push_agent_result` 广播只携带列表内容，丢失了源事件身份。本轮补传 session_id、generation、character_id、character_revision；推送前拒绝切换中/不存在或代际过期的来源会话。

`App.vue` 在开始切换、1012 关闭、实际角色变化时清卡并取消旧计时器；旧 WebSocket 回调不再处理消息。接收卡片时校验当前会话，来源卡另校验角色和角色修订号。新文字输入/ASR 识别开始清理上一轮来源卡。不是仅在切换后的页面上隐藏旧 DOM。

## 语音只朗读正文

`engine/yuiro/audio/speech_text.py` 负责清理 HTTP(S)、www 与常见裸域名、Markdown 链接地址和数字引用标号，以及独立的末尾参考列表。Markdown 链接保留可读标题，屏幕回答/历史原文不修改。版本号如 `3.14.0` 不当成域名。

文字回复：`main._speak_reply` **先清理全文再分句**，翻译后合成前再次清理；纯链接不触发合成，仍正常发送回复结束。

语音链路：`split_sentences` 在长句硬切前清理，`OutputRenderer.render_speak` 在转换前后清理；TTSTaskManager 入队前再设一道保护，空片段以空 segment 保序，不调用供应商。流式 Agent 分句避开 URL 内的 `?`/`;`，防止链接尾部参数被切成普通台词。展示语言转换不执行这套语音清理。

## 真实双角色证据

证据：[live.json](search-presentation-artifacts/live.json)，同目录有四段实际合成 WAV。真实当前 LLM、DeepSeek、Hiyori SiliconFlow、Hotaru Fish；不是假搜索结果驱动的展示测试。

| 场景 | 实际结果 |
|---|---|
| Hiyori 查询官方文档 | 1 次来源卡事件；实际 DOM 3 条标题/摘要/日期栏；音频播放 start=1 |
| Hiyori 只要版本答案 | 无来源卡事件/DOM；音频播放 start=1 |
| Hotaru 查询官方文档 | 模型调用两次搜索、2 次卡片事件，单张卡替换显示；实际 DOM 3 条摘要/日期栏；音频播放 start=1 |
| Hotaru 只要版本答案 | 无来源卡事件/DOM；音频播放 start=1 |
| Hiyori→Hotaru | 真实切换后旧卡为空；将旧身份消息注入新 socket 后仍为空 |
| Hotaru→Hiyori | 同上，双向通过 |

“旧身份消息注入”是明确的合成竞态检查，不包装成供应商真的发送了迟到消息。正常卡片/音频部分来自真实对话。

首轮发现裸域名仍可能被朗读，已修复并重启引擎后重跑以上四场景；首轮记录保留为 `live-before-bare-domain-fix.json`，不是最终验收结果。首轮 Hiyori 长回答导致卡片在音频结束前自然到期；最终脚本同时记录 `observed_before_expiry`，避免把超时收卡误判为“从未显示”。

后端 TTS 正文日志确认链接片段被清理，四段均进入实际 AudioContext 播放；没有通过 ASR 转写或人的听觉逐字确认，因此不声称物理音箱听感和克隆表现已经人工审定。截图捕获未成功，最终呈现依据实际 DOM 与事件记录，不将其称为截图视觉验收。搜索结果本轮未提供发布时间时，展示未知日期；已知日期透传由自动化样本覆盖。

临时开启的 Hiyori 语音回复已恢复原始 **false**；Hotaru 恢复原始 **true**；结束角色为 Hiyori。两者音色、模型、语言、人设未替换。当前已保存的联网开关不因这次功能改造改变。

## 回归与边界

- 本轮新增 **18 项**意图/正文清理/链接分句/空 TTS 队列/真实卡片事件发射测试（`test_search_presentation.py`）。首次定向（当时尚未加入裸域名样本）52 项通过。
- 最终全量：**844 passed, 1 skipped / 99.72s**，见 [JUnit](search-presentation-artifacts/pytest.xml)。跳过的是既有 `test_agentloop_memory_roundtrip`，原因是 BGE-M3 未成功加载；不是来源卡或 TTS 测试跳过，不宣称全量无跳过。
- 对该记忆用例单独重跑结果为 **1 passed / 34.37s**；与全量结果分别记录，不回改 JUnit 的跳过事实。
- Node 原有 C0 三个真实前端函数场景通过；因 loadModelPath 现在调用清卡函数，相应隔离测试补了该依赖 stub。
- `pnpm typecheck` / `pnpm build` 通过；新增 Python F 检查通过，diff 空白检查通过（有换行格式提示）。
- 未改搜索排序或事实真伪判断；模型仍可能给出错误/不充分结论，卡片只是核验入口。未新增独立聊天记录内的永久引用档案，卡片仍是现有的临时桌宠结果卡。
- 未上传音色、迁移记忆、删除数据库或 commit/push。验收产生的真实对话/关系数据保留。

复现：根目录加载 `config/env.ps1`；定向测试 `engine/tests/test_search_presentation.py`；`scripts/diag/search_presentation_acceptance.py` 需要已运行的 Engine 与 Electron CDP 9222，会调用真实云 API 并临时打开语音回复，finally 恢复开关。音频与日志不是密钥，报告中不包含任何服务商密钥。
