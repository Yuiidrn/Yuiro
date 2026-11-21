# 当前候选说话中正式换角验收

Goal：验证前几轮取消/身份修复在真实角色切换时能够一起工作。Scenario：实际WebAudio正在播放时通过调试台正式角色选择切换，两个方向各观察；页面不刷新，最终恢复Hotaru。

Architecture Increment：无生产改动。诊断临时记录AudioBufferSourceNode.start/stop元数据，调用原函数，不改变音频；结束恢复原型。Tests：先确认源角色真实speaking与活跃音频时钟，再切换；检查旧节点停止、新模型路径、口型归零、idle、动作占用释放、麦克风关闭与两角色配置sections一致。DoD：限定范围的原始证据和外部失败均保留，不用刷新消除残留，不把节点stop时间称为声学停声。

## 首轮原始结果

见avatar-midplay-current-live.json。Hiyori→Hotaru已在原页面上观察旧节点stop、新角色正确、mouth=0、idle、until=0；配置一致。反向尚未取得有效音频：Fish当次返回ConnectError，未切换其他音色或自动重发原句。诊断最后记录No active audio observed before timeout并恢复Hotaru；此失败不记为反向通过，原记录不覆盖。

只读非计费连通性检查见avatar-fish-connectivity-readonly.json。该机没有代理环境变量，但Windows系统代理指向127.0.0.1:7890。单次并发检查中trust_env=True请求openapi头部返回200（1788.4ms），trust_env=False直连ConnectTimeout（5023.5ms）。这只证明当时的连接路径表现，不证明代理因果、TTS授权或服务持续健康；未改系统代理、provider路由、密钥或音色。

原任务已终止，随后仅补一次反向真实测试，单独写avatar-midplay-current-reverse-live.json；不重复正向样本，不用后续成功覆盖第一次失败。结果待本轮任务结束后补录。

## 反向补测与最终结论

补测完成：[avatar-midplay-current-reverse-live.json](avatar-midplay-current-reverse-live.json)。Hotaru实际WebAudio时钟已进入音频内部100ms以上、presence=speaking时发起Hotaru→Hiyori；原页面仍保留诊断对象，sameDocument=true，没有页面刷新。观察到旧source.stop成功，所有记录的旧节点均停止或已自然到达结尾；新模型路径为Hiyori、mouth=0、presence=idle、until=0，mic关闭。Hiyori及最终Hotaru配置sections比较一致。

正向原始记录另外从既有音频图元数据补核对oldNodesQuiescent，记为postRunRawChecks；没有重新调用供应商。两方向现在都有当前候选的真实文本朗读中正式切换证据，首次反向ConnectError仍作为外部失败留在首轮文件。

| 范围 | 结果 |
| --- | --- |
| Hiyori→Hotaru，正在播放 | 原页面停止旧节点，新模型/零口型/idle/释放占用通过 |
| Hotaru→Hiyori，正在播放 | 首次Fish连接失败未测成；只读连接检查后独立补测通过 |
| 页面刷新 | 两方向观测期间均未刷新，排除刷新替代清理 |
| 角色配置 | Hiyori、Hotaru前后sections一致 |
| 终态 | 恢复Hotaru，模型正确、mouth=0、idle、until=0、mic关闭 |
| 主观听感/物理停声 | 未新增人工确认，节点stop与音频图静默不等于声卡停声P95 |

本轮只新增诊断与证据，未改生产代码；新增诊断Ruff、git diff --check通过，沿用后端1000项和此前前端类型/构建基线。没有改路由、配置、模型名/音色、捕获保护或背景。整体自然交互Goal仍保留Hiyori真人麦克风/打断、主观自然度、全部资源语义及真实延迟分位数等未完成项。
