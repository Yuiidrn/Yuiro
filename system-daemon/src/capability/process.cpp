#include <yuiro/capability/process.hpp>

#include <third_party/json.hpp>

#include <windows.h>
#include <shellapi.h>
#include <tlhelp32.h>

#include <cstdint>
#include <string>
#include <unordered_map>

namespace yuiro {

namespace {
using json = nlohmann::json;

// ShellExecute 返回值 <= 32 表示失败（错误码），> 32 表示成功句柄。
bool shell_exec_ok(HINSTANCE h) {
  return reinterpret_cast<std::intptr_t>(h) > 32;
}

// 中文应用名 → 可执行名/路径映射（LLM 可能传中文名，ShellExecute 需要 exe/路径）。
std::string resolve_target(const std::string& name) {
  static const std::unordered_map<std::string, std::string> kAliases = {
      {"记事本", "notepad"},
      {"计算器", "calc"},
      {"画图", "mspaint"},
      {"命令提示符", "cmd"},
      {"cmd", "cmd"},
      {"控制面板", "control"},
      {"资源管理器", "explorer"},
      {"文件管理器", "explorer"},
      {"我的电脑", "explorer"},
      {"此电脑", "explorer"},
      {"浏览器", "msedge"},
      {"Edge", "msedge"},
      {"网易云音乐", "cloudmusic"},
      {"网易云", "cloudmusic"},
      {"微信", "wechat"},
      {"QQ", "qq"},
  };
  auto it = kAliases.find(name);
  return it != kAliases.end() ? it->second : name;
}

}  // namespace

SystemResult AppOpenCapability::run(const std::string& args_json,
                                    const std::string& trace_id,
                                    bool dry_run) {
  SystemResult r;
  r.trace_id = trace_id;
  // 解析参数：{"name": "notepad"} 或 {"app": "notepad"}（兼容 LLM 传参差异）。
  json args = json::parse(args_json, nullptr, false);
  std::string target;
  if (!args.is_discarded() && args.is_object()) {
    if (args.contains("name") && args["name"].is_string()) {
      target = args["name"].get<std::string>();
    } else if (args.contains("app") && args["app"].is_string()) {
      target = args["app"].get<std::string>();
    }
  }
  if (target.empty()) {
    r.status = "error";
    r.stdout_text = "参数错误：需要 {\"name\": \"<应用或路径>\"}";
    return r;
  }
  target = resolve_target(target);

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将打开 \"" + target + "\"";
    return r;
  }

  // ShellExecuteA：按默认关联打开应用/文件/URL（无需管理员权限）。
  HINSTANCE h = ShellExecuteA(nullptr, "open", target.c_str(), nullptr, nullptr,
                              SW_SHOWNORMAL);
  if (!shell_exec_ok(h)) {
    r.status = "error";
    r.stdout_text = "ShellExecute 失败（错误码 " +
                    std::to_string(reinterpret_cast<std::intptr_t>(h)) + "）";
    return r;
  }
  r.status = "ok";
  r.stdout_text = "已打开 \"" + target + "\"";
  r.audit_json = "{\"tool\":\"app_open\",\"target\":\"" + target + "\"}";
  return r;
}

