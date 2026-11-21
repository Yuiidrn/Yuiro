# 可视化角色演出工作台：实现与参考取舍

## 设计选择

原外观页把模型、映射表、互动参数纵向堆叠，用户需要从文件名猜动作。现在由 AppearanceStudio 组织“先看效果，再编辑行为”的左右工作台，Live2DCanvas 仍是唯一渲染实现。动作、表情、Agent搭配都适配现有 AvatarIntent，避免预览另外维护一套动作播放器。

模型选择分为 selected（预览）和 current（真实配置），普通点击只改变 selected。显式应用才调用角色配置保存与 setPetModel；桌宠试演亦需主动开启，并带角色/模型上下文。收藏按角色+模型存储，缩略图按模型+资源标识缓存在内存。异步请求带版本、离页标志和批次编号，解决切模型后旧结果回填。

缩略图采用单舞台串行播放、450ms后实际画布裁剪。相对每张卡一个WebGL实例，这样能控制GPU上下文数量；代价是缩略图不是完整动画，批量生成时舞台会依次试播。显式按钮让用户选择是否支付这段工作量，分页控制每批最多12项。预览禁用自主待机和轮廓采样，保留SDK基础呼吸/眨眼，不触发桌面点击穿透。

失败由Canvas事件反馈到工作台，退出加载态并禁用应用；重复点击单击池加入保持幂等。纯表情没有可解析动作时，不出现加池按钮。未识别语义保留待分类，避免错误演出含义。

Agent重复表演合并放在既有AvatarRuntime内：先处理代际、到期，再比较当前名称及实际映射。最初仅比较名称会挡住同名映射热更新，已有热重载测试发现此回归，已改为比较具体表情、动作及槽位后再合并；全量956项通过。这是复用Runtime约束的局部增强，不引入新的Agent循环。

## 源码落点

- shell/src/renderer/src/dev/components/AppearanceStudio.vue：目录、舞台、分类、收藏、缩略图、应用边界。
- shell/src/renderer/src/avatar/catalog.ts：可解释的语义分类与资源标签。
- shell/src/renderer/src/components/Live2DCanvas.vue：ready/failed、画布裁剪和预览模式。
- shell/src/renderer/src/dev/components/PerformanceEditor.vue：本地预览事件与目录刷新，保留原保存逻辑。
- shell/src/main/index.ts、shell/src/preload/index.ts：模型扫描的名称/作者/隐藏元数据。
- engine/yuiro/avatar/runtime.py、tools/avatar_tool.py：重复演出合并及模型可理解的工具说明。

## 开源调研与个性化接入

查看了 [Haneoka](https://github.com/haneoka-gakuen/haneoka)、[bangdream-live2d](https://github.com/haneoka-gakuen/bangdream-live2d) 的项目组织与播放器定位；Haneoka package.json 展示了资源/工具与播放器包的划分。没有完成其播放器深层源码审计，不声称复刻其模型浏览器。

进一步阅读 [bandori-desktop-pet 的动作数据](https://github.com/TTZW1001/bandori-desktop-pet/blob/main/renderer/motion-data.js) 和 [renderer](https://github.com/TTZW1001/bandori-desktop-pet/blob/main/renderer/renderer.js)，其分角色反应池、触摸语义、鼠标/拖动节奏与冷却值得参考。本次吸收的是“按交互用途组织资源、先保障动作归属与节奏”的方法，结合本项目已有Manifest、两角色隔离、Agent映射与主题实现。

没有下载外部角色模型、复制外部源码或引入运行依赖；也不把更多随机动作直接灌进待机，这会重新产生注视与动作争抢。后续可在完成角色资源人工审定后扩展部位反应、注视回应与情境组合，继续走现有优先级和代际仲裁。

## 样式约束

沿用Hiyori奶油/Hotaru白花主题变量；模型图卡主导选择，资源卡展示真实截图而非装饰素材。左舞台保持可见，右侧按任务分区；顶部图卡紧凑横排，缩略图不过度抢占模型舞台。分类与资源名称并列，保留精确文件依据；未采样资源明确显示“点击动态预览”。更窄窗口允许单列，常规桌面优先左右对照。

验收与边界见 [交付记录](../plan/appearance-studio.md)。


2026-11-09修正：此前裁剪混用了布局时保存的client包围盒与截图时的canvas位置，页面滚动/吸顶后产生偏移。新previewCrop全程使用renderer局部坐标，独立换算X/Y像素尺度并等比例留边。缩略图加载先等SDK动作资源，再采样；IndexedDB异步缓存与当前页自动补缺降低重复生成成本，错误旧图由v2键隔离。该缓存按意图映射区分，不包含底层素材文件内容摘要；原路径原文件名直接替换素材后的自动失效仍是后续优化项。实机复验缺口见交付记录最新段落。


续验补强：自动缩略图任务也会写入同一舞台，必须参与“用户操作优先”的取消协议。手动动作和高级Agent试演统一在入口取消延迟任务并更新work批次；停止也取消未开始或等待加载的任务。新增执行当前SFC真实函数的调度回归，证明取消的不只是最终截图写回，也包括后续动作应用的有效性检查。实机环境现有Electron未暴露CDP，本轮不将组件测试称为真实视觉验收。


真实UI补验已完成：最新构建下Hiyori13动作与Hotaru67动作逐页自动生成/缓存加载，期间滚动到页底，80张真实PNG均检查人物上下界，并人工审阅第一页联系图；原client/local混用裁剪错误已获得真实浏览器证据。实际调试台重开后也能读缓存，未覆盖角色配置。脚本与结果见计划最新段落。此结论仅覆盖工作台缩略图及预览配置隔离，不扩展到桌宠注视自然度或整段动作导演效果。
