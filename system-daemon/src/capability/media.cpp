// Media control implementation — WinRT SMTC per-app precise control.
//
// 相比旧的 SendInput 全局媒体键（其他播放器也会响应 → 误控），
// SMTC 先枚举系统媒体会话，按 SourceAppUserModelId 锁定目标应用再控制。
#include <yuiro/capability/media.hpp>

#include <third_party/json.hpp>

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <string>
#include <unordered_map>
#include <vector>

#ifdef YUIRO_HAS_WINRT
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Foundation.Collections.h>
#include <winrt/Windows.Media.Control.h>
#include <winrt/base.h>
#include <mutex>
#endif

namespace yuiro {

namespace {
using json = nlohmann::json;

// 全局媒体键：仅在两条路径上使用——
//   1) 音量（SMTC 不提供音量接口，只能控制系统全局音量）
//   2) 编译期无 C++/WinRT 投影时的降级实现
const std::unordered_map<std::string, WORD> kMediaVk = {
    {"play", VK_MEDIA_PLAY_PAUSE},
    {"pause", VK_MEDIA_PLAY_PAUSE},
    {"play_pause", VK_MEDIA_PLAY_PAUSE},
    {"next", VK_MEDIA_NEXT_TRACK},
    {"prev", VK_MEDIA_PREV_TRACK},
    {"volume_up", VK_VOLUME_UP},
    {"volume_down", VK_VOLUME_DOWN},
    {"mute", VK_VOLUME_MUTE},
};

void send_media_key(WORD vk) {
  // SendInput 比 keybd_event 规范（keybd_event 已被官方标记弃用）。
  INPUT inputs[2] = {};
  inputs[0].type = INPUT_KEYBOARD;
  inputs[0].ki.wVk = vk;
  inputs[1].type = INPUT_KEYBOARD;
  inputs[1].ki.wVk = vk;
  inputs[1].ki.dwFlags = KEYEVENTF_KEYUP;
  SendInput(2, inputs, sizeof(INPUT));
}

std::string to_lower_copy(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return s;
}

#ifdef YUIRO_HAS_WINRT
using winrt::Windows::Media::Control::GlobalSystemMediaTransportControlsSession;
using winrt::Windows::Media::Control::GlobalSystemMediaTransportControlsSessionManager;
using winrt::Windows::Media::Control::
    GlobalSystemMediaTransportControlsSessionPlaybackStatus;

// WinRT 单元每个线程只需初始化一次；daemon 长驻，重复调用会抛异常。
void ensure_apartment() {
  static std::once_flag flag;
  std::call_once(flag, [] {
    try {
      winrt::init_apartment(winrt::apartment_type::multi_threaded);
    } catch (const winrt::hresult_error&) {
      // 已初始化（或无法更改模式），忽略即可
    }
  });
}

// 默认目标：网易云音乐。AUMID 由客户端版本决定，故按关键字模糊匹配而非硬编码单值。
bool is_default_target(const std::string& aumid) {
  const std::string lower = to_lower_copy(aumid);
  return lower.find("cloudmusic") != std::string::npos ||
         lower.find("netease") != std::string::npos ||
         lower.find("orpheus") != std::string::npos;
}

bool matches_target(const std::string& aumid, const std::string& target) {
  if (target.empty()) return is_default_target(aumid);
  return to_lower_copy(aumid).find(to_lower_copy(target)) != std::string::npos;
}

const char* status_to_string(GlobalSystemMediaTransportControlsSessionPlaybackStatus s) {
  switch (s) {
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Closed:
      return "closed";
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Opened:
      return "opened";
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Changing:
      return "changing";
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Stopped:
      return "stopped";
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Playing:
      return "playing";
    case GlobalSystemMediaTransportControlsSessionPlaybackStatus::Paused:
      return "paused";
    default:
      return "unknown";
  }
}

// 统一的 SMTC 执行入口，返回 false 表示未处理（交由调用方继续走降级路径）。
bool run_smtc(const std::string& action, const std::string& target, bool dry_run,
              SystemResult& r) {
  if (action != "play" && action != "pause" && action != "play_pause" &&
      action != "next" && action != "prev" && action != "now_playing" &&
      action != "list_sessions") {
    return false;
  }

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将通过 SMTC 对目标会话执行 " + action +
                    (target.empty() ? "（默认网易云音乐）" : "（target=" + target + "）");
    return true;
  }