SystemResult AppFocusCapability::run(const std::string& args_json,
                                     const std::string& trace_id,
                                     bool dry_run) {
  SystemResult r;
  r.trace_id = trace_id;
  json args = json::parse(args_json, nullptr, false);
  if (args.is_discarded() || !args.is_object() || !args.contains("name") ||
      !args["name"].is_string()) {
    r.status = "error";
    r.stdout_text = "参数错误：需要 {\"name\": \"<窗口标题关键词>\"}";
    return r;
  }
  std::string name = args["name"].get<std::string>();

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将聚焦窗口 \"" + name + "\"";
    return r;
  }

  // 三级递进查找，命中即返回：
  //  L1 可见窗口标题含关键词（最常见，用户能看到的应用）；
  //  L2 任意窗口（含最小化）标题含关键词 → 先 Restore 再激活
  //     （解决 app_open 后窗口尚未可见/被最小化导致的"找不到"）；
  //  L3 进程名兜底：窗口标题对不上时，按可执行名反查进程所属窗口
  //     （如 name="网易云" → 解析为 cloudmusic → 进程 cloudmusic.exe）。
  struct Ctx {
    std::string needle;        // 原始关键词
    std::string proc;          // L3 进程名（由 resolve_target 得到）
    bool visible_only = true;  // L1 用 true，L2 用 false
    DWORD pid = 0;             // L3 目标进程 PID
    HWND hwnd = nullptr;
  };
  Ctx ctx{name, resolve_target(name), true, 0, nullptr};

  auto match = [](HWND hwnd, LPARAM lp) -> BOOL {
    auto* c = reinterpret_cast<Ctx*>(lp);
    if (c->visible_only && !IsWindowVisible(hwnd)) return TRUE;
    char buf[512] = {0};
    int len = GetWindowTextA(hwnd, buf, sizeof(buf) - 1);
    if (len > 0 && std::string(buf).find(c->needle) != std::string::npos) {
      c->hwnd = hwnd;
      return FALSE;  // 命中，停止枚举
    }
    return TRUE;
  };

  // L1：仅可见窗口
  EnumWindows(match, reinterpret_cast<LPARAM>(&ctx));
  // L2：放宽到所有窗口（含最小化）
  if (ctx.hwnd == nullptr) {
    ctx.visible_only = false;
    EnumWindows(match, reinterpret_cast<LPARAM>(&ctx));
  }
  // L3：进程名兜底（窗口标题对不上时，用进程反查窗口）。
  // 以 name 与 resolve_target(name) 作为候选进程名（去 .exe 后缀比较），
  // 不要求 proc != name —— 用户直接传进程名（如 "notepad"）也应能命中。
  if (ctx.hwnd == nullptr) {
    std::string base_name = name;
    std::string base_proc = ctx.proc;
    auto strip_exe = [](std::string s) -> std::string {
      if (s.size() >= 4 && _stricmp(s.c_str() + s.size() - 4, ".exe") == 0)
        s.resize(s.size() - 4);
      return s;
    };
    base_name = strip_exe(base_name);
    base_proc = strip_exe(base_proc);
    std::vector<std::string> cands;
    cands.push_back(base_name);
    if (!base_proc.empty() && base_proc != base_name) cands.push_back(base_proc);

    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap != INVALID_HANDLE_VALUE) {
      PROCESSENTRY32 pe{};
      pe.dwSize = sizeof(pe);
      if (Process32First(snap, &pe)) {
        do {
          std::string exe = pe.szExeFile;
          exe = exe.substr(exe.find_last_of("\\/") + 1);
          exe = strip_exe(exe);
          bool hit = false;
          for (const auto& c : cands) {
            if (_stricmp(exe.c_str(), c.c_str()) == 0) { hit = true; break; }
          }
          if (hit) {
            ctx.pid = pe.th32ProcessID;
            break;
          }
        } while (Process32Next(snap, &pe));
      }
      CloseHandle(snap);
    }
    if (ctx.pid != 0) {
      EnumWindows(
          [](HWND hwnd, LPARAM lp) -> BOOL {
            auto* c = reinterpret_cast<Ctx*>(lp);
            DWORD pid = 0;
            GetWindowThreadProcessId(hwnd, &pid);
            if (pid == c->pid) {
              c->hwnd = hwnd;
              return FALSE;
            }
            return TRUE;
          },
          reinterpret_cast<LPARAM>(&ctx));
    }
  }

  if (ctx.hwnd == nullptr) {
    r.status = "error";
    r.stdout_text = "未找到标题含 \"" + name + "\" 的窗口（且进程 " +
                    ctx.proc + " 未运行）";
    return r;
  }

  // L2 命中（原本不可见）先恢复窗口，否则仍停留在后台，用户看不到。
  if (!IsWindowVisible(ctx.hwnd)) {
    ShowWindow(ctx.hwnd, SW_RESTORE);
  }
  // SetForegroundWindow 聚焦；前台抢占时先 AttachThreadInput 再 BringWindowToTop。
  const HWND fg = GetForegroundWindow();
  const DWORD fg_thread = GetWindowThreadProcessId(fg, nullptr);
  const DWORD cur_thread = GetCurrentThreadId();
  if (fg_thread != cur_thread) {
    AttachThreadInput(cur_thread, fg_thread, TRUE);
    BringWindowToTop(ctx.hwnd);
    SetForegroundWindow(ctx.hwnd);
    AttachThreadInput(cur_thread, fg_thread, FALSE);
  } else {
    SetForegroundWindow(ctx.hwnd);
  }
  r.status = "ok";
  r.stdout_text = "已聚焦窗口: " + name;
  r.audit_json = "{\"tool\":\"app_focus\",\"name\":\"" + name + "\"}";
  return r;
}

}  // namespace yuiro
