# Fish持续文本流接入复盘（2026-11-11）

## 目标与复用边界

此前独立脚本证明提前握手可行，本轮将能力接入真实配置、VoicePipeline和文字朗读。采用单轮session适配现有Runtime：`engine/yuiro/audio/fish_websocket.py`负责Fish协议，`fish.py`暴露可选传输和单次合成接口；队列、播放租约、generation、RMS口型、WebAudio排期继续复用，不新增一套调度或播放器。

HTTP连接池可以跨请求复用传输，但WS上下文不能跨角色或回合共享。每轮session冻结音色/模型/速度，加载当前安全存储密钥，使用start/text/flush/stop输入和audio/finish输出。接收PCM16/44100Hz，经原WavStreamSplitter变成480ms WAV及最后尾块，一轮统一stream_id；前端已有连续播放与重新缓冲协议无需更换。

协议依据：[Fish文档索引](https://docs.fish.audio/llms.txt)、[实时TTS协议](https://docs.fish.audio/api-reference/endpoint/websocket/tts-live.md)。实现以真实服务验证为准。显式声明msgpack依赖及websockets>=15，使用当前已安装依赖，没有下载新运行环境。

## 生命周期和关键修正

语音入口在等待分句之前连接，独立生成器依次做speech_body清理和原OutputRenderer语言转换，每次转换前后检查所有权，再经TTSTaskManager适配器输出音频。文字入口将预连接桥接任务放入既有_reply_speak_tasks集合，由现有新消息、打断和角色切换取消路径管理；文本目前仍是完整回复交付后启动朗读，提前的只是握手。

创建session必须放在受管理任务内部。否则任务刚创建就被取消、尚未进入函数体时，提前在外部创建的连接无人回收。桥接任务通过Future领取本轮回复，取消后的Future不会触发旧回复的备用朗读。

输入与接收并发，但必须竞争检查输入任务异常：只等socket.recv会掩盖翻译失败，直到网络超时。显式关闭异步输入生成器；取消时cancel并join输入/接收/连接，幂等close任务通过shield允许清理完成。主语音finally中的状态与锁释放再包一层finally，确保关闭连接时再次取消也不遗留忙状态。文本侧生成器也显式aclosing，generation变化时立即关闭内层流，不等垃圾回收。

不捕获吞掉CancelledError；其余网络错误只记录异常类型，避免把鉴权信息写入日志。已经输出部分音频时不重发整句，不静默转HTTP或替换音色。协议依赖在provider构造阶段预加载，避免首句热路径冷导入。

## 配置与验证边界

新增tts.fish_transport=http|websocket，通过既有角色配置和调试台Fish字段过滤展示。新回合生效；持续文本流依赖segment_streaming，关闭时仍支持单次完整WAV。日记/试听等单文本调用可走WS单次合成，不获得主语音入口的提前生成握手收益。调试测试响应增加实际transport，防止误把HTTP成功当WS成功。

后端1032项全量通过，前端typecheck/build通过。测试使用实际生产函数及可控socket，覆盖首块提前交付、异常竞争、输入关闭、任务未启动即取消、generation翻译中变更、角色配置保存和Hiyori不变；不会以只测协议辅助类代替运行时集成。

真实VoicePipeline使用真实LLM、翻译和Fish，固定ASR替身并捕获音频回调；首块4283.9ms包含前序生成/转换，样本取得后才完成协议导入预加载调整。实际调试配置API保存WS、TTS测试API返回WS完整音频2548.7ms，随后完整恢复配置。前者不是实际声卡首音，后者不是首块指标，不据此宣称波动已解决。

证据与数值见[验收报告](../plan/2026-11-11-fish-websocket-integration.md)。当前Hotaru恢复HTTP、Hiyori配置未变、桌宠idle且闭麦。没有新增真人听感、多小时稳定性或P95结论；下一步应做受控对照和实际播放时间线，再决定默认值，而非扩大架构改造。
