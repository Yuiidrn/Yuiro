# Fish Audio HTTP 接入与充值后实机验收

日期：2026-10-23。当前窗口聚焦前后端功能开发与体验调整，不推进 G1 或扩大架构改造。

UI 续调：Fish 安全密钥入口已移入“语音合成”配置卡，仅当当前草稿选择 Fish 时显示，不再作为声音页独立块；语音试听保留。Electron DOM 检查确认卡内嵌入、切到其他引擎隐藏、试听保留三项通过；仅切换草稿验证，未保存或更改角色配置。类型检查与构建通过。入口位置在 `components/SectionForm.vue`，安全存储逻辑不变。

## 目标、边界与最终配置

Goal：Hotaru 使用 Fish 公共音色，Hiyori 保持原有设置；语音设置可在调试台独立保存、试听，切换期间不串声音。最小架构增量仅是现有 TTSProvider 的 HTTP Adapter 与安全配置入口，复用 Session/VoicePipeline/CharacterSwitch/解码/RMS 嘴型，不新增 Runtime、事件协议或外部框架。

- Hotaru：`provider=fish`，`fish_reference_id=ad0099b0c27a470eb2a11e9a37b14e4c`，合成引擎 `s2.1-pro`，`balanced`，语速 1.0，语音回复开启。实际 API 已成功合成，不只是公开模型元数据查询。
- Hiyori：仍为 SiliconFlow，原有音色、参考音频、大脑、人设与公共配置不替换；结束活动角色为 Hiyori。
- 密钥仅存 Windows OS keychain `yuiro-fish/tts`。AppConfig 不含 Fish 密钥字段，角色卡、配置 API、报告不包含密钥。调试台独立安全接口只返回已配置状态；保存失败明确报错，不明文降级。
- 不上传参考音频、不创建云端音色、不自动重试计费合成、不静默切换其他声音。HTTP 按句收齐音频后播放，不宣称 WebSocket/PCM 真流式已经实现。

## 改动与源码入口

| 位置 | 职责 |
|---|---|
| `engine/yuiro/audio/fish.py` | Fish HTTP、固定官方端点、引擎/音色区分、错误脱敏、取消传播、完整响应 WAV 长度修正、统一 Fish factory |
| `engine/yuiro/config.py` | 角色独立的非敏感 Fish 字段与调试台 schema |
| `engine/yuiro/main.py` | 主 VoicePipeline 装配接入 Fish |
| `engine/yuiro/debug_api.py` | 热更新/调试台自测采用同一 factory；安全 Key 接口；保存前验证 Fish 配置 |
| `engine/yuiro/keychain.py` | Fish 独立 OS keychain 服务；Provider 每次请求读取，缓存角色不保留旧 key |
| `shell/src/renderer/src/dev/components/FishKeySettings.vue` | 密码输入、安全保存/清除，不回显已有密钥 |
| `shell/src/renderer/src/dev/components/ProviderCard.vue` | 真实试听播放器；角色切换暂停、撤销 Blob、清空旧结果；迟到结果按 epoch 丢弃 |
| `shell/src/renderer/src/dev/DevApp.vue`、`configCatalog.ts` | 声音页接入；Fish 参数按 Provider 显示；Edge 音色卡不再误导 Fish 使用者 |
| `shell/src/renderer/dev.html` | CSP 仅增加本地 Blob 媒体来源，不放开远程媒体 |

