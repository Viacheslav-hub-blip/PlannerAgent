"""Minimal LangChain-compatible tool registry.

The registry stores native ``BaseTool`` objects instead of converting them into
agent-specific schemas. This keeps the integration aligned with LangChain and
LangGraph APIs while giving the research agent a single extension point for
toolsets, enabled subsets, and future policy/audit hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Iterable

from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    toolset: str = "default"
    tags: tuple[str, ...] = field(default_factory=tuple)


class ToolRegistry:
    """Registry for native LangChain tools."""

    def __init__(self, tools: Iterable[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._toolsets: dict[str, set[str]] = {}
        self._lock = RLock()
        if tools:
            self.register_many(tools)

    def register(
            self,
            tool: BaseTool,
            *,
            toolset: str = "default",
            tags: Iterable[str] | None = None,
            replace: bool = False,
    ) -> BaseTool:
        if not isinstance(tool, BaseTool):
            raise TypeError("ToolRegistry only accepts langchain_core.tools.BaseTool instances.")
        if not tool.name:
            raise ValueError("Tool name is required.")

        with self._lock:
            if tool.name in self._tools and not replace:
                raise ValueError(f"Tool already registered: {tool.name}")
            self._tools[tool.name] = tool
            self._toolsets.setdefault(toolset, set()).add(tool.name)
            for tag in tags or ():
                self._toolsets.setdefault(str(tag), set()).add(tool.name)
        return tool

    def register_many(
            self,
            tools: Iterable[BaseTool],
            *,
            toolset: str = "default",
            replace: bool = False,
    ) -> list[BaseTool]:
        return [
            self.register(tool, toolset=toolset, replace=replace)
            for tool in tools
        ]

    def get(self, name: str) -> BaseTool | None:
        with self._lock:
            return self._tools.get(name)

    def get_tool(self, name: str) -> BaseTool | None:
        return self.get(name)

    def list_tools(self) -> list[BaseTool]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools)]

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools)

    def enabled(
            self,
            names: Iterable[str] | None = None,
            *,
            strict: bool = True,
    ) -> list[BaseTool]:
        if names is None:
            return self.list_tools()

        selected: list[BaseTool] = []
        missing: list[str] = []
        with self._lock:
            for name in names:
                tool = self._tools.get(name)
                if tool is None:
                    missing.append(name)
                    continue
                selected.append(tool)

        if strict and missing:
            raise KeyError(f"Unknown tool(s): {', '.join(sorted(missing))}")
        return selected

    def toolset(self, name: str, *, strict: bool = True) -> list[BaseTool]:
        with self._lock:
            tool_names = sorted(self._toolsets.get(name, set()))
        if strict and not tool_names:
            raise KeyError(f"Unknown or empty toolset: {name}")
        return self.enabled(tool_names, strict=strict)

    def toolset_names(self) -> list[str]:
        with self._lock:
            return sorted(self._toolsets)

    def describe(self, names: Iterable[str] | None = None) -> str:
        tools = self.enabled(names) if names is not None else self.list_tools()
        if not tools:
            return "No tools are registered."
        return "\n".join(
            f"- {tool.name}: {tool.description or ''}".rstrip()
            for tool in tools
        )

    def info(self) -> list[ToolInfo]:
        with self._lock:
            tool_to_toolsets: dict[str, list[str]] = {
                name: [] for name in self._tools
            }
            for toolset, names in self._toolsets.items():
                for name in names:
                    if name in tool_to_toolsets:
                        tool_to_toolsets[name].append(toolset)

            return [
                ToolInfo(
                    name=name,
                    description=self._tools[name].description or "",
                    toolset=sorted(tool_to_toolsets[name])[0]
                    if tool_to_toolsets[name]
                    else "default",
                    tags=tuple(sorted(tool_to_toolsets[name])),
                )
                for name in sorted(self._tools)
            ]


__all__ = ["ToolInfo", "ToolRegistry"]
