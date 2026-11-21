#include <yuiro/mcp/server_stdio.hpp>

#include <third_party/json.hpp>

#include <yuiro/capability/capability.hpp>
#include <yuiro/capability/files.hpp>
#include <yuiro/capability/media.hpp>
#include <yuiro/capability/media_bridge.hpp>
#include <yuiro/capability/process.hpp>
#include <yuiro/security/policy.hpp>

#include <chrono>
#include <iostream>
#include <memory>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

namespace yuiro {

namespace {

using json = nlohmann::json;

// capability registry：工具名 -> 能力实现（M4 逐步补全）。
std::unordered_map<std::string, std::unique_ptr<Capability>> g_capabilities;

void ensure_registry() {
  if (!g_capabilities.empty()) return;
  g_capabilities.emplace("app_open", std::make_unique<AppOpenCapability>());
  g_capabilities.emplace("app_focus", std::make_unique<AppFocusCapability>());
  g_capabilities.emplace("file_create", std::make_unique<FileCreateCapability>());
  g_capabilities.emplace("file_read", std::make_unique<FileReadCapability>());
  g_capabilities.emplace("file_write", std::make_unique<FileWriteCapability>());
  g_capabilities.emplace("media_control", std::make_unique<MediaControlCapability>());
  // media_bridge（orpheus:// 投递）暂不注册。
  // 2026-08-31 实测：Windows 版网易云客户端不响应 URI 投递——
  //   1) Start-Process("orpheus://song/<id>") 无反应（含官方返回的 jumpUrl）
  //   2) cloudmusic.exe --webcmd="orpheus://song/<id>" 无反应
  //   3) ncm-cli play --player orpheus 明确报"仅支持 macOS"
  // 注册出来只会误导 LLM 调用一个注定失败的工具，故保留实现但不暴露。
  // 若将来客户端开放该能力，取消下行注释即可启用。
  // g_capabilities.emplace("media_bridge", std::make_unique<MediaBridgeCapability>());
  // M4+：process_list / process_kill / terminal_exec / window_screenshot /
  //      mouse_inject / keyboard_inject
}

std::string make_trace_id() {
  // 无 uuid 库：时间戳 + 随机数 组成 trace_id。
  auto now = std::chrono::high_resolution_clock::now().time_since_epoch().count();
  std::random_device rd;
  std::mt19937_64 gen(rd());
  std::string hex = "0123456789abcdef";
  std::string out;
  auto push = [&](uint64_t v, int digits) {
    for (int i = digits - 1; i >= 0; --i) out.push_back(hex[(v >> (i * 4)) & 0xF]);
  };
  push(static_cast<uint64_t>(now), 16);
  out.push_back('-');
  push(gen(), 16);
  return out;
}

// 把 SystemResult 序列化为 JSON，字段名与引擎侧 SystemActionResult 对齐
// （stdout 而非 stdout_text；audit 以字符串 audit_json 内嵌）。
json system_result_to_json(const SystemResult& r) {
  json j = {
      {"trace_id", r.trace_id},
      {"status", r.status},
      {"approval_required", r.approval_required},
      {"approval_request_id", r.approval_request_id},
      {"stdout", r.stdout_text},
      {"artifacts", r.artifacts},
  };
  if (!r.audit_json.empty()) j["audit"] = r.audit_json;
  return j;
}

json make_response(const json& req, json body) {
  json resp = {{"jsonrpc", "2.0"}};
  // jsonrpc 2.0：响应必须回显 id（字符串/数字/空都原样回显）。
  if (req.contains("id")) resp["id"] = req["id"];
  if (body.contains("error")) {
    resp["error"] = body["error"];
  } else {
    resp["result"] = body["result"];
  }
  return resp;
}

std::string handle_request(const std::string& line) {
  ensure_registry();
  json req;
  try {
    req = json::parse(line);
  } catch (const json::parse_error&) {
    json err = {{"jsonrpc", "2.0"}, {"error", {{"code", -32700}, {"message", "parse error"}}}};
    return err.dump();
  }
  if (!req.is_object() || !req.contains("method") || !req["method"].is_string()) {
    json err = {{"jsonrpc", "2.0"}, {"error", {{"code", -32600}, {"message", "invalid request"}}}};
    return err.dump();
  }

  const std::string method = req["method"].get<std::string>();

  if (method == "tools/list") {
    json tools = json::array();
    for (const auto& [name, cap] : g_capabilities) {
      tools.push_back({
          {"name", name},
          {"description", cap->supports_dry_run() ? name + " (supports dry-run)" : name},
          {"approval_required", cap->approval_required()},
          {"dry_run", cap->supports_dry_run()},
      });
    }
    return make_response(req, {{"result", {{"tools", tools}}}}).dump();
  }

  if (method == "tools/call") {
    const json params = req.value("params", json::object());
    const std::string tool_name = params.value("name", "");
    const json args = params.value("arguments", json::object());
    const bool dry_run = params.value("dry_run", false);

    auto it = g_capabilities.find(tool_name);
    if (it == g_capabilities.end()) {
      json err = {{"jsonrpc", "2.0"},
                  {"error", {{"code", -32602}, {"message", "unknown tool: " + tool_name}}}};
      if (req.contains("id")) err["id"] = req["id"];
      return err.dump();
    }

    // 审批由引擎侧 approval_gate 在工具调用前完成；此处直接执行，
    // 并把 approval_required 随结果上报（供审计/状态展示）。
    // 注意：敏感工具的审批拦截绝不能放在 run() 之后——那等于先执行后审批。
    std::string trace_id = make_trace_id();
    SystemResult result = it->second->run(args.dump(), trace_id, dry_run);
    result.approval_required =
        result.approval_required || Policy::requires_approval(tool_name);
    return make_response(req, {{"result", system_result_to_json(result)}}).dump();
  }

  json err = {{"jsonrpc", "2.0"},
              {"error", {{"code", -32601}, {"message", "method not found: " + method}}}};
  if (req.contains("id")) err["id"] = req["id"];
  return err.dump();
}

}  // namespace

int run_stdio_server() {
  std::string line;
  // stdio newline-JSON MCP-like transport：读一行 → 分发 → 写一行响应。
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::cout << handle_request(line) << "\n";
    std::cout.flush();
  }
  return 0;
}

}  // namespace yuiro
