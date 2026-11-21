/**
 * 渲染层布局常量（与 main/index.ts 中 FIT_SIDE_MARGIN / FIT_BOTTOM_RESERVE 保持一致）。
 *
 * 窗口 = 模型包围盒 + 左右交互余量（括号功能岛）+ 底部余量（连接状态泡）。
 * 聊天坞展开时主进程把窗口向左再扩 CHAT_DOCK_WIDTH，模型区不受侵占。
 */

/** 模型左右两侧的交互余量（括号图标列的活动空间）。 */
export const SIDE_MARGIN = 64

/**
 * 模型底部余量（输入胶囊 + 语音提示展开区）。
 *
 * 必须与 main/index.ts 的 ISLAND_RESERVE_H 保持一致：模型可用高度 = 窗口高 - 本值，
 * 两者相等时模型 scale 恰为 1（fit-to-model 会把窗口高度设为模型高 + 该预留）。
 *
 * 100 = 输入胶囊 42 + 语音提示向下展开区 ~44 + 边距；
 * 这块区域位于模型脚底之下且完全透明，因此输入/提示展开都不会遮住模型。
 */
export const BOTTOM_RESERVE = 100

/** 聊天坞宽度（请求值；主进程按屏幕空间可能右移窗口，但宽度不变）。 */
export const CHAT_DOCK_WIDTH = 300
