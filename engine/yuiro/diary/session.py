"""日记模式会话（S51）：草稿累积 + 吐槽门控 + 极简控制意图。

设计：`docs/features/diary-feature-design.md` §2.1 / §2.2 / §8.1。

★ **为什么不走 AgentLoop**（§2.2 的硬理由，第一条是决定性的）：

预路由对"裸名词命中应用名白名单（记事本/微信/Excel/浏览器…）"是**确定性触发
`app_open`，完全不经 LLM**。日记里写"今天用记事本记了点东西"会**真的把记事本打开**；
且一旦 `tool_ran`，本轮还会顺带写入记忆，绕过 §3.2 的显式授权。

其余三条：语义错位（日记不是"对她说的话"）、上下文/history 污染、延迟。

两条必须澄清的边界：
- **不走 AgentLoop ≠ 不用 LLM**：解构/吐槽/总评都要 LLM，走独立一次性调用；
- **"防自动写记忆"不是理由**（修正）：`memory_writer` 仅在 `tool_ran` 时被调用，
  纯文本轮不写 L2。真正的风险是第一条引起的**间接写入**。

控制意图（§2.2 的缺口补丁）：不做完整解析，但"退出/删掉刚才/看看我上周写的"
这类指令不能被当成正文 → 需要**极简识别**，且**未被识别的一律视为正文**
（宁可漏判控制，也不误判正文）。
"""
from __future__ import annotations

from uuid import uuid4

from yuiro.diary import PRIVACY_ALL, PRIVACY_LOCAL_ONLY
from yuiro.logger import vlog

#: 控制指令线索（必须**短**才认 —— 长句里的"写完了"是正文，不是指令）。
_CONTROL_MAX_CHARS = 12
_CONTROL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("exit", ("退出日记", "结束日记", "不写了", "写好了", "写完了", "记完了")),
    ("undo", ("删掉刚才", "删掉这句", "撤销刚才", "重写刚才", "刚才不算")),
    ("recall", ("看看我", "翻翻我", "我上周", "我之前写", "最近写的日记")),
)


def detect_control_intent(text: str) -> str | None:
    """识别极简控制意图，返回 ``exit`` / ``undo`` / ``recall``；否则 None。

    ★ 保守优先：**只有很短的输入**才可能被判成指令（长句一律当正文）。
    宁可漏判（用户再点一次按钮），也不能把日记正文误当指令丢掉。
    """
    t = (text or "").strip().rstrip("。.!！?？~～")
    if not t or len(t) > _CONTROL_MAX_CHARS:
        return None
    for intent, hints in _CONTROL_RULES:
        if any(h in t for h in hints):
            return intent
    return None


