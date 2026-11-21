// Media control capability — 精确到应用的媒体控制（WinRT SMTC）。
#include <yuiro/capability/capability.hpp>

#include <string>

namespace yuiro {

// media_control(action, target?)：通过 WinRT SMTC 精确控制指定媒体应用，
// 不再使用会误控其他播放器的全局媒体键。
//
// action 取值：
//   play      | pause    | play_pause  → 播放 / 暂停 / 播放暂停切换
//   next      | prev                   → 下一首 / 上一首
//   now_playing                        → 读取当前播放曲目（JSON）
//   list_sessions                      → 列出系统所有媒体会话的 AUMID（排障用）
//   volume_up | volume_down | mute     → 音量控制（SMTC 无音量接口，仍为系统全局）
//
// target（可选）：目标应用的 SourceAppUserModelId 片段，缺省匹配网易云音乐。
// 匹配失败时**绝不回退全局媒体键**（那正是误控的根因），而是返回错误
// 并附带 list_sessions 的结果，便于排障与确认真实标识。
//
// 说明：编译期未找到 cppwinrt.exe 时（YUIRO_HAS_WINRT 未定义），
// 本能力退化为旧的全局媒体键实现并在 stdout 中标注降级。
class MediaControlCapability : public Capability {
 public:
  std::string name() const override { return "media_control"; }
  bool approval_required() const override { return false; }  // 非破坏性，免审批
  SystemResult run(const std::string& args_json,
                   const std::string& trace_id,
                   bool dry_run) override;
};

}  // namespace yuiro
