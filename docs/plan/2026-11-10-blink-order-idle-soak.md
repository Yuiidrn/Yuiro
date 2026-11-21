# 表情/眨眼顺序更新后的待机稳定性

Goal：对当前真实加载的眨眼适配构建重新验证持续待机，不挪用旧候选记录。Scenario：正式切换两角色，各持续300秒；Hiyori仍只用固定Idle#0，观察rAF、画布非空/变化、presence及绘制边界EyeOpen。

Architecture Increment：无生产改动，仅给已有持续采样诊断增加可选原生眼睛计数；不改眨眼频率/动作池。Tests：每角色300秒、可见采样、非空画布、固定动作边界、眼睛有更新且非恒闭；前后构建哈希一致、结束恢复Hotaru并清理采样器。DoD：有具体样本与失败/可见性范围说明，不把rAF当GPU耗时、闭合转换数当SDK精确眨眼次数或人耳自然度。

命令：`.env-local/engine-venv2/Scripts/python.exe scripts/diag/avatar_current_idle_soak.py --seconds 300 --eyes --output docs/plan/avatar-blink-order-idle-soak.json`。不调用云端或麦克风。原先300秒文件保留，此轮使用新文件。

## 本轮结果

当前构建双角色各300秒通过有界自动验证。原始记录：[avatar-blink-order-idle-soak.json](avatar-blink-order-idle-soak.json)；断言汇总及最终状态：[avatar-blink-order-idle-summary.json](avatar-blink-order-idle-summary.json)；构建/适配源码快照：[avatar-blink-order-soak-manifest.json](avatar-blink-order-soak-manifest.json)。30个所列文件哈希前后一致。

| 角色 | 实际时长 | 可见/idle采样 | 绘制回调数 | rAF间隔P95 / 最大 | 最小非空像素 / 不同透明度哈希 | 实际动作 |
| --- | --- | --- | --- | --- | --- | --- |
| Hotaru | 300.17秒 | 300 / 300 | 41793 | 12.2 / 24.6ms | 313 / 300 | Motion#19，间歇无动作 |
| Hiyori | 300.14秒 | 300 / 300 | 49492 | 6.2 / 20.3ms | 268 / 300 | 仅Idle#0，间歇无动作 |

两个角色绘制边界眼睛开合值均覆盖0到1；阈值闭合转换分别66、99次，只说明实际可见眼睛参数变化，含动作控制，不代表SDK独立自动眨眼次数。画布按80×100缩采样，透明度哈希变化只能支持持续视觉更新，不能证明动作自然。

另外重新运行生产表情/眨眼适配专项与Avatar基线专项，均通过，覆盖顺序、动作控制排除、幂等释放，以及固定待机、注视、口型和旧身份帧拒收等已有测试。

结束已确认Hotaru、idle、麦克风关闭；原生Model.update采样包装及帧采样器均清理。未改角色配置、捕获保护或背景，未调用LLM/TTS服务。此轮没有重新运行后端全量，沿用上轮1000项通过记录。

仍待人工确认：Hiyori真实麦克风/打断、固定待机主观自然度；供应商首句波动与声学停声时间另行实测。用户暂不方便，不开启麦克风。本记录不推断多小时或语音压力稳定性。
