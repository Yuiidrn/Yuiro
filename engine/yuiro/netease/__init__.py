"""网易云音乐接入（官方 ncm-cli 封装）。

分层说明：
- 本包负责"调 ncm-cli 拿数据"与"管理后台播放守护进程"，均属服务调用，
  归引擎层职责。
- 播放由 ncm-cli 拉流到 mpv 发声（Windows 上桌面客户端无法被外部唤起：
  `--player orpheus` 明确报"仅支持 macOS"，orpheus:// 投递亦无效）。
"""
from yuiro.netease.client import (
    NcmResult,
    cache_clear,
    check_login,
    daemon_alive,
    ensure_daemon,
    ensure_daemon_ready,
    fetch_login_qr,
    is_available,
    render_qr_png,
    run_ncm,
    run_ncm_cached,
)

__all__ = [
    "NcmResult",
    "check_login",
    "daemon_alive",
    "ensure_daemon",
    "ensure_daemon_ready",
    "fetch_login_qr",
    "is_available",
    "render_qr_png",
    "run_ncm",
    "run_ncm_cached",
    "cache_clear",
]
