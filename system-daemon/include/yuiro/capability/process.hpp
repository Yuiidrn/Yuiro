// Process / app capabilities (WinAPI: ShellExecute, EnumWindows).
#include <yuiro/capability/capability.hpp>

namespace yuiro {

class AppOpenCapability : public Capability {
public:
  std::string name() const override { return "app_open"; }
  bool approval_required() const override { return false; }
  SystemResult run(const std::string& args_json, const std::string& trace_id,
                   bool dry_run) override;
};

class AppFocusCapability : public Capability {
public:
  std::string name() const override { return "app_focus"; }
  bool approval_required() const override { return false; }
  SystemResult run(const std::string& args_json, const std::string& trace_id,
                   bool dry_run) override;
};

// M4: full WinAPI implementations.

} // namespace yuiro
