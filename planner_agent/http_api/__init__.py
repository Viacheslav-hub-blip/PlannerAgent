"""Опциональный HTTP-слой (FastAPI) поверх ResearchAgent и RunInspectionService.

Требует зависимостей ``[api]`` из pyproject (fastapi, uvicorn). Не включает
фронтенд: при наличии локальной папки ``ui/analyst_ui`` она может быть
подключена как статика (см. ``create_app``).
"""

from __future__ import annotations

from .app import create_app
from .config import ApiServices, ApiSettings, build_api_services

__all__ = ["ApiServices", "ApiSettings", "build_api_services", "create_app"]
