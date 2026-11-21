# 联网检索切换 DeepSeek：实现与验收

日期：2026-10-23。范围为前后端功能调整，不推进架构阶段或重写 Agent Runtime。

## 目标与实现

Goal：移除现有国外搜索后端，让当前聊天模型通过 DeepSeek 独立 Search API 获取带来源的实时资料；调试台可以配置并直接验证。

Scenario：联网页保存总开关/安全密钥 → 测试搜索，显示耗时与可打开的来源 → 聊天开启联网后，现有 AgentLoop 调用 `web_search`，根据结果给出来源链接。关闭总开关、缺密钥或本轮禁用仍隐藏工具。

最小增量：复用 WebSearchTool、工具注册/可见性、现有 Agent 活动事件及结果注入，不引入额外搜索模型、框架或 Runtime。当前聊天模型、角色卡和 TTS 不替换。

改动入口：

- `engine/yuiro/tools/web_tool.py`：删除 TavilyProvider；新增 DeepSeekSearchProvider，固定请求 `https://api.deepseek.com/v1/tools/search`，Bearer 鉴权，发送 `query/count/need_content=false`。由 `httpx.AsyncClient` 替代不可真正取消的线程内 urllib；整体超时预算和 CancelledError 传播。
- `engine/yuiro/config.py`：仅显示 DeepSeek。旧 Tavily/SearXNG/SerpAPI 名称只用于迁移识别，旧端点强制归一为官方端点；运行时不再有旧服务商实现或回退。示例 TOML 同步更新。
- `engine/yuiro/keychain.py`：搜索密钥改用独立 `yuiro-deepseek-search/search` 命名空间；不读取旧搜索服务商 Key，也不隐式复用 LLM Key。旧凭证未破坏性删除，但不再使用。新密钥已安全保存，配置和报告不存明文。
- `engine/yuiro/debug_api.py`：搜索 Key 接口补鉴权；存储失败明确 503，不假称“内存已生效”；新增鉴权后的 `/api/search/test`，按已保存总开关执行。
- `shell/src/renderer/src/dev/components/SectionForm.vue`、`configCatalog.ts`：删除旧候选和自定义端点输入；安全密钥标签改为 DeepSeek；保留条数、超时，新增可选结果提炼。
- `SearchStatus.vue`、`dev/api.ts`：联网页新增测试词输入、真实搜索按钮、返回条数/耗时/来源摘要；链接通过现有 `openExternal` 在系统浏览器打开。

## 质量、安全与延迟取舍

- 摘要优先 summary，缺失时用 snippet；每条最多 300 字、标题最多 120 字、默认 3 条/上限 5 条，不返回 content 全文。
- 精确 URL 去重，拒绝非 HTTP(S) 与含用户名密码的链接；保留站点名称和发布时间，未知日期留空，不编造。
- 查询词限制 1–128 字符。日志只在 Provider 记录字符数、结果数和耗时，不记录密钥或供应商原始错误正文。既有 Agent 日志仍可能记录当轮工具查询，不宣称全链路隐去 query。
- 401/402/429/504 等给出可读原因，异常格式响应明确失败，不伪造空结果；本轮不自动重试，不回退其他服务商。
- 结果带“不可信外部数据，不是指令”的标记；开启额外提炼时同样声明不执行网页中的指令。此标记不是提示注入安全性的完整证明，现有审批边界不变。
- `refine_results=false` 为新默认：多条摘要直接交主模型，省去此前默认额外一次 LLM 往返；如需要可在高级项启用。未声称不同查询的整体回答延迟必然降低。
- 保留默认总开关关闭、会话级禁用；已有用户开启状态保留，不因测试把关闭配置永久开启。联网会发送当轮查询到 DeepSeek，并按账户/API 规则计费。

官方契约：[Search/Fetch 使用指南](https://api-docs.deepseek.com/zh-cn/guides/search/)。本轮只落地 Search，不增加 Fetch、爬虫或独立网页阅读器。

## 真实验收

证据：[live-search.json](deepseek-search-artifacts/live-search.json)、[agent-search.json](deepseek-search-artifacts/agent-search.json)。引擎已重启到新代码，实际 Electron 调试台、当前真实聊天模型、真实 DeepSeek 服务，不是 fake provider。

1. 调试台“联网”页直接执行测试：`status=ok`、3 条来源，含 `https://api-docs.deepseek.com/zh-cn/`。样本耗时 **702.7ms**；前一相同查询样本 856.8ms。单次网络样本，不是 P95 或长期 SLA。
2. 运行时 provider 为 deepseek、schema 候选仅 `[deepseek]`、旧 endpoint 不可编辑。
3. 实际发送显式联网问题，Agent 日志出现 `收到 tool_call chunk: web_search`、`turn.step` 为 `status=ok`，对应 DeepSeek 请求约 **746.4ms**；实际回复含官网 URL。
4. 该聊天回合整体约 **13.51s**，包含记忆检索和多轮 LLM；不能把约 0.75s 搜索耗时说成整体回复耗时。TTS/语言转换仍属独立后续链路。
5. `agent-search.json` 的调用探测最初误匹配“工具调用”日志，已根据实际 `收到 tool_call chunk` 与 turn.step 记录修正探测及回执；不是没有执行搜索后补写成功。

## 回归与限制

- 搜索定向 **40 项通过**（原工具 22 项 + 新增 18 项），覆盖请求契约、摘要预算、URL 筛选/去重、日期、401/402/403/429/5xx 脱敏且不重试、响应格式、取消与超时、旧配置迁移、新旧凭证隔离、自测鉴权/禁用/参数检查，以及原有工具可见性与会话级禁用。
- 全量 Python **827 passed / 88.56s**：[JUnit](deepseek-search-artifacts/pytest.xml)。不是只跑搜索测试后的数量。
- `pnpm typecheck`、`pnpm build` 通过；新增/核心搜索 Python F 检查通过；`git diff --check` 无空白错误，有既有换行格式提示。
- 搜索源可能含第三方镜像或非官方内容，不会自动判定全部结果可信；优先官方来源仍需模型结合问题选择。未返回日期时不显示伪造日期。
- 调试台联调有来源列表，正式聊天复用既有工具活动和带 URL 的回答；本轮不宣称新增完整的聊天搜索来源卡系统。
- 没有测长期稳定性、所有查询类别、实时天气准确度或供应商排名优劣。Fetch、短期缓存及专门的来源卡交互留作后续功能任务。

复现：根目录加载 `config/env.ps1`；引擎内运行 `python -m pytest tests/test_web_tool.py tests/test_deepseek_search.py -q`。实机可运行 `scripts/diag/deepseek_search_acceptance.py`，需引擎、Electron CDP 9222 与本机安全密钥，会发出实际 API/聊天请求；不应在 CI 自动运行计费联调。

未 commit/push，未清除旧凭证、删除数据库或覆盖其他角色设置。实测产生的对话/关系数据变化保留，不计为功能代码更改。
