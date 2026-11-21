# 主语音播放器完整释放

Goal：组件完整卸载后释放AudioContext，迟到回调不得重建音频资源。Scenario：播放/解码/开麦准备在途时dispose，或多次dispose；普通stop输入仍必须保留输出。Architecture Increment：补现有composable的终止标志与可等待幂等dispose，不另建播放器。Tests：生产组件卸载关闭一次、迟到解码/调用不重启、stop不关闭输出；真实Electron多个实例释放后context均closed。DoD：专项、类型/构建及限定范围实机证据落盘，未测声学自然度不冒充完成。

## 实施与验证

useVoiceInput此前dispose只停播、停采音和关socket，没有显式关闭AudioContext。本轮补disposed标志和closingAudio Promise：先停止全部节点和输入，同步解绑socket归属，清除audioCtx引用，调用原Context.close并返回可等待Promise；重复dispose复用同一结果。卸载后enqueue拒绝迟到帧、start拒绝重新开麦，正在解码的旧任务继续沿playbackEpoch作废。

stop()语义保持不变：只关采音，不能因为用户关麦就掐掉已经在播放的文字/语音回复。完整dispose才是终止，不可当普通停麦调用。

生产组件专项voice_input_lifecycle_test.cjs验证普通stop不close、完整dispose close一次、重复dispose幂等、卸载后迟到enqueue/start不创建资源、解码尚未结束时dispose后不创建source。既有stream排期、播放回执专项通过；前端typecheck/build通过。

真实Electron/WebAudio复验[avatar-stream-rebuffer-browser-live.json](avatar-stream-rebuffer-browser-live.json)六个隔离实例（两角色夹具×缓冲阈值/尾块/取消），每例新增contextsClosed=true，实际context已closed，等待期间口型和收尾仍通过。另[avatar-http-stream-browser-live.json](avatar-http-stream-browser-live.json)四场景自然结束/打断复验通过。诊断已改为await dispose再检查，不能以诊断自己的备用close掩盖生产dispose遗漏。

本轮未改后端，沿用1000项基线；新增相关Python诊断Ruff、git diff --check通过。未请求真实TTS或采麦，六个实例关闭不能外推为多小时内存压力已通过，也不能凭静音fixture判音质或自然度。

人工验收已请求Hiyori真实麦克风/打断及固定待机自然度的准备情况，尚未收到答复；不开麦、不自动替代为合成输入后宣称通过。原Goal仍保留这些人工项、动态语义审定及端到端分位数。
