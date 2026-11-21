# 哭泣动作与安抚语义分离

Goal：默认安抚用户时不自动选择尚未审定的哭泣/悲伤动作。Scenario：Hotaru收到comfort槽位时，不因文件名cry/tear/sad而播放悲伤动作；明确指定的资源及角色自定义覆盖仍可用。Architecture Increment：只修正共享纯函数词表，沿用现有manifest→槽位→意图链。Tests：真实资产清单上的前后候选、缺失安全回退、明确动作选择、类型/构建。DoD：默认comfort不包含三类悲伤词，已知comfort/pat/hug保留，具体资源可试播，记录实际部署/验收范围。

依据：此前动态抽查已经记录Hotaru Motion#10低落、Motion#0眼泪强度未审定；共享词表仍将sad/cry/tear映射comfort，与“未经审定不自动推广”的实施边界不一致。哭泣可以表达共情，但不能仅凭名字断定适合所有安抚用户场景。

## 实施及验证

共享词表只移除sad/cry/tear动作的comfort推断；三类悲伤表情推断仍为sad，comfort/pat/hug动作推断保留。后端角色performance_map/motion_slots指定的group#index及调试台具体试播不受词表改变影响。

- `node scripts/diag/avatar_comfort_semantics_test.cjs`通过。基于实际model3/motion3数据，两角色共13/67个动作仍保留；Hiyori移除0个自动comfort候选，Hotaru移除7个：Motion#0、#10–12、#43–45。默认resolver找不到comfort动作时返回null；上述7个具体动作仍可选。见[资产与解析结果](avatar-comfort-semantics.json)。
- 前端typecheck/build通过。因清单规则由Electron主进程加载，确认只存在一个本项目main后重启该壳，未重启引擎。启动关闭临时捕获例外（YUIRO_UI_CAPTURE=0），不添加额外桌宠实例，角色配置保持原样。
- 新主进程`inspectPetModel`读取两套真实清单：两者comfort候选均为空、完整动作数仍13/67；Hotaru七项slot为空。见[真实主进程清单](avatar-comfort-manifest-live.json)。
- 真实工作台Hiyori Idle#7、Hotaru Motion#0的具体动作播放/结束/显式取消四场景通过，证明tear资源仍可手动试播，见[试播回归](avatar-comfort-explicit-preview-live.json)。本地预览最终恢复Hotaru。

当前为新构建，未重跑此前300秒待机或后端全量；此次无后端修改。不将移除7个默认候选解释为全部资源语义审定完成。尤其comfort的默认sad表情是否适合各情境，仍需动态/用户审定。没有以此补丁声称低延迟改善，麦克风始终关闭，未调用大脑或供应商。
