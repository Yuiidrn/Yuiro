"""审批端到端测试：连 /ws/control 发系统操作指令，监听审批并立即回传裁决。

验证审批不再因 receive 循环阻塞而超时（队列化修复）。
用法: & .env-local\\engine-venv\\Scripts\\python.exe scripts\\test_approval_e2e.py [--url ws://127.0.0.1:8200/ws/control]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import websockets
except ImportError:  # pragma: no cover
    sys.exit("websockets 未安装")

DEFAULT_URL = "ws://127.0.0.1:8200/ws/control"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--text", default="打开记事本", help="触发 system_action 的指令")
    ap.add_argument("--approve", action="store_true", default=True, help="自动批准（默认）")
    ap.add_argument("--timeout", type=float, default=150.0)
    args = ap.parse_args()

    t0 = time.perf_counter()

    def log(msg: str) -> None:
        print(f"[{time.perf_counter() - t0:6.1f}s] {msg}", flush=True)

    async with websockets.connect(args.url) as ws:
        log(f"已连接 {args.url}，发送: {args.text!r}")
        await ws.send(json.dumps({"type": "chat:user", "text": args.text}, ensure_ascii=False))

        got_approval = False
        final_reply = ""
        deadline = time.perf_counter() + args.timeout
        while time.perf_counter() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.perf_counter())
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "approval:required":
                got_approval = True
                rid = msg.get("request_id", "")
                log(f"收到审批请求: {msg.get('tool')} request={str(rid)[:8]}")
                decision = args.approve
                log(f"→ 立即回传裁决: {'允许' if decision else '拒绝'}")
                await ws.send(json.dumps(
                    {"type": "approval:resolve", "request_id": rid, "approved": decision}
                ))
            elif mtype == "chat:assistant":
                final_reply = str(msg.get("text", ""))
                log(f"收到最终回复: {final_reply[:120]}")
                break

        print("\n===== 结果 =====", flush=True)
        print(f"收到审批请求: {got_approval}", flush=True)
        print(f"最终回复: {final_reply[:200]!r}", flush=True)
        if got_approval and final_reply:
            print("审批端到端链路通过（审批未超时）", flush=True)
            return
        print("链路未完整（见上）", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
