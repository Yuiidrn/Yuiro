// Security model: two-layer approval + dry-run sandbox + audit.
// Reflects docs/system-daemon.md §4.
#pragma once
#include <string>

namespace yuiro {

enum class ApprovalMode { NativeDialog, AutoGrant, Deny };

class Policy {
public:
  // Declare whether an action needs approval at the capability level.
  static bool requires_approval(const std::string& tool);

  // Check a file path is inside an allowed base (path-traversal guard).
  static bool path_allowed(const std::string& path,
                           const std::string& allowed_base);

  // Redact sensitive args (e.g. passwords) before auditing.
  static std::string redact(const std::string& args_json);

  static ApprovalMode mode();
};

} // namespace yuiro
