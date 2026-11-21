#include <yuiro/security/policy.hpp>
#include <filesystem>
#include <unordered_set>

namespace yuiro {

bool Policy::requires_approval(const std::string& tool) {
  // Deterministic actions run without approval; destructive/input-injecting
  // actions require approval. "Deterministic first, coordinate last"
  // (AIRI computer-use-mcp philosophy).
  static const std::unordered_set<std::string> kSensitive = {
    "process_kill", "terminal_exec", "file_write", "file_create",
    "mouse_inject", "keyboard_inject",
  };
  return kSensitive.count(tool) > 0;
}

bool Policy::path_allowed(const std::string& path,
                          const std::string& allowed_base) {
  // 路径穿越防护：weakly_canonical 归一化后逐段比较，path 必须位于 base 内。
  // 相比前缀匹配，可防 ``C:/safe_evil``、``..``、大小写/分隔符差异绕过。
  try {
    namespace fs = std::filesystem;
    // 先 absolute 再 weakly_canonical：MinGW 的 weakly_canonical 不会把
    // 相对路径（尤其不存在的）拼接 current_path，需显式绝对化。
    fs::path p = fs::weakly_canonical(fs::absolute(path));
    fs::path base = fs::weakly_canonical(fs::absolute(allowed_base));
    auto pit = p.begin();
    for (auto bit = base.begin(); bit != base.end(); ++bit, ++pit) {
      if (pit == p.end() || *pit != *bit) return false;
    }
    return true;
  } catch (const std::exception&) {
    return false;  // 路径无效（归一化失败）→ 拒绝
  }
}

std::string Policy::redact(const std::string& args_json) {
  // M4: strip known secret keys (password, token, key) from JSON.
  return args_json;
}

ApprovalMode Policy::mode() { return ApprovalMode::NativeDialog; }

} // namespace yuiro
