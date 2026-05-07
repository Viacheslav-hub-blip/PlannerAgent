"""Hermes-style tool runtime extracted for reuse in other agents.

The core Hermes ideas copied here:

1. Tools self-register into a central registry.
2. Tool schemas are filtered by availability checks at runtime.
3. Toolsets provide a second layer of surface-area control.
4. Async handlers are bridged safely from sync orchestration code.
5. Dispatch always returns structured error payloads instead of raising.

This module is intentionally independent from Hermes internals and from any
specific LLM framework. It can sit underneath LangChain tools, LangGraph
nodes, or a custom agent loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


ToolHandler = Callable[..., Any]
AvailabilityCheck = Callable[[], bool]


def _json_error(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


_tool_loop: asyncio.AbstractEventLoop | None = None
_tool_loop_lock = threading.Lock()
_worker_thread_local = threading.local()


def _get_tool_loop() -> asyncio.AbstractEventLoop:
    """Return a long-lived event loop for async tool handlers.

    This mirrors Hermes' approach: do not create/close a fresh loop per tool
    call, because cached async clients often bind themselves to the loop.
    """

    global _tool_loop
    with _tool_loop_lock:
        if _tool_loop is None or _tool_loop.is_closed():
            _tool_loop = asyncio.new_event_loop()
        return _tool_loop


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    loop = getattr(_worker_thread_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _worker_thread_local.loop = loop
    return loop


def run_async_safely(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from sync code without loop-lifecycle footguns."""

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running and running.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=300)

    if threading.current_thread() is not threading.main_thread():
        return _get_worker_loop().run_until_complete(coro)

    return _get_tool_loop().run_until_complete(coro)


@dataclass(slots=True)
class ToolDefinition:
    """Single tool registration entry."""

    name: str
    toolset: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler
    availability_check: Optional[AvailabilityCheck] = None
    is_async: bool = False
    requires_env: tuple[str, ...] = field(default_factory=tuple)
    emoji: str = ""
    max_result_size_chars: int | None = None

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def is_available(self) -> bool:
        if self.availability_check is None:
            return True
        try:
            return bool(self.availability_check())
        except Exception:
            logger.debug("Availability check raised for tool %s", self.name, exc_info=True)
            return False


class ToolRegistry:
    """Registry-driven tool runtime suitable for agent frameworks.

    Usage:

        registry = ToolRegistry()

        @registry.tool(
            name="read_notes",
            toolset="notes",
            description="Read the project notes file",
            parameters={"type": "object", "properties": {}},
        )
        def read_notes():
            ...
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._toolsets: Dict[str, set[str]] = {}
        self._toolset_aliases: Dict[str, str] = {}
        self._toolset_descriptions: Dict[str, str] = {}
        self._toolset_checks: Dict[str, AvailabilityCheck] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, definition: ToolDefinition) -> None:
        with self._lock:
            existing = self._tools.get(definition.name)
            if existing and existing.toolset != definition.toolset:
                raise ValueError(
                    f"Tool '{definition.name}' already registered under '{existing.toolset}', "
                    f"cannot shadow it from '{definition.toolset}'."
                )

            self._tools[definition.name] = definition
            self._toolsets.setdefault(definition.toolset, set()).add(definition.name)
            if definition.availability_check and definition.toolset not in self._toolset_checks:
                self._toolset_checks[definition.toolset] = definition.availability_check

    def tool(
        self,
        *,
        name: str,
        toolset: str,
        description: str,
        parameters: Dict[str, Any],
        availability_check: Optional[AvailabilityCheck] = None,
        is_async: bool = False,
        requires_env: Iterable[str] = (),
        emoji: str = "",
        max_result_size_chars: int | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator form of register()."""

        def _decorator(handler: ToolHandler) -> ToolHandler:
            self.register(
                ToolDefinition(
                    name=name,
                    toolset=toolset,
                    description=description,
                    parameters=parameters,
                    handler=handler,
                    availability_check=availability_check,
                    is_async=is_async,
                    requires_env=tuple(requires_env),
                    emoji=emoji,
                    max_result_size_chars=max_result_size_chars,
                )
            )
            return handler

        return _decorator

    def register_toolset(
        self,
        name: str,
        tools: Iterable[str],
        *,
        description: str = "",
        includes: Iterable[str] = (),
        aliases: Iterable[str] = (),
        availability_check: Optional[AvailabilityCheck] = None,
    ) -> None:
        with self._lock:
            tool_names = self._toolsets.setdefault(name, set())
            tool_names.update(tools)
            for included in includes:
                tool_names.update(self.resolve_toolset(included))
            if description:
                self._toolset_descriptions[name] = description
            if availability_check:
                self._toolset_checks[name] = availability_check
            for alias in aliases:
                self._toolset_aliases[alias] = name

    # ------------------------------------------------------------------
    # Surface building
    # ------------------------------------------------------------------

    def resolve_toolset(self, name: str) -> List[str]:
        with self._lock:
            canonical = self._toolset_aliases.get(name, name)
            return sorted(self._toolsets.get(canonical, set()))

    def get_registered_tool_names(self) -> List[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def get_registered_toolsets(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            result: Dict[str, Dict[str, Any]] = {}
            for name, tool_names in self._toolsets.items():
                result[name] = {
                    "description": self._toolset_descriptions.get(name, ""),
                    "tools": sorted(tool_names),
                    "available": self._toolset_available(name),
                }
            return result

    def get_definitions(
        self,
        *,
        enabled_toolsets: Optional[List[str]] = None,
        disabled_toolsets: Optional[List[str]] = None,
        include_tools: Optional[Iterable[str]] = None,
        exclude_tools: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            if enabled_toolsets is not None:
                selected: set[str] = set()
                for toolset_name in enabled_toolsets:
                    selected.update(self.resolve_toolset(toolset_name))
            else:
                selected = set(self._tools.keys())
                for toolset_name in disabled_toolsets or []:
                    selected.difference_update(self.resolve_toolset(toolset_name))

            if include_tools:
                selected.update(include_tools)
            if exclude_tools:
                selected.difference_update(exclude_tools)

            result = []
            for tool_name in sorted(selected):
                definition = self._tools.get(tool_name)
                if definition and definition.is_available():
                    result.append(definition.schema())
            return result

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, tool_name: str, args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        definition = self.get(tool_name)
        if definition is None:
            return _json_error(f"Unknown tool: {tool_name}")
        if not definition.is_available():
            return _json_error(f"Tool '{tool_name}' is currently unavailable.")

        try:
            call_args = args or {}
            if definition.is_async:
                result = run_async_safely(definition.handler(**call_args, **kwargs))
            else:
                result = definition.handler(**call_args, **kwargs)
        except TypeError:
            try:
                # Hermes handlers commonly accept a single args dict; this
                # fallback preserves that ergonomic pattern for portability.
                if definition.is_async:
                    result = run_async_safely(definition.handler(args or {}, **kwargs))
                else:
                    result = definition.handler(args or {}, **kwargs)
            except Exception as exc:
                logger.exception("Tool %s failed", tool_name)
                return _json_error(f"{type(exc).__name__}: {exc}")
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return _json_error(f"{type(exc).__name__}: {exc}")

        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"success": True, "result": result}
        return {"success": True, "result": result}

    def get(self, tool_name: str) -> Optional[ToolDefinition]:
        with self._lock:
            return self._tools.get(tool_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _toolset_available(self, name: str) -> bool:
        check = self._toolset_checks.get(name)
        if check is None:
            return True
        try:
            return bool(check())
        except Exception:
            logger.debug("Toolset availability check raised for %s", name, exc_info=True)
            return False