接口依据：[官方 TTS](https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech)、[官方 OpenAPI](https://api.fish.audio/openapi.json)。`model` 请求头选合成引擎；`reference_id` 选角色音色。

## 真实验收结果

证据目录：[C0-fish-artifacts](C0-fish-artifacts/)。实际 Electron、Qwen、SiliconFlow 与 Fish 云端；自动化回归另行使用 mock，不混淆。

| 场景 | 结果与证据 |
|---|---|
| 充值前 Hotaru | Fish HTTP 402，账户 API credit 为 0；保留 `voices-before-topup.json`，不是成功样本 |
| 充值后 Hiyori→Hotaru→Hiyori | `voices.json` 三段均实际 AudioContext start=1，无超时，跨角色 start=0；Hotaru 为中文真实 Fish 合成 |
| Hiyori 说话中切 Hotaru | 页面时钟内旧 source 在切换触发后约 12.9ms 收到 stop |
| Hotaru 说话中切 Hiyori | 同口径约 18.5ms；不是物理扬声器静音延迟，也不是整条切换耗时 |
| Hotaru 合成中切换 | `cancel-pending.json`：切换前未播放；后台记录 `Fish HTTP 已取消`；切换后三秒窗口未出现旧音频 start |
| 调试台日文合成与实际试听 | `ui-audition.json`：Fish 合成 2239.4ms，实际 HTML audio 播放成功，时长 4.179592s |
| 调试台试听中切换 | 同一证据：旧 audio paused=true、有 pause 事件、旧元素已移除；不是只看 HTTP 200 |
| 配置恢复与隔离 | `config-roundtrip.json` 七项通过，包括旧草稿 409、独立表演映射、回切恢复、公共设置不变、临时修改清理 |
| 最终 Hiyori 恢复 | `hiyori-preserved-restore-hiyori.json` 与最后 `hiyori-preserved-ui.json`：与接入前原始基线完全一致（忽略新加且未使用的 Fish 参数） |

最终 UI 截图捕获失败，已在 `ui-audition.json` 记录 `screenshot_captured=false`；此前截图仅供问题定位，不拿它充当最终播放证据。

## 实测发现并修复的问题

1. **完整 HTTP WAV 仍带流式长度占位符。** 实际 RIFF/data 长度为接近 4GiB 的占位值。现在收齐响应后修正长度字段，不修改 PCM 样本，补精确字节对照测试。此前 AudioContext 可解码并不意味着所有播放器都兼容。
2. **调试台 CSP 不允许媒体 Blob。** 原生 audio 拒播还受页面策略影响；改用受控 Blob URL，仅放行 `media-src 'self' blob:`。清理时 pause + revoke，不积累试听资源。
3. **旧试听与迟到结果。** 切换角色/修订号变化/开始切换与卸载时清理播放器；异步回包只有当前 epoch 才显示。新增真实 Vue 函数测试覆盖。
4. **Hiyori 基线差异已追查并恢复。** 一度仅 `reply_tts_enabled` 从 false 变为 true。单字段反推可精确重建最初 SHA256；壳日志有语音回复按钮开启事件，但无法确定触发者，不归因于用户。未发现 Fish Provider/音色串入 Hiyori。声音复测是在开关开启状态完成，结束后通过配置 API 将其恢复原始 false，再验证原始基线一致；没有覆盖参考音频、人设等其他字段，也未重新生成基线掩盖差异。原始开关为关闭，因此最终 Hiyori 默认只回文字，若希望长期出声应由用户另行打开。

## 回归、指标边界与复现

- Python 全量 **809 passed / 66.03s**：[JUnit](C0-fish-artifacts/pytest.xml)。新增 Fish 16 项：请求/真实 PCM 解码与 RMS、401/402/403/429/500/503 脱敏且不自动重试、HTTP 取消与队列不交付、缺 Key/音色、角色往返及重启、Key 鉴权/不回显/存储失败、流式 WAV 修正与非法音频拒绝。
- Node：既有 C0 三场景通过；新增 `node scripts/diag/c0_fish_frontend_test.cjs` 三项通过（迟到响应、停播/撤销 Blob、限定媒体 CSP）。不是完整浏览器自动化套件。
- `pnpm typecheck`、`pnpm build` 通过；新增 Python 文件 F 检查通过；`git diff --check` 无空白错误（有换行格式提示）。
- 2.24s 是单个日文样本的完整 HTTP 合成耗时，不是首字/首音 P95，不与不同文本的 SiliconFlow 样本做速度优劣结论。充值前后从 402 到成功只证明可用性恢复。
- 调试台迟到响应丢弃已验；它的自测 HTTP 请求目前不是角色 Runtime 下的托管任务，切换后服务端自测合成可能继续完成。**正式对话链路**的合成取消已实测通过。后续如优化试听资源取消，应补 AbortController 与服务端断开取消，而不是宣称现已具备。
- 云端公共音色可见性与权益可能变化；本次没有验证商业授权。中文/日文清晰度与角色贴合度仍由用户听感最终审定，浏览器播放状态不能替代主观验收。

复现：根目录先加载 `config/env.ps1`。`scripts/diag/c0_fish_acceptance.py` 提供 `voices`、`ui`、`cancel`、`config`、`audit`；实机脚本需要现有引擎、Electron CDP 9222 与有效本机安全凭证。`voices` 需要 Hiyori 开启语音回复；测试如临时开启，必须恢复并比较原始基线。不要再次执行 baseline 覆盖历史证据。

未 commit/push，未删除或迁移用户数据库。保留实测产生的既有对话/关系数据变化，不混作功能代码修改。后续在本窗口只围绕前后端功能、交互、声音与演出调整推进，不开展 G1 架构演进。
