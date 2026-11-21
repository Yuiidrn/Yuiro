"""Yuiro engine — plugin bridge package.

Brings in my-neuro's impressive dual-language plugin system:

- Python plugins: a Plugin base class with async hooks + a request/response RPC.
- JS plugins can also participate via a bridge talking newline-JSON over
  stdin/stdout with request ids + timeouts (my-neuro python-plugin-bridge.js).
- Plugins fundamentally add function-call tools the LLM can invoke.
"""
from __future__ import annotations

import json
from abc import ABC
from dataclasses import dataclass, field


@dataclass
class PluginContext:
    """Per-plugin context: storage, add_context, helper APIs (my-neuro)."""

    storage: dict = field(default_factory=dict)


class Plugin(ABC):
    """Base class for Python plugins.

    Subclasses implement hooks: on_init, on_user_input, get_tools, execute_tool.
    """

    name: str = ""

    async def on_init(self, ctx: PluginContext) -> None:  # pragma: no cover - stub
        ...

    async def on_user_input(self, text: str, ctx: PluginContext) -> str | None:  # pragma: no cover - stub
        """Optionally inject context into the conversation."""
        ...

    def get_tools(self) -> list[dict]:
        """Return OpenAI tool schemas contributed by this plugin."""
        return []

    async def execute_tool(self, name: str, args: dict) -> str:  # pragma: no cover - stub
        ...


class JSONRPCBridge:
    """stdin/stdout newline-JSON bridge to a subprocess plugin (my-neuro).

    Each message carries an id; responses are matched by id with a timeout.
    """

    def __init__(self, command: list[str], timeout_s: float = 10.0) -> None:
        self.command = command
        self.timeout_s = timeout_s

    async def request(self, method: str, params: dict) -> dict:  # pragma: no cover - stub
        """Send {id, method, params} over stdin; await matching response."""
        ...

    async def start(self) -> None:  # pragma: no cover - stub
        ...

    async def close(self) -> None:  # pragma: no cover - stub
        ...


class PluginManager:
    """Discovers Python plugins (import) and JS plugins (subprocess bridge);
    collects their tools into the ToolRegistry and wires injection hooks.
    """

    def __init__(self, registry) -> None:
        self._registry = registry
        self._plugins: list[Plugin] = []
        self._bridges: list[JSONRPCBridge] = []

    def register_plugin(self, plugin: Plugin) -> None:  # pragma: no cover - stub
        ...

    def list_tools(self) -> list[dict]:  # pragma: no cover - stub
        ...

    async def on_user_input(self, text: str) -> str:  # pragma: no cover - stub
        """Aggregate context injected by all plugins."""
        ...
