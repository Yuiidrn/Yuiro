"""统一控制台日志：让后端运行终端（uvicorn stdout）清晰看到执行过程。

用法: from yuiro.logger import vlog
      vlog("voice", "ASR 识别: '你好'（440ms）")
输出: [yuiro][voice] ASR 识别: '你好'（440ms）
"""
from __future__ import annotations

import sys
import logging


class StatusPollFilter(logging.Filter):
    """仅隐藏成功的状态轮询；错误、其他端点及业务阶段日志仍保留。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            _, method, target, _, status = args
            return not (method == "GET" and str(target).split("?", 1)[0] == "/api/status"
                        and str(status) == "200")
        return True


def quiet_status_poll_logs() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StatusPollFilter) for f in logger.filters):
        logger.addFilter(StatusPollFilter())


def vlog(source: str, message: str) -> None:
    """打印一条带来源标签的日志到 stdout（立即 flush，uvicorn 终端可见）。"""
    print(f"[yuiro][{source}] {message}", flush=True)
