"""S38 测试：整理能力（file_list / 移动语义 / 结构化结果）。

三个都是**真实验收暴露的问题**的护栏：
1. 没有 file_list → "整理文件夹"连第一步"看清有什么"都做不到；
2. `_plan_moves` 把"无扩展名的 dest"当成重命名 → .xls 变成叫「表格文件」的无扩展名文件；
3. 工具结果被二次 JSON 转义 → 长度翻倍、更易截断、模型要解两层（实测读不到清单）。
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from yuiro.native import ops
from yuiro.native.backend import _plan_moves


# ── 1. 移动语义：无扩展名的 dest 是目录（不是重命名）──────────────────────
def test_bare_dest_is_directory_not_rename() -> None:
    """修前：`a.xls → D:\\t\\表格文件` 被当成重命名，xls 变成了无扩展名文件。"""
    moves, as_dir = _plan_moves([r"D:\t\a.xls"], r"D:\t\表格文件")
    assert as_dir is True
    assert moves == [(r"D:\t\a.xls", os.path.join(r"D:\t\表格文件", "a.xls"))]


def test_dest_with_extension_is_rename() -> None:
    moves, as_dir = _plan_moves([r"D:\t\a.txt"], r"D:\t\b.txt")
    assert as_dir is False
    assert moves == [(r"D:\t\a.txt", r"D:\t\b.txt")]


def test_multi_files_always_treated_as_directory() -> None:
    moves, as_dir = _plan_moves([r"D:\t\a.txt", r"D:\t\b.txt"], r"D:\t\新目录")
    assert as_dir is True
    assert len(moves) == 2
    assert moves[0][1] == os.path.join(r"D:\t\新目录", "a.txt")


def test_trailing_separator_means_directory() -> None:
    _, as_dir = _plan_moves([r"D:\t\a.txt"], r"D:\t\新目录\\")
    assert as_dir is True


# ── 2. file_list：列目录 ──────────────────────────────────────────────────
def test_file_list_returns_files_sorted_by_size() -> None:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "big.pdf"), "w", encoding="utf-8") as f:
            f.write("x" * 100)
        with open(os.path.join(d, "small.txt"), "w", encoding="utf-8") as f:
            f.write("y")
        os.makedirs(os.path.join(d, "sub"))

        status, out = ops.file_list(d, [d])
        assert status == "ok"
        data = json.loads(out)
        assert data["count"] == 2
        assert data["dirs"] == ["sub"]
        assert data["files"][0]["name"] == "big.pdf"  # 大小降序 → 大件先看到
        assert data["files"][0]["ext"] == ".pdf"
        assert data["truncated"] is False


def test_file_list_pattern_filter() -> None:
    with tempfile.TemporaryDirectory() as d:
        for name in ("a.pdf", "b.txt", "c.PDF"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("x")
        _, out = ops.file_list(d, [d], pattern="*.pdf")
        names = [f["name"] for f in json.loads(out)["files"]]
        assert "a.pdf" in names and "b.txt" not in names
        # Windows 上 fnmatch 走平台语义（不区分大小写）→ c.PDF 也命中；Linux 上则不会
        if os.name == "nt":
            assert "c.PDF" in names


def test_file_list_recursive_includes_subdirs() -> None:
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "deep.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        _, out = ops.file_list(d, [d], recursive=True)
        names = [f["name"] for f in json.loads(out)["files"]]
        assert any("deep.txt" in n for n in names)


def test_file_list_rejects_out_of_roots() -> None:
    status, out = ops.file_list(r"C:\Windows", [r"D:\somewhere"])
    assert status == "denied"
    assert "不在允许目录内" in out


def test_file_list_rejects_non_directory() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        status, out = ops.file_list(path, [d])
        assert status == "error"
        assert "只用于列目录" in out


# ── 3. 结构化结果解包（不再二次 JSON 转义）────────────────────────────────
@pytest.mark.asyncio
async def test_invoke_unwraps_structured_stdout() -> None:
    """工具返回的 JSON 应**扁平**呈现：count/files 直接可见，无 stdout 层。

    修前是 `{"status":"ok","stdout":"{\\"count\\":3,...}"}` —— 长度翻倍（一半是转义符），
    更容易撞上 tool_result_max_chars 被截断，模型还得解两层 JSON。
    """
    from yuiro.systemd.client import SystemActionResult
    from yuiro.tools.system_tool import FileListTool

    class _Backend:
        async def call(self, tool, args, dry_run=False):  # noqa: ARG002
            return SystemActionResult(
                trace_id="t-1",
                status="ok",
                stdout=json.dumps({"status": "ok", "count": 3, "files": [{"name": "a"}]}),
            )

    tool = FileListTool(backend=_Backend())
    payload = json.loads(await tool.run({"path": "D:/x"}, "t1"))
    assert payload["count"] == 3
    assert payload["files"][0]["name"] == "a"
    assert "stdout" not in payload  # 不再包一层
    assert "trace_id" not in payload  # 结构化结果里它是噪音


@pytest.mark.asyncio
async def test_invoke_keeps_plain_text_as_stdout() -> None:
    """非结构化输出仍走 stdout（不误当 JSON 解析）。"""
    from yuiro.systemd.client import SystemActionResult
    from yuiro.tools.system_tool import OpenAppTool

    class _Backend:
        async def call(self, tool, args, dry_run=False):  # noqa: ARG002
            return SystemActionResult(trace_id="t-2", status="ok", stdout='已打开 "notepad"')

    payload = json.loads(await OpenAppTool(backend=_Backend()).run({"name": "notepad"}, "t1"))
    assert payload["stdout"] == '已打开 "notepad"'
    assert payload["trace_id"] == "t-2"


@pytest.mark.asyncio
async def test_invoke_passes_through_txn_id() -> None:
    """S33 的事务 id 仍要透传（解包不能把它吃掉）。"""
    from yuiro.systemd.client import SystemActionResult
    from yuiro.tools.system_tool import FileWriteTool

    class _Backend:
        async def call(self, tool, args, dry_run=False):  # noqa: ARG002
            return SystemActionResult(
                trace_id="t-3",
                status="ok",
                stdout=json.dumps({"status": "ok", "wrote": "a.txt"}),
                txn_id="txn-abc-123",
            )

    payload = json.loads(await FileWriteTool(backend=_Backend()).run(
        {"path": "D:/x/a.txt", "content": "hi"}, "t1"
    ))
    assert payload["txn_id"] == "txn-abc-123"
    assert payload["wrote"] == "a.txt"
    assert "rollback_hint" in payload
