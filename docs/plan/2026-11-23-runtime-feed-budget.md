# Runtime 取消与语音投喂预算优化

## 成果与范围

本轮沿用现有 Runtime，先优化取消通知，再限制 VoicePipeline 翻译到合成的在途任务。固定 64 句、翻译受控挂起的压力场景中，实际生产函数的翻译任务峰值从 **64 降为 4**；解除挂起后全部 64 句仍按序交付，完成后活跃翻译归零。这是任务预算改善，不是云端首音频或实际停播性能结论。

基线提交为 `368c188`。开始本轮持续迭代时，工作区仅有前一切片的 RuntimeRegistry、契约和测试修改；保留这些改动继续验证。没有修改音色、供应商、角色配置、模型素材、用户数据库或前端，没有自动部署/重启服务。

## 实现与兼容

Goal：慢依赖或长回复时，不无限创建翻译和合成等待任务；停止时能回收本轮任务。

Scenario：长回复包含 64 句，翻译暂时无法完成；首句先就绪时立即交付，不等整批结束；用户中断后不继续投喂剩余句子。

Architecture Increment：仅在 `engine/yuiro/audio/__init__.py` 的 `_speak_impl._feed` 内加 4 项在途窗口。创建任务前等待容量，任意任务完成即回收并补位；仍保留合成并发 2、首句准入顺序、按 seq 交付、完成后 finish，以及取消后 join。选择 4 作为保守工程上限，用于两路合成加翻译预取，不声称它是全部 provider 的最优配置。

前一切片在 RuntimeRegistry 中并发分发取消：慢异步清理不再延迟其它 Runtime 收到取消。会话 generation 先失效、普通异常逐模块隔离、父取消继续传播；取消通知结束前回收子任务。close_session 仍顺序执行。100ms 慢清理替身的一次对照中，Speech 通知约 108.73ms → 0.20ms，全部清理约 108.76ms → 108.31ms；这说明通知不再串行等待，不代表当前正常钩子或物理停播有同等收益。

## 测试与对照

新增 `engine/tests/test_speech_feed_budget.py` 覆盖整段/流式来源、完成/中断、长回复有序无损、取消后归零，以及滚动补位：第一句已交付、第二到第四句仍挂起时，第五句可以进入窗口，不因整批等待制造新延迟。

`scripts/diag/runtime_feed_budget.py` 从 HEAD 与工作区分别提取真实 `_speak_impl`，在同一进程使用替身 Renderer/TTS 执行对照，不导入 main、不请求云端。证据：[任务峰值对照](runtime-feed-budget-evidence.json)。旧实现的新增预算测试先失败（峰值 64），修改后通过（峰值 4）。

根目录复跑诊断：

```powershell
. .\config\env.ps1
& .\.env-local\engine-venv2\Scripts\python.exe scripts/diag/runtime_feed_budget.py
```

测试在 `engine/` 加载 `..\config\env.ps1` 后运行：

```powershell
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/test_speech_feed_budget.py tests/test_tts_first_sentence.py tests/test_tts_stream.py tests/test_tts_streaming.py tests/test_fish_websocket.py tests/test_speech_turn_handoff.py tests/test_runtime_contract.py -q
& ..\.env-local\engine-venv2\Scripts\python.exe -m pytest tests/ -q -ra --disable-warnings -p no:cacheprovider --junitxml=../docs/plan/runtime-feed-budget-regression.xml
```

本轮完整后端回归 **1039 passed / 58.03s / 无 skip**，见 [JUnit](runtime-feed-budget-regression.xml)；新增窗口测试 5 项单独通过。新增测试和诊断脚本 Ruff 通过，`git diff --check` 通过。audio 模块全文件 Ruff 仍有既有的导入顺序、BLE001、S110、SIM102 四项问题，未借优化改无关代码，不宣称全仓 lint 清零。没有前端改动，不重复构建前端。

诊断脚本以当前 HEAD 为 before，提交后重跑需另行选取原基线，不能将已优化 HEAD 当旧版本。脚本只覆写同名证据文件，比较前先归档。

## 边界与后续

### 实际项目启动验证

2026-11-23 启动当前 Engine 与 Electron 开发界面，保持 Hotaru casual 和现有 Fish WS 配置。通过真实界面 sendText 发送固定无工具短句，经过实际检索、LLM、TTS、WS、解码和 AudioContext.start；前两次完整播放，第三次开始播放后调用既有 interrupt/stopPlayback。原始数据见 [实机记录](runtime-renderer-live.json)，复现入口为 `scripts/diag/runtime_renderer_live.py`（依赖 8200 Engine 和 9222 CDP，含真实云端请求，复跑会覆盖同名证据）。

两次正常样本首播放分别 8826.9ms、1660.4ms；第三次 1554.3ms 后开始播放，再停止，观察1.5秒新增 start 为0。此处仅证明该次本地停止后的观察结果，不证明所有取消竞态或后端任务取消完成。应用播放不等同物理声学首音，三次样本不构成 P95 验收。

Engine trace 显示首次检索约4562ms、检索后至模型首token约2887ms；第二次检索约80ms、随后约927ms至首token。正常两样本从文字答复到首音频接收约1256/558ms，音频接收到应用首start约38/7ms。监听器注册顺序使 decode_start 可能略早于记录的 receive，不把这几分之一毫秒误差当负传输耗时。当前证据优先指向冷检索和远端生成/合成等待，而非本地模块通信或解码；还需更多受控样本确认稳定分布。

Hotaru 模型已实际加载，结束时 modelReady=true、turnBusy=false、replyTtsBusy=false。未打开麦克风、未批准工具、未改配置；正常聊天会保留当前会话历史及既有事件记录。Engine 与 Electron 留在运行中供用户验证。截图确认模型显示，不代表听感或动态演出已经人工审定。

本次限制的是翻译到合成的在途任务，并未给 LLM 文本队列、manager 已完成音频缓存、renderer 预解码增加全链路预算。并发取消也不抢占同步阻塞代码，不为外部副作用提供回滚或清理 deadline。

DoD：受控任务峰值可重复下降、首句提前交付与有序无损不退化、两类入口取消回收通过、已有相关回归通过。真实 provider 的端到端 P50/P95、双角色听感和长时间稳定性不由本轮替身测试替代。下一切片应继续独立测量待发送音频容量和 LLM 句子通道，处理消费者退出/异常/取消后再加预算，不能直接把无界队列改为有限容量而让结束哨兵阻塞。

没有新增 Runtime、播放器或依赖。回退本轮 `_feed` 的窗口改动可恢复原投喂方式；取消广播切片可独立回退。不要用全仓回滚覆盖用户后续改动。
