# C0 双角色实机续验（2026-10-23）

范围：延续现有 Runtime，仅局部修复；未进入 G1。实际工程位于 `D:\Project\Yuii\desktop-pet\Yuiro`，不是 ChatGPT 项目镜像。已重启本项目引擎与 Electron 壳；未删除角色数据或提交代码。

## 配置与切换

真实 Electron 调试台操作、实际引擎与两套 Live2D 模型，不是 fake provider：

- Hiyori→Hotaru→Hiyori 连续三组 UI 切换通过，调试台角色、宠物角色、模型路径与控制连接一致。
- [六次切换记录](C0-live-artifacts/switches.json)：后端 10.07–64.62ms，模型/连接就绪 204.87–565.73ms。包含 CDP 调用与轮询开销；浏览器资源缓存已热，不是全冷启动或长期 P95。
- [修改前记录](C0-live-artifacts/switches-before-fixes.json)：固定重连等待导致整体约 3.2–3.7s。`shell/src/renderer/src/App.vue:562` 对计划切换的 1012 关闭采用 100ms 重连；普通网络断开仍 3s。
- [配置往返七项检查](C0-live-artifacts/config-roundtrip.json)通过：Hiyori 临时大脑/人设修改不影响 Hotaru；回切恢复；自定义表演语义只在所属角色出现；旧角色保存返回 409；公共设置不变；临时修改已清除。缺少公开 agent 配置段的情况未包装成 API 全字段验证通过。
- 切换引起的预期取消不再作为 ASGI 异常传播（`engine/yuiro/main.py:1763`、`:1874`）；非切换取消仍继续抛出。

## Hotaru 声音修正与证据边界

用户明确选择使用现有 SiliconFlow 服务，为 Hotaru 单独设置不同音色。最终本地角色卡：Hotaru 使用 `siliconflow`、`FunAudioLLM/CosyVoice2-0.5B:claire`、参考音频为空、`reply_tts_enabled=true`；Hiyori 的既有参考音频克隆配置未改。不在报告中存储凭证，继续使用原有共享凭证机制。

重要纠正：此前 Hotaru 无声被初步描述成 Edge 超时，但复核发现其独立卡的语音回复开关为 false，未发起合成。故 [旧记录](C0-live-artifacts/voices-edge-failure.json)只能证明该配置下没有播放，**不能证明 Edge 服务不可用**。[第一次 SiliconFlow 复测](C0-live-artifacts/voices-tts-disabled.json)也受同一开关影响。未进一步诊断 Edge 的连接状态。

局部代码修复：新增角色可持久化的 `siliconflow_voice`（`engine/yuiro/config.py:133`、`:707`）；主链、调试台重建、自测统一读取它（`main.py:721`，`debug_api.py:264`、`:808`）。此前把基础模型名当成内置音色标识；现默认包含 `:anna`，Hotaru 单独用 `:claire`。参考音频克隆路径仍只发送 references，不发送 voice。

音色标识与 references/voice 互斥依据：[SiliconFlow 官方 TTS 指南](https://docs.siliconflow.cn/docs/userguide/capabilities/text-to-speech)、[Speech API](https://docs.siliconflow.cn/docs/api/audio-speech-post)。不据名称保证主观听感贴合角色。

[最终串行语音记录](C0-live-artifacts/voices.json)记录实际 Qwen→SiliconFlow→浏览器 AudioContext 播放；前两段在播放后 0.5s 切换，记录旧 source 的 stop/ended、跨角色 start。音频附件为实际合成 WAV。`voices-invalid-overlapping-checks.json` 是配置检查干扰语音检查的无效轮次，明确排除验收。诊断脚本已取消“收到 reply_end 就判无音频”的错误捷径：异步解码可能尚未完成。

最终串行三段均各有 1 次实际播放 start、无超时、跨角色 start 为 0。Hiyori→Hotaru 与 Hotaru→Hiyori 两次说话中切换，旧 source 在触发切换后分别约 **12.8ms / 13.5ms** 收到 stop。这是宠物页面时钟内的本地停播指令延迟，不是声卡物理静音延迟。结束恢复 Hiyori。

## 回归与尚未验收

- 全量 Python：**793 passed / 57.45s**，见 [JUnit](C0-live-artifacts/pytest-final.xml)。新增三项覆盖音色默认值/元数据及克隆、内置音色请求互斥；角色切片 21 项通过。
- Node 三个真实前端函数时序场景通过；`pnpm typecheck`、`pnpm build` 通过；`git diff --check` 无空白错误（有既有换行格式提示）。不等于全仓 lint 或完整 E2E 全绿。
- 真实声音清晰度、语种、音色差异与角色贴合度仍需用户听觉确认；浏览器播放调用不能证明扬声器可听。当前两个角色共用云服务，但音色配置独立。
- 表演资源候选隔离和实际模型加载已测；完整动作/表情视觉审定、说话中嘴型与动作迟到复活、多调试窗口同步、开麦中切换及长时压力测试仍待继续，不宣称 C0 整体验收完成。
- 云合成等待与切卡耗时是不同指标，本次没有解决云服务首音延迟；不能把亚秒切卡表述成亚秒语音回复。
- 发现切换遍历包含已归档 session id，可能产生多余 interrupt 状态/日志；留作 C0 局部检查，不扩大到 Runtime 重写。

下一步只完成上述 C0 未验项，再决定是否进入 G1。保留现有 Runtime、两卡与数据库；不引入第二套角色/Agent 框架。
