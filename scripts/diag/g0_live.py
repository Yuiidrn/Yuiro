"""G0 live CDP inspection; no production imports or credential output."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[2]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True)
    args = parser.parse_args()
    async with httpx.AsyncClient() as client:
        pages = (await client.get("http://127.0.0.1:9222/json/list")).json()
    page = next(p for p in pages if p["type"] == "page" and p["title"] == "Yuiro")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": args.eval, "awaitPromise": True, "returnByValue": True,
            "userGesture": True}}))
        while True:
            reply = json.loads(await ws.recv())
            if reply.get("id") == 1:
                print(json.dumps(reply, ensure_ascii=False))
                break


if __name__ == "__main__":
    asyncio.run(main())
