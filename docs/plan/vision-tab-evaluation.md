# 视觉 Tab 调研与接入评估

日期：2026-10-27。状态：方案，尚未实现视觉 Tab、调用图片接口或打开摄像头。延续现有 Runtime，局部适配；不启动新的架构演进主线。

## 建议结论

分开实现两种能力：用户主动发图，由视觉语言模型理解；用户主动开启摄像头后，在本地检测在场、脸部朝向和动作，用于克制的角色反应。不要把持续摄像头视频默认上传给大脑，也不要把“检测到脸”称为“识别出是谁”。

百炼当前官方视觉示例已使用 `qwen3.8-max` 和 OpenAI 兼容 `image_url` 消息，因此优先验证现有供应商能否复用，而不是先增加另一套大脑配置。账号、地域、具体部署的能力和费用仍需独立小样本验证，本轮没有调用验证。[官方图像与视频理解文档](https://help.aliyun.com/zh/model-studio/vision)

## 当前代码与差距

| 当前实现 | 复用方式 | 待补内容 |
|---|---|---|
| `engine/yuiro/agent/__init__.py` 文本/工具消息 | 保留 Provider、工具循环与取消契约 | 增加有类型的图文消息和供应商能力检测，不能直接拼接 Base64 到文本 |
| `shell/src/shared/engine-protocol.ts` | 仍作跨端协议来源 | 定义图片引用、大小/类型约束、取消与错误事件 |
| Session / Generation / Cancellation | 复用身份与取消传播 | 换角、取消后旧识图结果不得进入聊天、记忆或 Avatar |
| Artifact Store / ContextEngine | 原图短期引用，正文只放必要摘要 | 确认大小上限、生命周期及本地删除，不把整帧写入 EventLog |
| AvatarIntent / 现有角色表演配置 | 将在场事件映射到各角色已有动作 | 能力不足时跳过，不假定 Hiyori 与 Hotaru 动作一致 |
| `shell/src/main/index.ts` 的 media permission handler | 保留现有麦克风路径 | 目前对 media 统一放行；引入摄像头前必须分开校验 audio/video、来源及窗口，不能把现有行为当摄像头授权 |

本轮定向检查未找到已接通的图片消息或摄像头视觉链路；上述为增量设计，不代表这些功能已经存在。

## 方案比较

| 方案 | 用途/优点 | 限制与取舍 |
|---|---|---|
| 现有百炼视觉模型 | 主动识图、图中文字与场景问答；减少凭证和供应商数量 | 先测实际模型/地域支持；云上传须明确告知 |
| MediaPipe Face Landmarker + Web Worker | 本地脸部关键点、朝向、blendshape；不必逐帧调用 LLM | 不提供人物身份识别；检测 API 同步阻塞，必须移出模型渲染线程 |
| 本地视觉语言模型 | 可离线理解图片 | 与既有 ASR/TTS 争夺 RTX 3060 资源，暂缓；需独立进程与显存基线 |
| 额外云视觉供应商 | 后续按能力显式切换 | 本阶段暂缓，不静默外发或自动切换供应商 |

MediaPipe 官方描述了关键点、blendshape 和变换矩阵，并提示视频检测会阻塞 UI，建议使用 Worker。它适合作为本地动作信号，不适合据此宣称识别身份或真实情绪。[官方 Web 指南](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/web_js)

## IDE 可执行阶段

### V0：手动图片理解

- Goal/Scenario：用户在视觉页选一张图片并提问，得到可取消的图文回答。
- Architecture Increment：扩展现有协议与 Provider 消息适配器，复用 Artifact 引用、Session/Generation，不新建通用 Vision Runtime。
- 范围：文件选择、缩略图、清除、格式和体积校验；单图先行；发送前显示目标模型与是否上传云端。默认不自动共享记忆。
- Tests/DoD：非法类型、解码失败、大图、网络超时有明确错误；取消与双角色切换丢弃旧结果；日志不含图片正文；使用无个人信息样本验证当前模型真实支持。记录处理与模型耗时，不能把规划指标写成实测。

### V1：摄像头本地预览与在场检测

- Goal/Scenario：用户明确开启后可预览、看到“检测到人脸/未检测到”，关闭即释放设备。
- Architecture Increment：renderer 摄像头控制器 + 专用 Worker，帧只保留最新一张；与 Live2D 渲染解耦。
- 范围：先以 320–640 像素、3–5 FPS、单人在场验证，CPU 优先；依赖/WASM/模型落到项目缓存，国内可达镜像优先，不使用运行时外部 CDN。
- Tests/DoD：拒绝权限、设备占用、拔插、窗口关闭/隐藏、换角均有确定状态；退出时停止全部 tracks；Worker 不积帧、不持续增长内存；连续运行10分钟记录渲染帧时间和CPU。相对无摄像头基线的 P95 帧时间增幅目标≤10%，达不到则降采样或暂停检测，不能牺牲模型交互。

### V2：低频角色反应

- Goal/Scenario：进入视野后一次招呼、离开后停止关注，避免不停打断用户。
- Architecture Increment：本地信号→去抖/冷却门控→已有 AvatarIntent；不逐帧发 LLM。
- Tests/DoD：建议在场连续1秒才触发、招呼冷却≥60秒（可调目标）；说话/表演时按现有优先级协调；双角色分别映射资产能力；取消和换角后零旧角色动作；关闭时无检测、无云请求。

### 暂缓项

具体人物身份识别、长期摄像头记忆、后台桌面截图、持续云视频、视觉驱动自动系统操作。将来若引入熟人识别，单独设计用户主动登记、本地模板、撤回和删除；不能用关键点假冒身份识别。笑容等动作分值只作动作提示，不当作心理状态判断。

## Tab 信息结构及权限

“识图”区放图片、问题、目标模型、发送/取消；“摄像头”区放设备、启动/停止、本地预览、采集指示、检测状态；“反应”区放冷却、角色动作映射和性能；“数据”区说明本地/云边界与清理。沿用 cream/lily tokens，默认摄像头关闭。

摄像头采集与发送单帧到云端是两种独立选择。换角与窗口退出停止采集、撤销待发任务并清空帧；停止必须可见、立即生效。图片和识别文本按不可信外部输入处理，不获得执行工具的权限。

设备权限、secure context 与 tracks 生命周期以 [getUserMedia 文档](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)为依据；Electron 放行范围以[官方 session 权限文档](https://www.electronjs.org/docs/latest/api/session#sessetpermissionrequesthandlerhandler)为依据。实施前核对 Electron 33 实际权限详情字段，避免影响已有语音功能。
