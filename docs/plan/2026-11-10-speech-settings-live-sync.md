# 调试台语音设置与运行中桌宠同步

Goal：调试台保存/重载插话打断与回复TTS开关后，已运行桌宠不必重连或重新开麦即同步镜像。Scenario：运行中从另一窗口改开关，或角色切换/多次回读乱序；旧响应不得覆盖当前角色。

Architecture Increment：复用同源窗口storage通知，只发角色与随机变更标识，不存设置值/密钥；引擎配置仍唯一真相。复用composable打断读取，给读取加请求序号/角色/存活检查。Tests：通知角色过滤、解绑、乱序读取与卸载、实际两窗口保存/恢复及角色隔离；不开麦，不用模拟输入冒充真人打断。DoD：专项、类型/构建和限定范围实机记录，原配置恢复。

## 实施与证据

原调试台保存/重载后没有通知已运行桌宠回读。现api.putConfig在vad/tts保存成功、reloadConfig成功后发送speechSettingsSignal；跨窗口通知只有characterId和nonce，收到匹配角色的通知才向引擎回读。失败写入、非语音配置和外来角色不通知/不响应，不在localStorage保留第二份设置值。

App的重复打断读取改为复用useVoiceInput.loadBargeIn；打断及回复TTS读取均增加请求序号、角色与组件存活检查，旧HTTP结果不能回写新状态。快捷开关写入捕获角色/revision、带现有鉴权头，await密钥与响应后重新确认归属，旧操作不写当前UI提示或发新通知。

补齐反向同步：聊天坞保存成功也通知；DevApp只在没有未保存草稿、没有保存/换角中的情况下load回读，不覆盖编辑中的草稿。回读不再次通知，避免循环。角色切换与Session/Generation协议没有改动，storage通知是前端刷新提示，不是引擎Runtime事件。

生产专项：speech_settings_signal_test.cjs验证角色过滤、坏通知、解绑、随机标识、API成功保存/重载才通知，通知无设置/密钥；voice_settings_race_test.cjs验证打断读取乱序、跨角色及dispose拒绝；speech_quick_toggle_test.cjs直接执行App快捷保存与TTS读取，验证旧角色密钥/响应不能写回、读回乱序与卸载保护。既有Avatar/输入生命周期专项、前端typecheck/build通过。

实际窗口证据[speech-settings-live.json](speech-settings-live.json)：初始Hotaru、barge=false、reply TTS=true；通过真实Dev Pinia store→API分别开/关两项，菜单四次同步；通过真实聊天坞快捷按钮再切换两项，Dev store四次同步。设置变化期间sameDocument=true，未刷新/重连。另在无真实草稿的测试环境模拟hasDraftChanges=true，确认外部更新不覆盖Dev已读值；清标记并显式回读后恢复。不是用用户正文作测试，也不声称验证了所有草稿合并冲突。

finally恢复初始两个值，整个config sections JSON比较一致；恢复菜单/聊天坞原开闭状态、删除临时诊断变量。没有LLM/TTS服务请求或麦克风采集，不能把菜单/ref同步当成“真人开麦中的实际打断已通过”；开麦门控源码使用同一个实时ref，人工声学复验仍在总体审计中保留。

诊断首轮曾假设聊天坞已展开，因控件未挂载而退出，尚未写配置；修正为通过现有BracketMenu的chat action展开后才测，未把该诊断错误当成产品空白窗口故障。最终成功证据保留八次变化及草稿标记保护。新增诊断Ruff、git diff --check通过；后端未改，沿用1000项基线，不伪称本轮重跑。
