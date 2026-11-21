# 回复窗滚轮失效：共享入口中的全局CSS污染

`detached/main.ts`静态导入DetachedApp和DialogueLineApp，选择其中一个mount，不能阻止另一个SFC的全局CSS进入共享构建。旧版对白曲线组件对html/body/#app设置pointer-events:none，回复窗继承了该值。截图看起来正常，但document.elementFromPoint落到html，正文接收不到真实浏览器滚轮事件。仅增加overflow:auto无法修复这个命中问题。

本次入口在mount之前写入data-detached-kind；曲线组件根CSS使用html[data-detached-kind='connector']限定，SVG规则改为scoped。原生connector窗setIgnoreMouseEvents不变，装饰SVG仍不参与命中。

ReplySurface的高度预算移到整个frame，用flex纵向布局、正文min-height:0以及花饰flex-shrink:0实现可缩正文区；独立窗口传入工作区高度上限。正文scrollbar-width:none、webkit scrollbar隐藏；仍使用浏览器默认滚轮滚动，wheel.stop只阻止向外围冒泡，没有preventDefault和额外动画。键盘region/tabindex保留。

真实构建的独立回复窗验证记录在[验收文档](../plan/2026-11-10-long-reply-scroll.md)：同样300px滚轮输入，修复前无事件且scrollTop=0，修复后收到wheel并到300；30段Markdown滚到底，末段完整显示且位于花饰上方。截图为自身renderer捕获，捕获保护未关闭。CDP输入不等于Windows原生滚轮验收，不扩展为所有多屏/DPI组合通过。
