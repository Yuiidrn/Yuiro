# 首段等待的真实主窗口整合回放

Goal：将首段等待补丁的验证从隔离composable推进到实际App消息处理器、模型presence/口型props和播放器。Scenario：正式Hiyori→Hotaru→Hiyori换角；每次分别回放有音频和空结果；新角色等待时投递旧角色音频与结束帧。Architecture Increment：无生产修改，仅新增可清理CDP诊断。Tests：真实构建桌宠主窗口、实际SDK模型、真实WebAudio与本地合成入站消息；有界等待。DoD：六场景状态断言、两个方向旧会话拒收、结束恢复Hotaru并移除全部钩子，明确模拟与真实服务边界。

## 结果

执行：`.env-local/engine-venv2/Scripts/python.exe scripts/diag/avatar_tts_waiting_integrated_live.py`。

证据：[完整状态与最终清理](avatar-tts-waiting-integrated-live.json)。当前主窗口构建沿用首段等待补丁的`index-Cyk2OWl1.js`。

| 正式角色切换顺序 | 有音频 | 空音频 | 旧角色音频/结束帧 |
| --- | --- | --- | --- |
| Hiyori | thinking→speaking→idle；说话时mouthOpen>0，结束0 | thinking→idle；mouthOpen=0 | 首角色没有此前fixture身份，不作此项断言 |
| Hotaru | 同上 | 同上 | 旧Hiyori会话帧均未改变新角色thinking或口型 |
| Hiyori | 同上 | 同上 | 旧Hotaru会话帧均未改变新角色thinking或口型 |

共六场景通过；两次换角均断言新旧session不同，旧音频/结束帧以旧身份送进当前控制消息处理器，等待状态与口型不变。没有发送chat:user或audio:start；没有调用大脑、TTS供应商或打开麦克风。实际播放静音WAV，嘴形props由预设音量包络驱动，不能冒充真实语音声学对齐；实际core口型参数已有独立证据，本轮只断言模型props。

临时钩子仅观测现有WebSocket对象和消息类型，再通过浏览器本地MessageEvent向真实App处理器回放；不修改后端、不新增WS连接、不改变网络消息内容。finally正式恢复Hotaru，删除CDP新文档脚本并重载主窗口，最终Hotaru/idle/mouth=0/闭麦，window观测与回放辅助函数已不存在。重载也清除本地fixture气泡与临时状态。

## 诊断失败与修正

最初脚本在页面重载尚未创建#app时直接访问_vnode失败；增加空值检查。随后尚未启用Page域的文档脚本未可靠安装，角色/模型/会话就绪超时，未进入业务断言。通过独立新文档小探针确认先Page.enable后脚本可生效，修正诊断初始化顺序后回放通过。第一次失败后的角色恢复还暴露了诊断依赖固定等待的问题，现会等待调试台切换结束及实际主模型恢复，再移除钩子。上述失败不记为模型/TTS供应商故障。

诊断Python Ruff通过。无生产改动，不重复类型/构建或后端全量。此证据加强真实前端整合与双向身份隔离；不代替真实ASR/LLM/TTS整条链路、Hiyori真人打断、主观自然度、供应商TTFA或物理停声分位数。原目标继续，麦克风保持关闭。
