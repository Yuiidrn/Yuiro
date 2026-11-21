"""连运行中引擎 /ws/control 实测裸名词泛化：自动批准审批，观察工具是否执行。"""
import asyncio
import json
import sys

import websockets


async def ask(ws: object, text: str) -> None:
    await ws.send(json.dumps({"type": "chat:user", "text": text}))
    print(f"\n[ws] >>> {text!r}")
    for _ in range(20):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=25)
        except asyncio.TimeoutError:
            print("[ws] 超时无响应")
            return
        data = json.loads(raw)
        mtype = data.get("type")
        if mtype == "approval:required":
            rid = data.get("request_id")
            print(f"[ws] 收到审批请求({data.get('tool')}), 自动批准")
            await ws.send(json.dumps({"type": "approval:resolve",
                                      "request_id": rid, "approved": True}))
        elif mtype == "chat:assistant":
            print(f"[ws] <<< {data.get('text')!r}")
            return


async def main():
    cases = sys.argv[1:] or ["记事本。", "网易云音乐。"]
    uri = "ws://127.0.0.1:8200/ws/control"
    async with websockets.connect(uri) as ws:
        for t in cases:
            await ask(ws, t)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
