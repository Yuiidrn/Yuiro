# 停麦与完整释放要有不同的生命周期

此前为修复停麦掐掉回复，输入stop与播放stopPlayback已经分开；但完整dispose仍缺少AudioContext.close。不能为补释放又让普通停麦关闭公共音频图，否则会回归到“用户关麦，角色突然闭嘴”。

现只有完整dispose设置终止标志、清除输出/输入/socket后关闭原音频图，并返回可等待、幂等的Promise。开始与入队拒绝终止实例，正在解码的任务保留既有epoch检查；无需重写播放器。关闭错误有模块日志，不输出正文/凭证。

测试直接编译生产composable：普通stop保留活动音频和口型，dispose一次关闭，重复不重关；迟到解码及外部入队不能新建资源。真实Electron六个实例进一步读到context.state=closed，取消/缓冲四场景仍正常。测试诊断先await生产dispose再检查，避免手工备用close伪装产品已释放。

当前验证是生命周期正确性，未测量堆内存下降比例，也未声称多小时压力稳定或声音自然度已通过。原始证据及剩余项见[计划](../plan/2026-11-10-voice-audio-context-lifecycle.md)。
