// File capabilities (create/read/write) with path-traversal guard.
#include <yuiro/capability/capability.hpp>

#include <string>

namespace yuiro {

// file_create(path, content)：创建文件（父目录自动创建）。
// 路径须在允许目录内（Policy::path_allowed，默认当前工作目录）。
class FileCreateCapability : public Capability {
 public:
  std::string name() const override { return "file_create"; }
  bool approval_required() const override { return true; }
  SystemResult run(const std::string& args_json, const std::string& trace_id,
                   bool dry_run) override;
};

// file_read(path)：读取文本文件内容。
class FileReadCapability : public Capability {
 public:
  std::string name() const override { return "file_read"; }
  bool approval_required() const override { return false; }
  SystemResult run(const std::string& args_json, const std::string& trace_id,
                   bool dry_run) override;
};

// file_write(path, content)：覆盖写文本文件。
class FileWriteCapability : public Capability {
 public:
  std::string name() const override { return "file_write"; }
  bool approval_required() const override { return true; }
  SystemResult run(const std::string& args_json, const std::string& trace_id,
                   bool dry_run) override;
};

}  // namespace yuiro
