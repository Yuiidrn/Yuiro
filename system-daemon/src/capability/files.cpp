// File capabilities implementation (std::filesystem + Policy::path_allowed).
#include <yuiro/capability/files.hpp>

#include <third_party/json.hpp>

#include <yuiro/security/policy.hpp>

#include <filesystem>
#include <fstream>
#include <string>

namespace yuiro {

namespace {
using json = nlohmann::json;

// 允许的文件操作根目录：当前工作目录（daemon 由引擎在 engine/ 下 spawn）。
std::filesystem::path allowed_base() {
  return std::filesystem::current_path();
}

// 解析参数并校验 path 在允许目录内；失败时填充 SystemResult 并返回 false。
bool parse_path(const std::string& args_json, const std::string& trace_id,
                std::string& path_out, std::string& content_out,
                SystemResult& r) {
  r.trace_id = trace_id;
  json args = json::parse(args_json, nullptr, false);
  if (args.is_discarded() || !args.is_object() || !args.contains("path") ||
      !args["path"].is_string()) {
    r.status = "error";
    r.stdout_text = "参数错误：需要 {\"path\": \"<路径>\"}";
    return false;
  }
  path_out = args["path"].get<std::string>();
  if (args.contains("content") && args["content"].is_string()) {
    content_out = args["content"].get<std::string>();
  }
  // 路径穿越防护：必须位于允许目录内。
  if (!Policy::path_allowed(path_out, allowed_base().string())) {
    r.status = "denied";
    r.stdout_text = "路径不在允许目录内，已拒绝: " + path_out;
    return false;
  }
  return true;
}
}  // namespace

SystemResult FileCreateCapability::run(const std::string& args_json,
                                       const std::string& trace_id,
                                       bool dry_run) {
  SystemResult r;
  std::string path, content;
  if (!parse_path(args_json, trace_id, path, content, r)) return r;

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将创建文件 \"" + path + "\"";
    return r;
  }

  try {
    std::filesystem::path p(path);
    if (p.parent_path() != std::filesystem::path() &&
        !std::filesystem::exists(p.parent_path())) {
      std::filesystem::create_directories(p.parent_path());
    }
    std::ofstream out(p, std::ios::binary);
    if (!out) {
      r.status = "error";
      r.stdout_text = "无法创建文件: " + path;
      return r;
    }
    out << content;
    out.close();
    r.status = "ok";
    r.stdout_text = "已创建文件: " + path + "（" + std::to_string(content.size()) + " 字节）";
    r.audit_json = "{\"tool\":\"file_create\",\"path\":\"" + path + "\"}";
  } catch (const std::exception& e) {
    r.status = "error";
    r.stdout_text = std::string("创建失败: ") + e.what();
  }
  return r;
}

SystemResult FileReadCapability::run(const std::string& args_json,
                                     const std::string& trace_id,
                                     bool dry_run) {
  SystemResult r;
  std::string path, content;
  if (!parse_path(args_json, trace_id, path, content, r)) return r;

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将读取文件 \"" + path + "\"";
    return r;
  }

  try {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
      r.status = "error";
      r.stdout_text = "无法读取文件: " + path;
      return r;
    }
    std::string body((std::istreambuf_iterator<char>(in)),
                     std::istreambuf_iterator<char>());
    r.status = "ok";
    r.stdout_text = body;
  } catch (const std::exception& e) {
    r.status = "error";
    r.stdout_text = std::string("读取失败: ") + e.what();
  }
  return r;
}

SystemResult FileWriteCapability::run(const std::string& args_json,
                                      const std::string& trace_id,
                                      bool dry_run) {
  SystemResult r;
  std::string path, content;
  if (!parse_path(args_json, trace_id, path, content, r)) return r;

  if (dry_run) {
    r.status = "dry-run";
    r.stdout_text = "dry-run：将写入文件 \"" + path + "\"";
    return r;
  }

  try {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
      r.status = "error";
      r.stdout_text = "无法写入文件: " + path;
      return r;
    }
    out << content;
    out.close();
    r.status = "ok";
    r.stdout_text = "已写入文件: " + path + "（" + std::to_string(content.size()) + " 字节）";
    r.audit_json = "{\"tool\":\"file_write\",\"path\":\"" + path + "\"}";
  } catch (const std::exception& e) {
    r.status = "error";
    r.stdout_text = std::string("写入失败: ") + e.what();
  }
  return r;
}

}  // namespace yuiro
