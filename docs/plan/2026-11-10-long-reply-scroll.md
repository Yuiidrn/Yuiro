# 长回复隐藏滚动与正文裁切修复

## 场景与原因

用户反馈长故事回复只能看到前半部分，需要不显眼的滚轮下拉。实际检查发现正文原本已经有`overflow:auto`，但曲线窗口`DialogueLineApp.vue`的非scoped样式将`html/body/#app`全部设为`pointer-events:none`。`detached/main.ts`静态导入两种窗口组件，导致该CSS也进入回复窗。真实浏览器命中测试返回html而不是正文，注入的滚轮事件没有进入正文区域，scrollTop始终0。

另一个问题是高度限制分别施加在正文和花饰上，没有以整个框体为预算，在屏幕可用区域较小时可能由原生窗口裁掉内容。

## 实施

- 为独立窗设置`data-detached-kind`，曲线透明区域的pointer-events规则只作用于connector；曲线SVG仍不接收鼠标，原生曲线窗点击穿透保持。
- 整个回复框使用受限高度的纵向flex布局，正文`min-height:0`并允许纵向滚动，底部花饰固定留位。最大高度同时受调试台参数和屏幕可用工作区约束。
- 隐藏正文滚动条，保留鼠标滚轮、触控板及已有tabindex键盘滚动。滚动不冒泡影响外围区域；保留浏览器默认滚动，不加入逐帧自定义滚轮动画。
- 选歌/来源卡的滚动条风格保持原设置；修复共享根节点pointer-events污染也恢复这些窗口的默认命中条件。

## 验收

前端typecheck/build通过。真实独立回复窗使用30段Markdown的临时UI样本，未调用LLM、未写入会话/记忆、未改正式样式偏好：

- 改前相同流程滚轮无事件，命中html；改后命中实际段落，收到deltaY=300滚轮事件，scrollTop从0变成300。
- 正文可视350px、总高度3134px；滚到底部后“【全文结束】”完整可见。
- 正文底部356px，花饰区域从356px开始，窗口高400px；文字不被花饰覆盖或窗口裁掉。
- computed scrollbar-width=none。测试结束重载原桌宠renderer以撤销临时展示，未新建桌宠实例、未取消捕获保护。

数据：[result.json](long-reply-scroll-artifacts/result.json)。截图：[顶部](long-reply-scroll-artifacts/top.png)、[底部](long-reply-scroll-artifacts/bottom.png)。检查使用CDP浏览器滚轮事件，未声称Windows原生鼠标SendInput或所有DPI/多屏组合均已复验。

## 连续任务状态

Hotaru真实打断修复后已获用户确认，详见[本轮实录](2026-11-10-hotaru-barge-in-review.md)。用户随后反馈Fish首句返回波动，仍在排查：当前日志显示Hotaru中文内容逐句转换为日文约0.9–2.9秒，Fish完整HTTP响应从不足1秒的无音频短片段到数秒长句差异较大；每句新建HTTP客户端、异步翻译完成顺序与两路合成信号量竞争需进一步分段测量。尚未以更换音色、关闭既定日语或缩短故事来规避问题，也未宣称首句延迟已修复。
