// yuiro SystemDaemon — capability contract.
// Each capability maps to an MCP tool exposed to the Engine (Python).
#pragma once
#include <string>
#include <optional>
#include <vector>

namespace yuiro {

// Unified result returned for every action (mirrors docs/system-daemon.md).
struct SystemResult {
  std::string trace_id;
  std::string status;                 // ok | denied | error | dry-run
  bool approval_required = false;
  std::string approval_request_id;
  std::string stdout_text;
  std::vector<std::string> artifacts; // e.g. screenshot paths
  std::string audit_json;             // {tool, ts, actor, args(redacted)}
};

// Capability base — every OS capability implements run() and a dry-run mode.
class Capability {
public:
  virtual ~Capability() = default;
  virtual std::string name() const = 0;
  virtual bool approval_required() const = 0;
  virtual bool supports_dry_run() const { return true; }
  // Executes the action. dry_run=true never injects input, captures best-effort
  // screenshot for debugging (AIRI computer-use-mcp `dry-run` mode).
  virtual SystemResult run(const std::string& args_json,
                           const std::string& trace_id,
                           bool dry_run) = 0;
};

} // namespace yuiro
