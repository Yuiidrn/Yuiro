// Media bridge capability — 把音乐资源投递到网易云桌面客户端播放。
//
// ⚠️ 实测结论（2026-08-31）：Windows 版网易云客户端无法被外部唤起播放，
// 本能力当前**未被注册到 MCP 工具表**（见 server_stdio.cpp 的说明）。
// 已验证无效的三条路径：
//   1. Start-Process("orpheus://song/<originalId>") —— 无反应
//   2. cloudmusic.exe --webcmd="orpheus://song/<id>" —— 无反应
//   3. ncm-cli play --player orpheus —— 报错"仅支持 macOS"
// 点歌改由引擎层 yuiro/netease 走 ncm-cli play（mpv 发声）。
// 保留本实现仅供将来客户端开放该能力时启用。
#include <yuiro/capability/capability.hpp>

#include <string>

namespace yuiro {

// media_bridge：通过客户端注册的 orpheus:// 协议把歌曲/歌单投递给桌面客户端，
// 让声音由客户端发出（保留音效、桌面歌词、歌单与播放状态同步）。
//
// 注册表事实（本机实测）：
//   HKLM\SOFTWARE\Classes\orpheus\shell\open\command
//     = "<cloudmusic.exe>" --webcmd="%1"
// 因此 ShellExecute("orpheus://song/<id>") 即可把命令投递给客户端。
//
// action 取值：
//   play_song      → orpheus://song/<song_id>
//   play_playlist  → orpheus://playlist/<playlist_id>
//   open_search    → orpheus://search/<keyword>
//   raw_uri        → 原样投递 uri 字段（兜底，便于实测新路径）
//
// 参数：
//   song_id / playlist_id / keyword / uri —— 按 action 取用
//   ensure_play（可选，默认 false）：投递后等待片刻，再用 SMTC TryPlayAsync 补按播放。
//     实测发现客户端只跳详情页不自动播放时启用；默认关闭以免打断用户已有播放。
//
// 即使未编译 C++/WinRT（YUIRO_HAS_WINRT 未定义）本能力仍可用——URI 投递不依赖 WinRT，
// 仅 ensure_play 需要 SMTC 支持。
class MediaBridgeCapability : public Capability {
 public:
  std::string name() const override { return "media_bridge"; }
  bool approval_required() const override { return false; }  // 播放类操作，免审批
  SystemResult run(const std::string& args_json,
                   const std::string& trace_id,
                   bool dry_run) override;
};

}  // namespace yuiro
