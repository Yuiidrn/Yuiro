# 辅助语音入口：日记连接所有权

Goal：日记换角/重连时，旧异步连接和旧socket事件不得污染新角色回应与播放。Scenario：getEngineSecret尚未返回即切换角色，或同角色旧socket在新连接后才close/message/error。

Architecture Increment：沿用现有connectionEpoch与独立日记音频取消队列，给每次connect分配新epoch、await后复核、回调校验socket实例；不重写日记业务，也不把独立日记音频并入桌宠主播放器。Tests：生产连接函数的乱序密钥返回、旧socket迟到事件、正常close清理及卸载失效；既有日记手势、类型/构建回归。DoD：竞态可复现且修复通过，明确真实麦克风与人耳未验证范围。

入口盘点：普通文本已复用_prepare_text_turn；官方媒体_reply_official_media只发送media:state，不合成语音，不能为了统一而让暂停/喜欢动作中断桌宠语音；日记diary:interact有独立request_id、audioEpoch与roleChanged取消，应保持独立。遗留builtin媒体直达存在独立文字朗读取消代码，但前端已不使用，不在本轮借机重写。

## 修复与验证结果

旧connect在await wsUrl前只读取connectionEpoch，返回后直接覆盖全局ws；旧onerror没有身份检查，同角色重连也复用epoch。现每次尝试先推进connectionEpoch，await后复核有效性，再创建并安装本次socket；所有回调同时检查epoch、disposed和ws实例。替换旧socket之前已更新归属，旧close不能清理新请求。正常close只清理一次cancelQuip，清除ws并安排重连。

日记音频队列还发现一个独立迟到结果：旧audio.play()在换角/取消后reject会覆盖新角色status。现错误提示也检查audioEpoch，旧失败只释放自己的等待；当前失败仍显示“语音播放失败，文字仍保留”。没有改request_id或音频播放协议。

三个生产源码专项通过：

- diary_connection_ownership_test.cjs：乱序密钥返回不会新建/覆盖新socket；旧close/error/message无副作用；当前消息与close正常处理；卸载后迟到密钥不创建连接。
- diary_audio_epoch_test.cjs：旧request不播放、旧play reject不污染新角色status、当前失败仍可见。
- diary_companion_test.cjs：Enter/Ctrl/Shift/IME、关闭回应开关与段落绑定保持原行为。

前端typecheck/build通过。实际新构建日记窗口在Hotaru→Hiyori→Hotaru后均connected，预期构建文件diary-D1sbwnTb.js匹配，未发现既有窗口/草稿；未输入、保存、朗读或采麦。原始证据[diary-role-connection-live.json](diary-role-connection-live.json)，脚本遇到既有窗口或草稿会跳过切换而保留内容。临时窗口已关闭，Hotaru已恢复。此实机冒烟证明正常连接/正式换角，受控异步竞态由生产函数专项证明；不把两者混成“真人已测全部竞态”。

本轮未改后端，沿用1000项回归基线，不宣称重跑全部后端；新增诊断Ruff和git diff --check通过。未改主桌宠音频、音乐播放归属、角色配置、背景或捕获保护。仍不替代Hiyori真人麦克风和整体自然度验收。
