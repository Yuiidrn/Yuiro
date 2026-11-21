"""Artifact 工具（S09）：按需回读被存入 artifact 的大结果。

与 S06 的截断配合：工具结果超长 → 存 artifact + 返回摘要与 id →
LLM 需要细节时调用 ``artifact_read`` 读回完整内容（默认前 2000 字符，可分片续读）。
"""
from __future__ import annotations

import json

from yuiro.tools import BaseTool


class ArtifactReadTool(BaseTool):
    name = "artifact_read"
    approval_required = False
    description = (
        "读取此前因过长被存入 artifact 的工具结果完整内容。"
        "当某个工具返回里出现「已存入 artifact：art_xxxxxx」而你还需更多细节时，"
        "用本工具读取；start/length 指定字符区间（默认前 2000 字符），"
        "返回里会提示「还有 N 字符未显示」，可继续读取下一段。"
    )

    def __init__(self, store=None) -> None:
        self._store = store

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "artifact id（art_xxxxxx）",
                        },
                        "start": {
                            "type": "integer",
                            "description": "起始字符位置（默认 0）",
                        },
                        "length": {
                            "type": "integer",
                            "description": "读取长度（默认 2000 字符）",
                        },
                    },
                    "required": ["artifact_id"],
                },
            },
        }

    async def run(self, args: dict, task_id: str) -> str:
        del task_id
        if self._store is None:
            return json.dumps(
                {"status": "pending", "note": "ArtifactStore 未注入"}, ensure_ascii=False
            )
        aid = str(args.get("artifact_id", "")).strip()
        if not aid:
            return json.dumps(
                {"status": "error", "note": "artifact_id 不能为空"}, ensure_ascii=False
            )
        art = self._store.get(aid)
        if art is None:
            # S35：模型会凭印象编造 id（实测得到 art_9f8e7d6c5b4a3210 这种）——因为 artifact id
            # 只存在于**当轮**的 tool 消息里，跨轮就没了。这里明确引导"重新调原工具"。
            return json.dumps(
                {
                    "status": "error",
                    "note": (
                        f"artifact 不存在或已清理: {aid}。"
                        "artifact 只保留最近若干条工具结果，且 id 不跨轮记忆——"
                        "不要凭印象编造 id；如需最新内容，请重新调用产生该结果的工具"
                        "（例如重新搜索、重新拉歌单）。"
                    ),
                },
                ensure_ascii=False,
            )
        try:
            start = int(args.get("start", 0) or 0)
            length = int(args.get("length", 2000) or 2000)
        except (TypeError, ValueError):
            return json.dumps(
                {"status": "error", "note": "start/length 必须是整数"}, ensure_ascii=False
            )
        text = self._store.read_slice(aid, start, length)
        end = start + len(text)
        more = max(0, art.size - end)
        note = f"还有 {more} 字符未显示" + (f"，可继续读 start={end}" if more > 0 else "")
        return json.dumps(
            {
                "status": "ok",
                "artifact_id": aid,
                "name": art.name,
                "start": start,
                "end": end,
                "total": art.size,
                "content": text,
                "note": note,
            },
            ensure_ascii=False,
        )


ARTIFACT_TOOLS = [ArtifactReadTool]
