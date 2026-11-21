// Media bridge implementation — 经 orpheus:// 协议把资源投递给网易云桌面客户端。
//
// 设计要点：与 media_control（SMTC 遥控器）互补——SMTC 无法指定"播放哪一首"，
// 只能控制当前曲目；本能力负责"指定内容"，二者配合才构成完整点歌链路。
#include <yuiro/capability/media_bridge.hpp>

#include <third_party/json.hpp>

#include <windows.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <string>

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

// ShellExecute 返回值 <= 32 表示失败（错误码），> 32 表示成功。
bool deliver_uri(const std::string& uri) {
  const HINSTANCE h =
      ShellExecuteA(nullptr, "open", uri.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
  return reinterpret_cast<std::intptr_t>(h) > 32;
}

// UTF-8 百分号编码：中文关键词直接拼进 URI 会被 ShellExecute 截断。
std::string url_encode(const std::string& s) {
  static const char* kUnreserved =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~";
  std::string out;
  out.reserve(s.size() * 3);
  for (unsigned char c : s) {
    if (std::strchr(kUnreserved, static_cast<char>(c)) != nullptr) {
      out.push_back(static_cast<char>(c));
    } else {
      char buf[4];
      std::snprintf(buf, sizeof(buf), "%%%02X", c);
      out += buf;
    }
  }
  return out;
}

std::string to_lower_copy(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return s;
}

#ifdef YUIRO_HAS_WINRT
using winrt::Windows::Media::Control::GlobalSystemMediaTransportControlsSessionManager;

// WinRT 单元只需初始化一次（与 media.cpp 各自的 once_flag 互不影响，
// 重复初始化会抛异常，此处静默忽略）。
void ensure_apartment() {
  static std::once_flag flag;
  std::call_once(flag, [] {
    try {
      winrt::init_apartment(winrt::apartment_type::multi_threaded);
    } catch (const winrt::hresult_error&) {
      // 已初始化
    }
  });
}

// 用 SMTC 对目标会话补按播放。返回 false 表示未找到会话或应用拒绝。
bool smtc_ensure_play(const std::string& target) {
  try {
    ensure_apartment();
    auto manager = GlobalSystemMediaTransportControlsSessionManager::RequestAsync().get();
    for (const auto& s : manager.GetSessions()) {
      const std::string aumid = winrt::to_string(s.SourceAppUserModelId());
      const std::string lower = to_lower_copy(aumid);
      const bool hit = target.empty()
                           ? (lower.find("cloudmusic") != std::string::npos ||
                              lower.find("netease") != std::string::npos ||
                              lower.find("orpheus") != std::string::npos)
                           : lower.find(to_lower_copy(target)) != std::string::npos;
      if (hit) return s.TryPlayAsync().get();
    }
    return false;
  } catch (const winrt::hresult_error&) {
    return false;
  } catch (const std::exception&) {
    return false;
  }
}
#endif

// 解析 action 与参数，产出待投递的 URI；失败时把原因写进 err。
bool build_uri(const json& args, const std::string& action, std::string& uri,
               std::string& err) {
  auto get_str = [&](const char* key) -> std::string {
    if (args.contains(key) && args[key].is_string()) return args[key].get<std::string>();
    if (args.contains(key) && args[key].is_number()) {
      return std::to_string(args[key].get<long long>());
    }
    return "";
  };

  if (action == "play_song") {
    const std::string id = get_str("song_id");
    if (id.empty()) {
      err = "play_song 需要提供 song_id";
      return false;
    }
    uri = "orpheus://song/" + id;
    return true;
  }
  if (action == "play_playlist") {
    const std::string id = get_str("playlist_id");
    if (id.empty()) {
      err = "play_playlist 需要提供 playlist_id";
      return false;
    }
    uri = "orpheus://playlist/" + id;
    return true;
  }
  if (action == "open_search") {
    const std::string kw = get_str("keyword");
    if (kw.empty()) {
      err = "open_search 需要提供 keyword";
      return false;
    }
    uri = "orpheus://search/" + url_encode(kw);
    return true;
  }
  if (action == "raw_uri") {
    const std::string raw = get_str("uri");
    if (raw.empty()) {
      err = "raw_uri 需要提供 uri";
      return false;
    }
    uri = raw;
    return true;
  }
  err = "未知 action: " + action;
  return false;
}
}  // namespace

SystemResult MediaBridgeCapability::run(const std::string& args_json,
                                        const std::string& trace_id,
                                        bool dry_run) {
  SystemResult r;
  r.trace_id = trace_id;
  json args = json::parse(args_json, nullptr, false);
  if (args.is_discarded() || !args.is_object() || !args.contains("action") ||
      !args["action"].is_string()) {
    r.status = "error";
    r.stdout_text = "参数错误：需要 {\"action\": "
                    "\"play_song|play_playlist|open_search|raw_uri\", ...}";
    return r;
  }

  const std::string action = args["action"].get<std::string>();
  std::string uri;
  std::string err;
  if (!build_uri(args, action, uri, err)) {
    r.status = "error";
    r.stdout_text = err;
    return r;
  }

  const bool ensure_play = args.value("ensure_play", false);

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将投递 URI " + uri +
                    (ensure_play ? "（并在投递后尝试 SMTC 补按播放）" : "");
    return r;
  }

  if (!deliver_uri(uri)) {
    r.status = "error";
    r.stdout_text = "投递失败: " + uri +
                    "（客户端未响应。请确认网易云音乐已安装；若未运行，"
                    "协议应会自动拉起客户端，如仍失败请用 app_open 先启动）";
    r.audit_json = "{\"tool\":\"media_bridge\",\"action\":\"" + action +
                   "\",\"result\":\"deliver_failed\"}";
    return r;
  }

  r.status = "ok";
  r.stdout_text = "已投递给网易云客户端: " + uri;

  if (ensure_play) {
    // 客户端响应协议需要一点时间（拉起 UI / 切换曲目）。
    ::Sleep(2500);
#ifdef YUIRO_HAS_WINRT
    const std::string target = args.contains("target") && args["target"].is_string()
                                   ? args["target"].get<std::string>()
                                   : std::string();
    if (smtc_ensure_play(target)) {
      r.stdout_text += "（已通过 SMTC 补按播放）";
      r.audit_json = "{\"tool\":\"media_bridge\",\"action\":\"" + action +
                     "\",\"result\":\"delivered_and_played\"}";
    } else {
      // 找不到会话属正常：客户端可能刚启动尚未产生 SMTC 会话，不视为失败。
      r.stdout_text += "（已投递，但未找到可控制的媒体会话；"
                       "若客户端未自动播放，可稍后用 media_control action=play）";
      r.audit_json = "{\"tool\":\"media_bridge\",\"action\":\"" + action +
                     "\",\"result\":\"delivered_play_unconfirmed\"}";
    }
#else
    r.stdout_text += "（本构建未启用 WinRT，无法补按播放）";
    r.audit_json = "{\"tool\":\"media_bridge\",\"action\":\"" + action +
                   "\",\"result\":\"delivered_no_winrt\"}";
#endif
    return r;
  }

  r.audit_json =
      "{\"tool\":\"media_bridge\",\"action\":\"" + action + "\",\"result\":\"delivered\"}";
  return r;
}

}  // namespace yuiro
