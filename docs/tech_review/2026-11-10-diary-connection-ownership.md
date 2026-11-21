# 连接epoch要覆盖异步建连和socket实例

日记是独立窗口/独立音频队列，不能为了主桌宠输出统一而强行共用播放器。它需要的是同样的所有权原则：旧角色的异步结果不能变成新连接的状态。

原connect先记录connectionEpoch，然后await异步密钥，返回后直接赋ws；换角期间旧请求迟到会覆盖新ws。同角色重连不推进epoch，旧socket的close/message也可能通过检查，onerror更没有检查。现每次connect分配新epoch，await后复核，回调再同时验证socket实例；新归属确立后关闭旧socket，避免同步/异步close反向清理新请求。

音频也存在类似边界：排队前检查audioEpoch不足以保护audio.play Promise的迟到reject。现在错误提示只允许当前epoch写入，旧失败仍resolve自己的等待以免阻塞队列。没有吞当前失败，没有把取消伪装成播放成功。

生产函数抽取测试使用可控密钥Promise和socket事件，覆盖密钥乱序、旧close/error/message、正常清理与卸载；生产onMessage测试覆盖旧音频拒绝。真实新构建窗口再经正式角色选择验证两角色都能正常连接。分别记录可控竞态与真实窗口的证据范围，见[验收报告](../plan/2026-11-10-diary-connection-ownership.md)。

官方音乐控制入口仅回media:state，没有回复朗读，不应让暂停/喜欢之类操作无故停止桌宠说话；废弃builtin入口不因本次核对恢复到前端。保持现有Runtime与播放器归属，比为“统一”增加不必要的共享状态更符合隔离目标。
