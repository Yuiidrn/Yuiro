cmake_minimum_required(VERSION 3.20)
project(yuiro CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Windows SDK 可能装在非默认路径（本机装在 D:\Windows Kits\10），
# 通过环境变量 CMAKE_VS_WINSDK_DIR / WindowsSDKDir 指定。
if(WIN32 AND EXISTS "$ENV{WindowsSDKDir}")
  set(CMAKE_VS_WINSDK_DIR "$ENV{WindowsSDKDir}")
  set(WindowsSDKDir "$ENV{WindowsSDKDir}")
  message(STATUS "使用自定义 Windows SDK 路径: ${WindowsSDKDir}")
endif()

# 源文件含中文注释，强制 MSVC 按 UTF-8 读取，避免 C4819 及由此引发的语法错位。
if(MSVC)
  add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:/utf-8>")
endif()

find_package(Threads REQUIRED)
# Optional HTTP/MCP deps (M4): uWebSockets / ASIO can be added when wired.
# For M0 the daemon exposes a stdio newline-JSON MCP-like transport so no
# external libs are required to validate the executable contract.

# ---------------------------------------------------------------------------
# C++/WinRT 投影头生成（供 SMTC 精确媒体控制使用）
#
# Windows SDK 的 Include/<ver>/winrt 目录只有 ABI 头、没有 winrt/base.h，
# 因此必须用 SDK 自带的 cppwinrt.exe 生成 C++/WinRT 投影头。
# 产物落在 build/_winrt（不污染源码树，已被 build/ 一并 gitignore）。
# 找不到 cppwinrt 时优雅降级：不定义 YUIRO_HAS_WINRT，media.cpp 回退媒体键实现。
# ---------------------------------------------------------------------------
set(YUIRO_HAS_WINRT FALSE)
if(WIN32)
  set(_kits_root "$ENV{WindowsSDKDir}")
  if(_kits_root STREQUAL "")
    get_filename_component(_kits_root
      "[HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Windows Kits\\Installed Roots;KitsRoot10]"
      ABSOLUTE)
  endif()
  file(GLOB _cppwinrt_list "${_kits_root}/bin/*/x64/cppwinrt.exe")
  if(_cppwinrt_list)
    list(SORT _cppwinrt_list)
    list(REVERSE _cppwinrt_list)          # 取版本号最高的 SDK
    list(GET _cppwinrt_list 0 YUIRO_CPPWINRT_EXE)
    set(YUIRO_WINRT_DIR "${CMAKE_BINARY_DIR}/_winrt")
    # 只把 base.h 作为生成完成的哨兵（cppwinrt 会产出上千个头文件，无法逐一列举）
    add_custom_command(
      OUTPUT "${YUIRO_WINRT_DIR}/winrt/base.h"
      COMMAND "${YUIRO_CPPWINRT_EXE}" -in local -out "${YUIRO_WINRT_DIR}"
      COMMENT "生成 C++/WinRT 投影头 (cppwinrt -in local)"
      VERBATIM
    )
    add_custom_target(cppwinrt_projection DEPENDS "${YUIRO_WINRT_DIR}/winrt/base.h")
    set(YUIRO_HAS_WINRT TRUE)
    message(STATUS "C++/WinRT: ${YUIRO_CPPWINRT_EXE}")
  else()
    message(STATUS "C++/WinRT: 未找到 cppwinrt.exe，media_control 将回退到全局媒体键")
  endif()
endif()

add_executable(yuiro
  src/main.cpp
  src/capability/process.cpp
  src/capability/files.cpp
  src/capability/terminal.cpp
  src/capability/media.cpp
  src/capability/media_bridge.cpp
  src/security/policy.cpp
  src/mcp/server_stdio.cpp
)

target_include_directories(yuiro PRIVATE include)

# Windows system libs for real OS capabilities (M4+).
if(WIN32)
  target_link_libraries(yuiro PRIVATE shell32 user32)
endif()

if(YUIRO_HAS_WINRT)
  add_dependencies(yuiro cppwinrt_projection)
  target_include_directories(yuiro PRIVATE "${YUIRO_WINRT_DIR}")
  # windowsapp.lib 提供 WinRT (Windows.Media.Control) 的链接符号
  target_link_libraries(yuiro PRIVATE windowsapp.lib)
  target_compile_definitions(yuiro PRIVATE YUIRO_HAS_WINRT=1)
endif()

include(CTest)
if(BUILD_TESTING)
  # 注意：必须把被测实现源文件一并编入测试目标，否则链接期未定义符号。
  add_executable(yuiro_tests tests/test_policy.cpp src/security/policy.cpp)
  target_include_directories(yuiro_tests PRIVATE include)
  if(WIN32)
    target_link_libraries(yuiro_tests PRIVATE shell32 user32)
  endif()
  add_test(NAME policy COMMAND yuiro_tests)
endif()
