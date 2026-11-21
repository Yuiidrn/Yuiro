# 表情眼睛参数与自动眨眼顺序修复

Goal：闭眼笑等资源的眼睛参数真正作用于绘制，普通待机继续自然眨眼。Scenario：Hotaru exp_bsmile01要求左右EyeOpen Multiply 0，但SDK绘制前读回0.393–1而不是闭眼；只记录选中表情不能算成功。

Architecture Increment：保留现有Cubism4模型与SDK，只在模型实例生命周期内将自动眨眼移到表情合成前；动作正在更新时仍沿用SDK的“不额外自动眨眼”规则。卸载恢复方法与监听，不修改供应商包、资源文件、Agent或角色配置。Tests：参数写入顺序/每帧一次/动作归属/毫秒秒换算/清理；实际两模型绘制前参数及闭眼/回中性截图。DoD：原始前后数值和图像、类型/构建通过；不据此宣称所有资源语义或人工自然度已验收。

修复前证据avatar-expression-eye-before.json：中性75帧左右均1；exp_bsmile01稳定后89帧仍0.393–1。实际资源Multiply 0且FadeIn约0.2秒，采样在等待1秒后开始。安装SDK在expressionManager.update之后执行eyeBlink.updateParameters，存在后写覆盖，不能先靠更换语义候选掩盖问题。

## 修复和当前证据

新增avatar/expressionBlinkOrder.ts，装配在Live2DCanvas模型实例创建时，卸载时恢复。适配器记录原update的毫秒delta与motionManager.update返回值，在afterMotionUpdate、表情更新之前执行一次原生眨眼，跳过SDK原来的后写眨眼。动作实际更新时仍不执行自动眨眼，不重复计算眨眼，也不改Blink算法。表达式随后按原SDK Blend合成，最终注视/口型仍走原beforeModelUpdate钩子。WeakMap避免重复装配，清理幂等，不覆盖其他后来安装的包装；缺少所需接口则保持原路径。

生产适配器专项expression_blink_order_test.cjs复现原覆盖，验证闭眼结果、每帧一次、动作排他、dt毫秒→秒、重复装配/清理和原方法恢复。既有Avatar专项、前端typecheck/build通过；后端未改，沿用1000项基线。

实际原生Cubism Model.update边界采样见[avatar-expression-eye-after/result.json](avatar-expression-eye-after/result.json)，仅本地预览，不是读取avatarState猜测成功：

| 模型/阶段 | 采样帧 | 左右EyeOpen范围 |
| --- | --- | --- |
| Hiyori中性 | 1351 | 0–1，正常眨眼 |
| Hiyori happy | 199 | 稳定0.55000001，符合资源Multiply 0.55 |
| Hiyori回中性 | 1354 | 0–1，恢复正常眨眼 |
| Hotaru中性 | 1174 | 0–1，正常眨眼 |
| Hotaru exp_bsmile01 | 174 | 稳定0，符合闭眼笑资源 |
| Hotaru回中性 | 1244 | 0–1，恢复正常眨眼 |

中性/恢复每阶段采样8.2秒，选中表情阶段在等待1.2秒后再采1.2秒，避免把淡入过程混作稳定值。当前图片已能看到Hotaru闭眼笑；修复前候选头像不能当成完整表情语义审定。本轮尚未调整槽位排序或用户配置。

| 修复前选中bsmile（仍睁眼） | 修复后实际闭眼笑 |
| --- | --- |
| ![修复前](avatar-expression-candidates/exp_bsmile01.png) | ![修复后](avatar-expression-eye-after/hotaru-expression.png) |

另补[动作/表情/口型组合](avatar-expression-eye-combo/result.json)：Hiyori Idle#6+happy与Hotaru Motion#4+bsmile，本地合成mouth prop=0.7；绘制前真实口型参数均稳定0.69999999，Hotaru眼睛仍为0，Hiyori仍≤0.55。取消/回中性后口型为0，两角色四场景通过。这是参数仲裁验证，不是听到声音或真实语音口型同步验收。

诊断finally恢复原生Model.update、清空合成口型、回中性并恢复Hotaru预览；没有写角色配置、麦克风、背景或捕获保护。新增诊断Ruff与diff检查通过。用户明确表示暂不方便人工验收，继续自动验证，不以这些参数/图片代替其自然度评价。当前构建新增了帧顺序适配，旧300秒待机样本不能重新标成这版长时稳定性证据。
