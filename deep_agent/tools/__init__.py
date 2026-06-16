"""LangChain tools, доступные supervisor и специализированным subagents.

Содержит публичные фабрики:
- build_analyze_image_tool: VLM-анализ локальных изображений.
"""

from deep_agent.tools.image_analysis import build_analyze_image_tool

__all__ = ["build_analyze_image_tool"]