class DiarySession:
    """一次"写日记"过程的状态（草稿 / 段落 / 吐槽门控）。"""

    def __init__(self, *, service=None, quip=None) -> None:
        self._service = service
        self._quip = quip
        self._segments: list[str] = []
        self.segment_ids: list[str] = []
        self.active = False
        self._revision = 0
        self._saving = False
        #: 审阅态（§2.1）：先解构、**不落库**，等用户确认后再存。
        self._pending: dict | None = None

    # ---- 生命周期 -----------------------------------------------------------
    def start(self) -> None:
        self.active = True
        self._pending = None
        self._revision += 1
        self._segments.clear()
        self.segment_ids.clear()
        if self._quip is not None:
            self._quip.gate.reset()  # 不继承上次的节流状态

    def reset(self) -> None:
        self.active = False
        self._pending = None
        self._revision += 1
        self._segments.clear()
        self.segment_ids.clear()
        if self._quip is not None:
            self._quip.gate.reset()

    # ---- 草稿 ---------------------------------------------------------------
    def append(self, text: str) -> str:
        """追加一段草稿（多段保持独立 —— 解构时按"时间连续的生活片段"呈现）。"""
        t = (text or "").strip()
        if t:
            if self._saving:
                raise RuntimeError("保存中，请等待完成后再追加")
            self._pending = None
            self._revision += 1
            self._segments.append(t)
            self.segment_ids.append(uuid4().hex)
        return self.draft()

    def undo(self) -> str:
        """删掉最后一段（"删掉刚才那句"）。"""
        if self._saving:
            raise RuntimeError("保存中，请等待完成后再撤销")
        if self._segments:
            self._pending = None
            self._revision += 1
            self._segments.pop()
            self.segment_ids.pop()
        return self.draft()

    def draft(self) -> str:
        return "\n\n".join(self._segments)

    @property
    def segments(self) -> list[str]:
        return list(self._segments)

    # ---- 吐槽（§8.1：可选、低频、可随时闭嘴）--------------------------------
    async def maybe_quip(self, idle_s: float, *, text: str | None = None) -> str | None:
        """按门控决定要不要说一句。**失败/不该说都返回 None**（调用方静默）。"""
        if self._quip is None or not self.active or self._saving:
            return None
        latest = text if text is not None else (self._segments[-1] if self._segments else "")
        revision = self._revision
        try:
            result = await self._quip.maybe_quip(latest, idle_s=idle_s)
            return result if revision == self._revision and self.active else None
        except Exception as exc:  # noqa: BLE001 — 吐槽绝不能干扰写日记
            vlog("diary", f"[吐槽] 异常（静默）：{type(exc).__name__}: {exc}")
            return None

    # ---- 提交与审阅态（§2.1）------------------------------------------------
    async def preview(self) -> dict:
        """先解构**不落库**，返回"原文 ↔ 润色稿"对照供用户审阅（§2.1 审阅编辑态）。

        ⚠ 解构只是**辅助**：用户看到的原文始终保留，且可以直接选"存原文"。
        """
        if self._service is None:
            return {"ok": False, "note": "日记功能未启用"}
        text = self.draft()
        if not text:
            return {"ok": False, "note": "还没有内容"}
        revision = self._revision
        data = await self._service.deconstruct(text)
        if revision != self._revision:
            return {"ok": False, "note": "草稿已变化，请重新审阅"}
        self._pending = {"raw_text": text, "data": data}
        return {
            "ok": True,
            "raw_text": text,
            "polished_text": str(data.get("polished_text") or text),
            "deconstructed": bool(data),
        }

    async def confirm(
        self,
        *,
        privacy: str = PRIVACY_LOCAL_ONLY,
        quip_mode: bool = False,
        use_polished: bool = True,
    ) -> dict:
        """用户确认审阅稿 → 落库。

        ``use_polished=False``（"存原文"）时丢弃润色稿，**但保留**解构出的
        summary/标签（它们只是索引，不改用户的话）。确认后会话复位。
        """
        if self._service is None:
            return {"ok": False, "note": "日记功能未启用"}
        if privacy not in PRIVACY_ALL:
            return {"ok": False, "note": f"未知隐私档位：{privacy}"}
        pending = self._pending
        if self._saving:
            return {"ok": False, "note": "正在保存，请勿重复提交"}
        if pending is None:  # 没走过审阅（直接提交）→ 退回普通提交
            return await self.submit(privacy=privacy, quip_mode=quip_mode)
        text = str(pending.get("raw_text") or "")
        data = dict(pending.get("data") or {})
        if not use_polished:
            data.pop("polished_text", None)  # 保留 summary/标签，只丢润色稿
        self._saving = True
        try:
            res = await self._service.submit(text, privacy=privacy, quip_mode=quip_mode, data=data)
            if res.get("ok"):
                self.reset()
            return res
        finally:
            self._saving = False

    async def save_raw(self, *, privacy: str = PRIVACY_LOCAL_ONLY, metadata: dict | None = None) -> dict:
        """显式保存原文，不调用解构/润色；共享记忆仍须用户选择。"""
        if self._service is None:
            return {"ok": False, "note": "日记功能未启用"}
        if privacy not in PRIVACY_ALL:
            return {"ok": False, "note": "未知保存范围"}
        if self._saving:
            return {"ok": False, "note": "正在保存，请勿重复提交"}
        text = self.draft()
        if not text and not (metadata and (metadata.get("title") or metadata.get("attachment_ids"))):
            return {"ok": False, "note": "还没有内容"}
        self._saving = True
        try:
            res = await self._service.submit(text, privacy=privacy, quip_mode=False, data=metadata or {})
            if res.get("ok"):
                self.reset()
            return res
        finally:
            self._saving = False

    async def submit(self, *, privacy: str = PRIVACY_LOCAL_ONLY, quip_mode: bool = False) -> dict:
        """直接提交整篇（原文 = 多段拼接；不经审阅态）。提交后会话复位。"""
        if self._service is None:
            return {"ok": False, "note": "日记功能未启用"}
        if privacy not in PRIVACY_ALL:
            return {"ok": False, "note": f"未知隐私档位：{privacy}"}
        text = self.draft()
        if not text:
            return {"ok": False, "note": "还没有内容"}
        if self._saving:
            return {"ok": False, "note": "正在保存，请勿重复提交"}
        self._saving = True
        try:
            res = await self._service.submit(text, privacy=privacy, quip_mode=quip_mode)
            if res.get("ok"):
                self.reset()
            return res
        finally:
            self._saving = False
