"""Контракт supervisor-а и subagent data-retrieval аналитического DeepAgent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from deep_agent_test.prompts import DATA_RETRIEVAL_PROMPT
from deep_agent_test.settings import DeepAgentSettings

DATA_RETRIEVAL_AGENT_NAME = "data-retrieval-agent"

DATA_RETRIEVAL_AGENT_DESCRIPTION = (
    "Читает фактические строки данных через read_table по таблицам, которые описаны в skills. "
    "Используй этого subagent-а для выборок по конкретным полям, фильтрам, ключам и периоду. "
    "Не используй его для расчетов, join, отчетов или создания файлов."
)

SubagentStatus = Literal["success", "partial", "empty", "needs_more_input", "schema_error", "error"]


class DataRetrievalResponse(BaseModel):
    """Структурированный ответ data-retrieval-agent для supervisor-а."""

    status: SubagentStatus = Field(description="Статус выполнения шага чтения данных.")
    rows_count: int = Field(default=0, description="Количество найденных строк.")
    tables_used: list[str] = Field(default_factory=list, description="Список реально использованных таблиц.")
    fields_used: list[str] = Field(default_factory=list, description="Список реально использованных полей.")
    filters_used: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Список реально примененных фильтров.",
    )
    period_used: str = Field(default="", description="Период или формулировка точечного поиска.")
    key_values_for_next_step: dict[str, Any] = Field(
        default_factory=dict,
        description="Ключевые значения для следующего шага, выбранные по skills или фактическому результату чтения.",
    )
    missing_required_inputs: list[str] = Field(
        default_factory=list,
        description="Какие обязательные входные значения отсутствуют.",
    )
    limitations: list[str] = Field(default_factory=list, description="Ограничения результата.")
    preview_rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Небольшой preview строк для supervisor-а.",
    )
    summary: str = Field(default="", description="Краткий итог шага на русском языке.")
    target_field_found: bool | None = Field(
        default=None,
        description="Найдено ли целевое поле текущего пользовательского шага в выбранной таблице.",
    )
    routing_keys_found: bool | None = Field(
        default=None,
        description="Удалось ли получить ключи маршрутизации для следующего шага.",
    )

    @model_validator(mode="after")
    def normalize_success_payload(self) -> "DataRetrievalResponse":
        if self.status == "success" and self.rows_count > 0:
            has_non_empty_key_values = _has_non_empty_dict(self.key_values_for_next_step)
            has_non_empty_preview = any(_has_non_empty_dict(row) for row in self.preview_rows)
            if not has_non_empty_key_values and has_non_empty_preview:
                self.key_values_for_next_step = _extract_routing_keys(self.preview_rows)
                has_non_empty_key_values = _has_non_empty_dict(self.key_values_for_next_step)
            if not has_non_empty_key_values or not has_non_empty_preview:
                self.status = "partial"
                if self.routing_keys_found is True and not has_non_empty_key_values:
                    self.routing_keys_found = False
                self.limitations.append(
                    "Structured output subagent-а неполный: отсутствуют фактические "
                    "key_values_for_next_step или preview_rows. Проверь полный read_table output."
                )
        return self


def _extract_routing_keys(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if not _has_non_empty_dict(row):
            continue
        return {key: value for key, value in row.items() if value not in (None, "", [], {}, ())}
    return {}


def _has_non_empty_dict(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(item not in (None, "", [], {}, ()) for item in value.values())


def build_analytics_subagent_specs(
    *,
    settings: DeepAgentSettings,
    data_tools: list[Any],
    common_middleware: list[Any],
) -> list[dict[str, Any]]:
    return [
        {
            "name": DATA_RETRIEVAL_AGENT_NAME,
            "description": DATA_RETRIEVAL_AGENT_DESCRIPTION,
            "system_prompt": DATA_RETRIEVAL_PROMPT,
            "tools": data_tools,
            "skills": [settings.skills_virtual_dir],
            "middleware": common_middleware,
        },
    ]


__all__ = [
    "DATA_RETRIEVAL_AGENT_NAME",
    "DataRetrievalResponse",
    "build_analytics_subagent_specs",
]
