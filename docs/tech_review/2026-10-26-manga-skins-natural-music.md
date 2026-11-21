# 漫画轮廓、角色皮肤与自然语言收藏复盘

对应 [验收报告](../plan/manga-skins-and-natural-music.md)与[样式规范](../UI&motions/character-ui-style-reference.md)。

## 消除框体/尾巴拼接

旧版是圆角矩形叠加另一张尾巴SVG，透明度和交界描边不统一。新`mangaBubble`在实际DIP坐标里构建一个闭合路径，连接圆角框和两条弯曲尖尾边；ResizeObserver根据实际框尺寸重算，避免viewBox拉伸导致线宽变形。白色外缘和内线重描同一路径，整组应用alpha，无尾巴叠加色块。长文限制内容层高度并滚动，背景层不参与布局。

装饰SVG与Markdown区域分离；Markdown继续经过既有安全处理，花卉不能通过LLM内容插入。关闭按钮默认隐化，hover/focus显现。单曲线模式不绘制闭合框/花卉，原穿透连接窗不变。

## 皮肤与明暗分开

`skin:auto|cream|lily`只决定角色配色和装饰，不混入`theme:light|dark|auto`、字号和布局。`resolveSkin`统一映射角色，`panelAppearance`提供面板tokens，CSS负责调试台与输入栏，功能岛保留原透明度参数。

一个同步细节：原`localStorage.setItem`只通知别的窗口，发起切换的窗口自身不能指望storage事件更新。`setCharacter`显式更新同窗口响应式role，其他窗口沿用VueUse存储同步；DevApp监听配置角色。皮肤在共享effectScope初始化，因此设置页卸载不会停止主题同步。

白花/星光是本地原创细线装饰，不依赖图片下载，无动画循环，无交互命中。窄窗隐藏标题装饰，不以低对比浅色替代正文。

## “这首”不能由LLM猜ID

自然语言验收前发现schema要求song_id，对话只说“喜欢这首”时模型不得不从历史候选中选择。修正为可省略ID，服务端按现有`identity + playback_id + epoch`取当前归属歌曲，再核对客户端ID。显式错误ID不被修正成另一首；无归属/角色不符仍拒绝。

通过真实模型实际发送“喜欢这首”“取消喜欢”“推荐几首歌”，确认工具选择无需用户指定函数名；结果卡在既有状态轮询后同步。重复工具调用由既有成功去重阻止二次toggle，收藏仍用目标布尔值，外部副作用不安全重放。

## 回归方法

`manga_ui_acceptance.py`仅本地显示/真实窗口，负责皮肤自动/固定、夜间、长文和截图；`natural_music_acceptance.py`使用真实Agent和官方客户端，finally恢复Monody收藏及原角色。后者内部用数字ID核验，但用户输入没有数字ID/工具名；不能把内部验收断言混为用户必须输入的命令。

单测新增“这首”默认解析、跨角色拒绝和schema可选性；前端检查覆盖三种皮肤选择、有界设置、连续轮廓和来源窗不可发音乐控制。真实语音TTS听感不在本轮新增验收范围，不把聊天输入验收写成麦克风ASR验收。
