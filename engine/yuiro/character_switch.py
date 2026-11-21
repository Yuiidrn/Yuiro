"""单活跃角色切换事务；不创建第二套 Runtime，不启动服务。"""
from __future__ import annotations

import asyncio
import copy
import time

from yuiro.characters import ROLE_SECTIONS
from yuiro.logger import vlog


class CharacterSwitch:
    def __init__(self, store, cfg, *, prepare, quiesce, activate, notify):
        self.store, self.cfg = store, cfg
        self.prepare, self.quiesce = prepare, quiesce
        self.activate, self.notify = activate, notify
        self.lock = asyncio.Lock()
        self.revision = 0
        self.switching = False

    async def switch(self, role: str) -> dict:
        self.store.check_id(role)
        async with self.lock:
            old_id = self.store.active()
            if role == old_id:
                return self.view()
            started = time.monotonic()
            # 必须先解析/准备；准备失败不打断正在用的角色。
            target = self.store.resolve(role, self.cfg)
            prepared = await self.prepare(role, target)
            old = copy.deepcopy(self.cfg)
            self.switching = True
            try:
                self.store.save(old_id, old)
                await self.quiesce()
                for section in ROLE_SECTIONS:
                    setattr(self.cfg, section, getattr(target, section))
                self.cfg._character_id = role
                await self.activate(role, prepared)
                self.store.commit(role)
            except BaseException:
                for section in ROLE_SECTIONS:
                    setattr(self.cfg, section, getattr(old, section))
                self.cfg._character_id = old_id
                await self.activate(old_id, None)
                vlog("character", f"切换 {old_id} → {role} 失败，已恢复旧配置")
                raise
            finally:
                self.switching = False
            self.revision += 1
            elapsed = round((time.monotonic() - started) * 1000, 2)
            vlog("character", f"切换 {old_id} → {role} 完成，revision={self.revision} {elapsed}ms")
            try:
                await self.notify(role, self.revision)
            except Exception as exc:  # noqa: BLE001 — 提交后通知失败不能伪装成切换未提交
                vlog("character", f"角色已切换，通知失败：{type(exc).__name__}；客户端重连后读取当前配置")
            return {**self.view(), "switch_ms": elapsed}

    def view(self):
        return {**self.store.view(), "revision": self.revision, "switching": self.switching}
