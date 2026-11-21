# Fish HTTP连接复用与WebSocket验证

旧Fish适配器在每句的stream/post范围新建并关闭AsyncClient。HTTP音频虽提前分块交付，跨句仍丢掉连接池。本次将无角色状态的HTTP传输提升为事件循环内共享：正常stream退出只关闭本次响应，取消亦如此；引擎lifespan退出在finally关闭池。

共享的是连接，不是音色或安全设置：认证头、模型、reference_id、语速、latency仍逐请求提供，安全密钥每次重新读取。缓存角色或调试台临时Provider因此可以借用同一传输，而不会因局部请求结束关掉其他角色/请求的池。不同事件循环单独建池，避免跨循环借用已绑定连接。明确注入的诊断client由诊断拥有和关闭。

池上限8条连接/4条保活，60秒保活；连接/池等待10秒、读取沿用60秒，不添加自动重试或切换音色。测试覆盖多Provider共用单client但请求参数/密钥独立、取消A而B及后续请求继续、关闭幂等、循环隔离。生产流式/整句既有专项也通过，后端全量1014 passed。

有界真实实验通过httpcore trace只记录连接事件次数和时间，不记录连接参数、头或密钥。暖请求确认为0次TCP/TLS，直接证明复用发生；首块快慢仍可能受服务器排队等因素影响，不能按五个样本给出因果提速百分比。

官方WS协议最小验证采用MessagePack start/text/flush/stop，显式携带现有model/音色和PCM输出。两次成功，其中分段模式收到第一段音频后才发送余下文本，证明不必先提供整个回复。该实现仅在scripts/diag内，没有接入生产或改变HTTP开关；新WS握手约0.93–0.96秒，现有样本没有胜过暖HTTP。

官方参考：[HTTPX异步连接生命周期](https://www.python-httpx.org/async/)、[Fish官方索引](https://docs.fish.audio/llms.txt)、[Fish WS协议](https://docs.fish.audio/api-reference/endpoint/websocket/tts-live.md)。索引所列独立asyncapi.yml地址实取404，使用协议页面内嵌规范核对，未据错误链接猜事件名。

当前选择：部署HTTP复用，保留原可用网络路径；WS作为实验分支。后续如验证每轮LLM开始时提前建立WS、持续送入首句/译文，应继续沿用generation取消、角色归属和音频序列规则，不得让旧轮余音复活或换音色隐藏超时。