  try {
    ensure_apartment();
    auto manager = GlobalSystemMediaTransportControlsSessionManager::RequestAsync().get();
    auto sessions = manager.GetSessions();

    if (action == "list_sessions") {
      json arr = json::array();
      for (const auto& s : sessions) {
        json item;
        item["aumid"] = winrt::to_string(s.SourceAppUserModelId());
        arr.push_back(item);
      }
      r.status = "ok";
      r.stdout_text = arr.empty() ? "[]" : arr.dump(2);
      return true;
    }

    // 定位目标会话；同时收集全部 AUMID 以便匹配失败时排障。
    GlobalSystemMediaTransportControlsSession found{nullptr};
    std::vector<std::string> all_aumids;
    for (const auto& s : sessions) {
      const std::string aumid = winrt::to_string(s.SourceAppUserModelId());
      all_aumids.push_back(aumid);
      if (!found && matches_target(aumid, target)) found = s;
    }

    if (!found) {
      // 关键：绝不回退全局媒体键——那正是误控的根因。
      json j;
      j["error"] = "未找到匹配的媒体会话";
      j["target"] = target.empty() ? std::string("网易云音乐（默认）") : target;
      j["hint"] = "请用 action=list_sessions 查看当前所有媒体会话的 AUMID，"
                  "再用 target 参数指定；若目标应用未在播放，其会话可能尚未创建。";
      j["sessions"] = all_aumids;
      r.status = "error";
      r.stdout_text = j.dump(2, ' ', false, json::error_handler_t::replace);
      return true;
    }

    if (action == "now_playing") {
      json j;
      j["aumid"] = winrt::to_string(found.SourceAppUserModelId());
      j["status"] = status_to_string(found.GetPlaybackInfo().PlaybackStatus());
      try {
        auto props = found.TryGetMediaPropertiesAsync().get();
        j["title"] = winrt::to_string(props.Title());
        j["artist"] = winrt::to_string(props.Artist());
        j["album"] = winrt::to_string(props.AlbumTitle());
      } catch (const winrt::hresult_error&) {
        // 部分应用不提供媒体属性，降级为仅返回播放状态
        j["title"] = "";
        j["artist"] = "";
        j["album"] = "";
      }
      try {
        const auto timeline = found.GetTimelineProperties();
        const double tick = 10000000.0;  // TimeSpan 以 100ns 为单位
        j["position_s"] = static_cast<double>(timeline.Position().count()) / tick;
        j["duration_s"] = static_cast<double>(timeline.EndTime().count()) / tick;
      } catch (const winrt::hresult_error&) {
        j["position_s"] = 0.0;
        j["duration_s"] = 0.0;
      }
      r.status = "ok";
      r.stdout_text = j.dump(2, ' ', false, json::error_handler_t::replace);
      return true;
    }

    bool ok = false;
    if (action == "play") {
      ok = found.TryPlayAsync().get();
    } else if (action == "pause") {
      ok = found.TryPauseAsync().get();
    } else if (action == "play_pause") {
      const bool playing =
          found.GetPlaybackInfo().PlaybackStatus() ==
          GlobalSystemMediaTransportControlsSessionPlaybackStatus::Playing;
      ok = playing ? found.TryPauseAsync().get() : found.TryPlayAsync().get();
    } else if (action == "next") {
      ok = found.TrySkipNextAsync().get();
    } else {  // prev
      ok = found.TrySkipPreviousAsync().get();
    }

    if (ok) {
      r.status = "ok";
      r.stdout_text = "已通过 SMTC 执行: " + action + " → " +
                      winrt::to_string(found.SourceAppUserModelId());
    } else {
      // 会话存在但拒绝了该操作（很多应用不支持跳转/播放控制会返回 false）
      r.status = "error";
      r.stdout_text = "目标会话拒绝了该操作: " + action +
                      "（该应用可能未实现此控制，或当前状态不允许）";
    }
    return true;
  } catch (const winrt::hresult_error& e) {
    r.status = "error";
    r.stdout_text = std::string("SMTC 调用失败: ") + winrt::to_string(e.message());
    return true;
  } catch (const std::exception& e) {
    r.status = "error";
    r.stdout_text = std::string("SMTC 调用异常: ") + e.what();
    return true;
  }
}
#endif
}  // namespace

SystemResult MediaControlCapability::run(const std::string& args_json,
                                         const std::string& trace_id,
                                         bool dry_run) {
  SystemResult r;
  r.trace_id = trace_id;
  json args = json::parse(args_json, nullptr, false);
  if (args.is_discarded() || !args.is_object() || !args.contains("action") ||
      !args["action"].is_string()) {
    r.status = "error";
    r.stdout_text =
        "参数错误：需要 {\"action\": "
        "\"play|pause|play_pause|next|prev|now_playing|list_sessions|volume_up|volume_down|mute\"}";
    return r;
  }
  const std::string action = args["action"].get<std::string>();
  std::string target;
  if (args.contains("target") && args["target"].is_string()) {
    target = args["target"].get<std::string>();
  }

#ifdef YUIRO_HAS_WINRT
  // 播放控制与状态读取走 SMTC（精确到应用，不误控）
  if (run_smtc(action, target, dry_run, r)) {
    r.audit_json = "{\"tool\":\"media_control\",\"action\":\"" + action +
                   "\",\"transport\":\"smtc\"}";
    return r;
  }
#endif

  // 音量：SMTC 无音量接口，只能控制系统全局音量。
  // 无 C++/WinRT 投影时，播放控制也降级到全局媒体键（会误控，仅作兜底）。
  auto it = kMediaVk.find(action);
  if (it == kMediaVk.end()) {
    r.status = "error";
    r.stdout_text = "未知 action: " + action;
    return r;
  }

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将发送媒体键 " + action;
    return r;
  }

  send_media_key(it->second);
  r.status = "ok";
#ifdef YUIRO_HAS_WINRT
  r.stdout_text = "已发送系统音量键: " + action + "（SMTC 无音量接口，作用范围为系统全局）";
  r.audit_json = "{\"tool\":\"media_control\",\"action\":\"" + action +
                 "\",\"transport\":\"volume_key\"}";
#else
  r.stdout_text = "已发送全局媒体键: " + action +
                  "（降级模式：未找到 C++/WinRT 投影，非精确控制，可能误控其他播放器）";
  r.audit_json = "{\"tool\":\"media_control\",\"action\":\"" + action +
                 "\",\"transport\":\"media_key_fallback\"}";
#endif
  return r;
}

}  // namespace yuiro
