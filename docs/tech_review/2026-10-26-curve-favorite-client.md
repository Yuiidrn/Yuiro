# 单曲线紧凑布局与客户端收藏、日推技术复盘

日期：2026-10-26。对应 [验收报告](../plan/curve-and-client-favorites.md)。

## 曲线过长的原因与局部修正

原先单曲线只复用了气泡的高位 `anchorY`，起点却是资源嘴部，导致垂直跨度拉长。增加 `speech.lineRise` 与 `lineBend`，主进程按嘴部比例计算文字位置；预览通过 `dialogueOffset` 使用相同算法。保留 `placeDetached` 的模型矩形保护、屏幕边界和多面板避让，不靠裁断连线伪装缩短。

涉及 `shell/src/shared/{uiAppearance,dialogueLine,detachedUi}.ts`、`main/detachedUi.ts`、`App.vue`、`UiScenePreview.vue`、`DetachedUiSettings.vue`。新偏好缺省补齐，旧闭合气泡 anchorY 不变。曲线窗口仍永远忽略鼠标，无引擎连接或控制权限。

## 收藏：目标状态和一次写入

`native/netease_client.py` 的当前歌曲投影增加 `liked: boolean|null`：只识别唯一可见的 `like_number` / `likenumber_red`，隐藏副本不能参与。写入前核对精确ID，且在单个客户端JS回合再核对当前ID与目标状态后点击固定图标一次。

真实客户端存在明显异步延迟，初次2秒读取仍可能是旧图标；一次30秒观察窗也出现未确认后才更新。不能把短等待后未变化当作“写入失败，可以再点一下”。最终方案最长60秒只重读，连续两次目标状态才成功，超时返回未确认。重读断线可重建已核验连接，但绝不自动重发点击。

`official_client.control` 复用既有播放 `_lock`、epoch 和 `_same(identity, playback_id)`。收藏任务以 shield 排空单次已发出的写入和读回后才释放锁；外层取消仍向上传播，不把外部账号修改假装成可以撤销的本地任务。角色release等待在途操作，旧epoch结果不能回到新角色。人工换曲即时解除归属，未控制新歌。Agent工具声明外部副作用，不安全自动重放。

结果卡只展示已知收藏状态，动作经过 `detached:action` 的合法窗口sender、key和有效playback校验，壳层再发送角色/版本/session/playback_id，Engine继续复核。来源卡和连线窗不能发收藏控制。按钮等待期间禁用；Agent和UI使用同一NativeBackend路径。

收藏是平台账号共享数据，不能随角色切换复制或恢复账号全部收藏。验收的恢复仅针对用户授权的Monody测试操作。

## 日推：导航与数据投影，不接管播放队列

固定 `#left_nav_recommend` 导航，再点击 `#dailyRecommendCard .title` 打开详情，避开“播放全部”按钮。数据只取 `page_pc_daily_recommend` 内的 `cell_pc_songlist_song`，严格 `s_ctype=song` 和数字ID；名称/歌手走固定子节点。只输出白名单，不导出账号store、cookie或推荐算法参数。

两次列表稳定后从当前已加载最多40首中抽取最多6首，`source=netease_client_daily`、`played=false`。不宣称是完整分页列表，不把“随机候选”混为私人FM或队列随机模式。结果卡点选复用现有精确ID播放桥。

`netease_recommend` 注册为客户端适配器；旧CLI/API推荐实现保留但不走日常调用。每轮音乐提示同步为“推荐展示，不自动播放；收藏需明确意图和有效归属”。新增 `/推荐` 显式UI消息复用认证的 `media:search` 与generation/角色worker，无第二个音乐通道。

## 验收经验与技术债

- 前端源码HMR会终止正在执行的Agent链路。一次推荐验证因此失效，不能把重连后截图当成功；冻结源码后完整重跑通过。
- 独立窗口是懒加载，诊断脚本需等待窗口ready而非假定600ms必创建完毕。
- 双角色真实收藏/恢复和Agent日推通过；单测覆盖幂等、未知ID、手工切歌、取消排空、角色竞争、无回退。完整测试统计及原始观测见验收报告。
- 此适配依赖客户端当前DOM，升级后应复测。UI状态读回不是独立云端事务API；本轮没有新增账户接口或逆向调用收藏API。未来可增加更明确的“读取中/写入未确认”诊断状态，但不得在未知结果下自动toggle重试。
