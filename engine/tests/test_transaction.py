"""S33 测试：Tool Transaction（文件操作可回滚）。

规范依据 ``docs/spec/architecture-goal.md`` §3.15 ——
``ToolExecution { dry_run → execute → verify → rollback }``，
"用户：恢复刚才的操作 → rollback(transaction_id)"。

测试用真实临时目录（本机 ``tmp_path`` 不可用，统一 ``tempfile.TemporaryDirectory``），
``file_roots`` 限定在该目录内，避免污染工作区。
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from yuiro.native import NativeBackend
from yuiro.transaction import TxnStore


def _backend(root: str, *, keep: int = 20, enabled: bool = True) -> NativeBackend:
    return NativeBackend(
        file_roots=[root],
        txn_store=TxnStore(os.path.join(root, "txn"), keep=keep) if enabled else None,
        txn_enabled=enabled,
    )


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── 1. 覆盖写 → 回滚还原原内容 ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_overwrite_then_rollback_restores_content() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        _write(path, "原始内容")
        be = _backend(d)

        r = await be.call("file_write", {"path": path, "content": "新内容"})
        assert r.status == "ok"
        assert r.txn_id.startswith("txn-")  # LLM 之后可据此撤销
        assert _read(path) == "新内容"

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert _read(path) == "原始内容"  # ← 核心承诺


# ── 2. 新建 → 回滚 = 删除该文件 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_then_rollback_deletes_new_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "new.txt")
        be = _backend(d)

        assert (await be.call("file_create", {"path": path, "content": "hi"})).status == "ok"
        assert os.path.isfile(path)

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert not os.path.exists(path)


# ── 3. 删除 → 回滚恢复内容 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_then_rollback_restores_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "del.txt")
        _write(path, "别删我")
        be = _backend(d)

        assert (await be.call("file_delete", {"path": path})).status == "ok"
        assert not os.path.exists(path)

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert _read(path) == "别删我"


# ── 4. 批量移动 → 整体回滚（"整理下载夹"场景）────────────────────────────
@pytest.mark.asyncio
async def test_move_batch_rollback_restores_all() -> None:
    with tempfile.TemporaryDirectory() as d:
        src_dir = os.path.join(d, "下载")
        dst_dir = os.path.join(d, "图片")
        os.makedirs(src_dir)
        names = ("1.png", "2.png", "3.png")
        srcs = []
        for n in names:
            p = os.path.join(src_dir, n)
            _write(p, n)
            srcs.append(p)

        be = _backend(d)
        r = await be.call("file_move", {"paths": srcs, "dest": dst_dir})
        assert r.status == "ok", r.stdout
        assert all(os.path.isfile(os.path.join(dst_dir, n)) for n in names)
        assert not any(os.path.exists(p) for p in srcs)

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert all(os.path.isfile(p) for p in srcs)  # 全部移回原位
        assert not any(os.path.isfile(os.path.join(dst_dir, n)) for n in names)


# ── 4b. 撤销"整理到新目录"时，新建的空目录也一并删掉（无残留）────────────
@pytest.mark.asyncio
async def test_rollback_removes_created_dest_dir() -> None:
    """冒烟实测发现：只把文件移回来会留下一个空文件夹，用户看得出残留。"""
    with tempfile.TemporaryDirectory() as d:
        src_dir = os.path.join(d, "下载")
        os.makedirs(src_dir)
        srcs = []
        for n in ("1.png", "2.png"):
            p = os.path.join(src_dir, n)
            _write(p, n)
            srcs.append(p)
        dest = os.path.join(d, "图片")  # 尚不存在 → 由本次操作创建

        be = _backend(d)
        assert (await be.call("file_move", {"paths": srcs, "dest": dest})).status == "ok"
        assert os.path.isdir(dest)

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert all(os.path.isfile(p) for p in srcs)
        assert not os.path.exists(dest)  # ← 新建的空目录也没了


# ── 4c. 本来就存在的目录不会被删（只删本次新建的）───────────────────────
@pytest.mark.asyncio
async def test_rollback_keeps_preexisting_dest_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        src_dir = os.path.join(d, "下载")
        dest = os.path.join(d, "图片")
        os.makedirs(src_dir)
        os.makedirs(dest)  # 用户自己的目录
        srcs = []
        for n in ("1.png", "2.png"):
            p = os.path.join(src_dir, n)
            _write(p, n)
            srcs.append(p)

        be = _backend(d)
        assert (await be.call("file_move", {"paths": srcs, "dest": dest})).status == "ok"
        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert all(os.path.isfile(p) for p in srcs)
        assert os.path.isdir(dest)  # 原有的目录保留（不越界删除用户的东西）


# ── 5. 单文件移动（重命名）→ 回滚 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_single_move_rollback() -> None:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "old.txt")
        dst = os.path.join(d, "renamed.txt")
        _write(src, "x")
        be = _backend(d)

        assert (await be.call("file_move", {"paths": [src], "dest": dst})).status == "ok"
        assert os.path.isfile(dst)

        ok, msg = await be.rollback_transaction("last")
        assert ok, msg
        assert os.path.isfile(src) and not os.path.exists(dst)


# ── 6. 落盘护栏：重启后仍可回滚 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_rollback_survives_restart() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        _write(path, "第一版")

        be1 = _backend(d)
        await be1.call("file_write", {"path": path, "content": "第二版"})
        assert _read(path) == "第二版"

        be2 = _backend(d)  # 新建实例 = 模拟引擎重启（同备份目录）
        ok, msg = await be2.rollback_transaction("last")
        assert ok, msg
        assert _read(path) == "第一版"


# ── 7. 重复回滚被拒 ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_double_rollback_rejected() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        _write(path, "v1")
        be = _backend(d)
        await be.call("file_write", {"path": path, "content": "v2"})

        ok1, _ = await be.rollback_transaction("last")
        ok2, msg2 = await be.rollback_transaction("last")
        assert ok1 is True
        assert ok2 is False
        assert "回滚过" in msg2


# ── 8. 保留策略（keep）──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_keep_prunes_old_transactions() -> None:
    with tempfile.TemporaryDirectory() as d:
        be = _backend(d, keep=2)
        for i in range(3):
            p = os.path.join(d, f"f{i}.txt")
            await be.call("file_create", {"path": p, "content": "x"})

        view = await be.list_transactions(10)
        assert view["keep"] == 2
        assert view["total"] == 2  # 最旧的一个（及其备份）已清理


# ── 9. dry-run 不产生事务 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dry_run_creates_no_transaction() -> None:
    with tempfile.TemporaryDirectory() as d:
        be = _backend(d)
        r = await be.call(
            "file_write", {"path": os.path.join(d, "a.txt"), "content": "x"}, dry_run=True
        )
        assert r.status == "dry-run"
        assert r.txn_id == ""
        assert (await be.list_transactions())["total"] == 0


# ── 10. 失败操作不留下事务 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_failed_write_leaves_no_transaction() -> None:
    with tempfile.TemporaryDirectory() as d:
        be = _backend(d)
        r = await be.call("file_write", {"path": "C:/Windows/evil.txt", "content": "x"})
        assert r.status == "denied"
        view = await be.list_transactions()
        assert view["total"] == 0  # 不留下无法对应的事务


# ── 11. 移动：目标已存在不覆盖，且整体不动手 ─────────────────────────────
@pytest.mark.asyncio
async def test_move_rejects_existing_target() -> None:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.txt")
        dst = os.path.join(d, "b.txt")
        _write(src, "src")
        _write(dst, "dst")
        be = _backend(d)

        r = await be.call("file_move", {"paths": [src], "dest": dst})
        assert r.status == "error"
        assert "已存在" in r.stdout
        assert _read(src) == "src" and _read(dst) == "dst"  # 两边都没动


# ── 12. 批量移动：目录不存在会自动创建；把文件当目录则拒绝 ───────────────
@pytest.mark.asyncio
async def test_move_batch_creates_missing_dest_dir() -> None:
    """目标目录不存在 → 自动创建（"整理下载夹，建个图片目录"是主场景）。"""
    with tempfile.TemporaryDirectory() as d:
        srcs = []
        for n in ("a.txt", "b.txt"):
            p = os.path.join(d, n)
            _write(p, n)
            srcs.append(p)
        dest = os.path.join(d, "新建目录")
        be = _backend(d)

        r = await be.call("file_move", {"paths": srcs, "dest": dest})
        assert r.status == "ok", r.stdout
        assert all(os.path.isfile(os.path.join(dest, n)) for n in ("a.txt", "b.txt"))


@pytest.mark.asyncio
async def test_move_batch_rejects_file_as_dest() -> None:
    with tempfile.TemporaryDirectory() as d:
        srcs = []
        for n in ("a.txt", "b.txt", "c.txt"):
            p = os.path.join(d, n)
            _write(p, n)
            srcs.append(p)
        not_a_dir = os.path.join(d, "其实是个文件.txt")
        _write(not_a_dir, "x")
        be = _backend(d)

        r = await be.call("file_move", {"paths": srcs, "dest": not_a_dir})
        assert r.status == "error"
        assert all(os.path.isfile(p) for p in srcs)  # 一个都没动


# ── 13. 回滚部分失败 → partial（如实报告，不静默）────────────────────────
@pytest.mark.asyncio
async def test_partial_rollback_when_original_slot_occupied() -> None:
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.txt")
        dst = os.path.join(d, "b.txt")
        _write(src, "move-me")
        be = _backend(d)
        await be.call("file_move", {"paths": [src], "dest": dst})

        _write(src, "别人占了这个位置")  # 外部改动：原位置被占

        ok, msg = await be.rollback_transaction("last")
        assert ok is False
        assert "原位置已有同名文件" in msg
        assert _read(src) == "别人占了这个位置"  # 不覆盖外部改动（保守）
        assert _read(dst) == "move-me"  # 也没丢


# ── 14. 目录不可删除 ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_delete_rejects_directory() -> None:
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "sub")
        os.makedirs(sub)
        be = _backend(d)
        r = await be.call("file_delete", {"path": sub})
        assert r.status == "error"
        assert os.path.isdir(sub)


# ── 15. 事务视图形状（调试台 / 工具共用）────────────────────────────────
@pytest.mark.asyncio
async def test_transaction_view_shape() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        be = _backend(d)
        await be.call("file_create", {"path": path, "content": "x"})

        view = await be.list_transactions()
        assert {"root", "keep", "total", "reversible", "recent"} <= set(view)
        rec = view["recent"][0]
        assert {"id", "tool", "ops", "status", "summary", "reversible"} <= set(rec)
        assert rec["tool"] == "file_create"
        assert rec["reversible"] is True


# ── 16. 工具层接线（LLM 说"恢复刚才的操作"走的就是这条）──────────────────
@pytest.mark.asyncio
async def test_rollback_tool_end_to_end() -> None:
    from yuiro.tools.system_tool import TransactionListTool, TransactionRollbackTool

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        _write(path, "原始")
        be = _backend(d)
        await be.call("file_write", {"path": path, "content": "改过"})

        listed = await TransactionListTool(backend=be).run({}, "t1")
        assert "txn-" in listed

        result = await TransactionRollbackTool(backend=be).run({"txn_id": ""}, "t1")
        payload = json.loads(result)
        assert payload["status"] == "ok", result
        assert _read(path) == "原始"


# ── 17. enabled=false：工具照常工作，只是不可回滚（明确报错，不静默）──────
@pytest.mark.asyncio
async def test_disabled_transaction_still_works_but_reports() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "a.txt")
        be = _backend(d, enabled=False)

        r = await be.call("file_create", {"path": path, "content": "x"})
        assert r.status == "ok"  # 文件操作本身不受影响
        assert r.txn_id == ""  # 只是没有事务
        assert os.path.isfile(path)

        ok, msg = await be.rollback_transaction("last")
        assert ok is False
        assert "未启用" in msg
