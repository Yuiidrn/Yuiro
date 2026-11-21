"""Native 执行后端（S10）：系统操作的 Python 原生实现。

替代 C++ SystemDaemon 成为默认执行后端（daemon 保留为可选：
``[systemd].backend = "native" | "daemon"``）。

- ``ops``：6 个操作的实现（Windows API via ctypes + 标准库 + PowerShell 桥）；
- ``NativeBackend``：与 ``SystemDaemonClient`` 同签名的 ``call(tool, args, dry_run)``。

规范：``docs/plan/S10-native-system-backend.md``。
"""
from yuiro.native.backend import NativeBackend

__all__ = ["NativeBackend"]
