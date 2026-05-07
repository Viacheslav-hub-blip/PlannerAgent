"""Spark-like инструменты для чтения локальных CSV-источников из examples/data.

Логические группы инструментов:
┌─ Поиск сработок ───────────────────────────────────┐
│  spark_lookup_trigger_cases   — поиск по event_id   │
│                               или epk_id + date     │
│  spark_get_trigger_cases_by_period — все сработки   │
│                               клиента за период     │
└────────────────────────────────────────────────────┘
┌─ Выгрузка событий клиента ─────────────────────────┐
│  spark_get_uko_events       — UKO-переводы         │
│  spark_get_cards_events     — карточные операции   │
└────────────────────────────────────────────────────┘
┌─ Работа с CSV-источниками ─────────────────────────┐
│  spark_source_to_sandbox    — preview / загрузка   │
│                              в песочницу           │
└────────────────────────────────────────────────────┘

Содержит:
- TriggerCaseInput: схема входа для spark_lookup_trigger_cases.
- TriggerCasesByPeriodInput: схема входа для spark_get_trigger_cases_by_period.
- ClientTransactionsInput: схема входа для выгрузки событий клиента.
- build_fake_spark_tools: фабрика LangChain tools (сработки + события).
- _spark_lookup_trigger_cases: получение сработок из таблицы hits.
- _spark_get_trigger_cases_by_period: получение сработок клиента за период.
- _spark_get_uko_events: выгрузка UKO-событий клиента.
- _spark_get_cards_events: выгрузка карточных событий клиента.
- _load_csv_table: загрузка CSV-таблицы с кешированием.
- _load_hits_table: загрузка таблицы сработок.
- _load_uko_table: загрузка таблицы uko_event с техническими полями связи.
- _load_cards_table: загрузка таблицы cards_event с техническими полями связи.
- _export_client_transactions: общая фильтрация операционных событий.
- _filter_by_period: фильтрация таблицы по периоду.
- _apply_optional_filters: применение дополнительных фильтров источника.
- _normalize_event_dt: нормализация даты к формату YYYYMMDD.
- _parse_event_dt: разбор даты из форматов YYYY-MM-DD и YYYYMMDD.
- _to_records: преобразование DataFrame в JSON-совместимые записи.
- _fake_sleep: имитация задержки Spark-запроса.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any



import pandas as pd
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, model_validator


DATA_DIR = Path(__file__).resolve().parent / "data"
HITS_FILE = "cspfs_repo_features3.hits_extra_info_129372427_view.csv"
UKO_FILE = "csp_afpc_sss_inc.uko_event.csv"
CARDS_FILE = "csp_afpc_sss_inc.cards_event.csv"
SOURCE_1_FILE = "source_1.csv"
SOURCE_2_FILE = "source_2.csv"
SOURCE_3_FILE = "source_3.csv"

TECHNICAL_COLUMNS = {
    "_source_table",
    "_source_file",
    "_lookup_epk_id",
    "_lookup_event_dt",
    "_lookup_event_date",
    "_linked_hit_event_id",
    "_linked_hit_user_id",
    "_linked_hit_event_time",
}

MERCHANT_COLUMNS = (
    "atm_merchant_name",
    "atm_merchant_name_tst",
    "bnpl_merchant_mame",
    "merchant_login",
    "merchant_id",
    "brand_name",
    "legal_name_of_service_provider",
    "full_name_org",
    "recepient_ul_name",
)
MCC_COLUMNS = (
    "atm_mcc",
    "atm_mcc_name",
    "atm_mcc_connection",
    "atm_mcc_pprb_tst",
    "mcc_group",
    "mcc_list_inn",
)
RECIPIENT_COLUMNS = (
    "transaction_beneficiar_account_number",
    "transaction_beneficiar_nick_name",
    "p2p_recipient_data",
    "recipient_info",
    "recipient_bank_name",
    "payee_phone_number",
    "payee_phone_number_in_foreign_bank",
    "payee_user_id",
    "payee_epk_id",
    "recepient_fio",
    "recepient_bik",
    "recepient_inn",
    "number_card_recepient",
    "account_number_of_recipient",
    "receiver_message",
)


class TriggerCaseInput(BaseModel):
    """Параметры получения сработки из таблицы hits.

    Args:
        event_id: Идентификатор конкретной сработки. Если задан, поиск идет по нему.
        epk_id: Идентификатор клиента. Используется вместе с event_dt, когда нужно
            получить все сработки клиента за день.
        event_dt: Дата события в формате YYYY-MM-DD или YYYYMMDD для поиска по epk_id.

    Returns:
        Валидированные параметры запроса с одним из двух режимов поиска.
    """

    event_id: str | None = Field(
        default=None,
        description="Идентификатор конкретной сработки из таблицы hits.",
    )
    epk_id: str | None = Field(
        default=None,
        description="Идентификатор клиента для поиска всех сработок за день.",
    )
    event_dt: str | None = Field(
        default=None,
        description="Дата события в формате YYYY-MM-DD или YYYYMMDD.",
    )

    @model_validator(mode="after")
    def validate_lookup_mode(self) -> "TriggerCaseInput":
        """Проверяет, что указан event_id или пара epk_id и event_dt.

        Args:
            Отсутствуют.

        Returns:
            Текущий объект схемы, если параметры заданы корректно.
        """

        if self.event_id:
            return self
        if self.epk_id and self.event_dt:
            return self
        raise ValueError("Укажите event_id или пару epk_id + event_dt.")


class ClientTransactionsInput(BaseModel):
    """Параметры выгрузки событий клиента из операционной таблицы.

    Args:
        epk_id: Идентификатор клиента из таблицы сработок.
        event_dt: Опорная дата в формате YYYY-MM-DD или YYYYMMDD.
        depth_days: Глубина периода назад от event_dt, если start_date/end_date не заданы.
        start_date: Начальная дата периода в формате YYYY-MM-DD или YYYYMMDD.
        end_date: Конечная дата периода в формате YYYY-MM-DD или YYYYMMDD.
        min_amount: Минимальная сумма операции.
        merchant_name: Фильтр по merchant/организации.
        mcc_code: Фильтр по MCC-коду или MCC-описанию.
        recipient: Фильтр по получателю.
        event_type: Фильтр по типу события.
        max_rows: Максимальное число строк после фильтрации.

    Returns:
        Валидированные параметры выгрузки событий клиента.
    """

    epk_id: str = Field(description="Идентификатор клиента из таблицы сработок.")
    event_dt: str = Field(description="Опорная дата в формате YYYY-MM-DD или YYYYMMDD.")
    depth_days: int = Field(
        default=180,
        description="Глубина периода назад от event_dt, если start_date/end_date не заданы.",
    )
    start_date: str | None = Field(
        default=None,
        description="Начальная дата периода в формате YYYY-MM-DD или YYYYMMDD.",
    )
    end_date: str | None = Field(
        default=None,
        description="Конечная дата периода в формате YYYY-MM-DD или YYYYMMDD.",
    )
    min_amount: float | None = Field(
        default=None,
        description="Минимальная сумма операции.",
    )
    merchant_name: str = Field(
        default="",
        description="Фильтр по названию merchant или организации.",
    )
    mcc_code: str = Field(
        default="",
        description="Фильтр по MCC-коду или MCC-описанию.",
    )
    recipient: str = Field(
        default="",
        description="Фильтр по получателю операции.",
    )
    event_type: str = Field(
        default="",
        description="Фильтр по типу события.",
    )
    max_rows: int | None = Field(
        default=None,
        description="Максимальное число строк после фильтрации.",
    )


class TriggerCasesByPeriodInput(BaseModel):
    """Параметры получения всех сработок клиента из hits за период.

    Args:
        epk_id: Идентификатор клиента.
        start_date: Начало периода в формате YYYY-MM-DD или YYYYMMDD.
        end_date: Конец периода в формате YYYY-MM-DD или YYYYMMDD.

    Returns:
        Валидированные параметры запроса с установленными границами периода.
    """

    epk_id: str = Field(
        description="Идентификатор клиента для поиска сработок за период.",
    )
    start_date: str = Field(
        description="Начало периода в формате YYYY-MM-DD или YYYYMMDD.",
    )
    end_date: str = Field(
        description="Конец периода в формате YYYY-MM-DD или YYYYMMDD.",
    )


def build_fake_spark_tools(
        *,
        delay_seconds: float = 1.5,
        data_dir: str | Path | None = None,
        transaction_count: int | None = None,
        day_event_count: int | None = None,
) -> list[BaseTool]:
    """Создаёт Spark-like tools для поиска сработок и выгрузки событий клиента.

    Логические группы:
      - spark_lookup_trigger_cases       — поиск сработок в hits.
      - spark_get_trigger_cases_by_period — все сработки клиента за период.
      - spark_get_uko_events             — UKO-переводы / списания.
      - spark_get_cards_events           — карточные операции.

    Args:
        delay_seconds: Искусственная задержка каждого tool-вызова в секундах.
        data_dir: Директория с CSV-файлами. По умолчанию используется examples/data.
        transaction_count: Устаревший параметр совместимости, не влияет на результат.
        day_event_count: Устаревший параметр совместимости, не влияет на результат.

    Returns:
        Список LangChain tools для поиска сработок, UKO-переводов и карточных операций.
    """

    del transaction_count, day_event_count
    resolved_data_dir = Path(data_dir).resolve() if data_dir else DATA_DIR

    async def spark_lookup_trigger_cases(
            event_id: str | None = None,
            epk_id: str | None = None,
            event_dt: str | None = None,
    ) -> dict[str, Any]:
        """Ищет сработки в hits по event_id (точная) или epk_id+event_dt (все за день)."""

        return await _spark_lookup_trigger_cases(
            event_id=event_id,
            epk_id=epk_id,
            event_dt=event_dt,
            data_dir=resolved_data_dir,
            delay_seconds=delay_seconds,
        )

    async def spark_get_trigger_cases_by_period(
            epk_id: str,
            start_date: str,
            end_date: str,
    ) -> dict[str, Any]:
        """Ищет все сработки клиента в hits за указанный период."""

        return await _spark_get_trigger_cases_by_period(
            epk_id=epk_id,
            start_date=start_date,
            end_date=end_date,
            data_dir=resolved_data_dir,
            delay_seconds=delay_seconds,
        )

    async def spark_get_uko_events(
            epk_id: str,
            event_dt: str,
            depth_days: int = 180,
            start_date: str | None = None,
            end_date: str | None = None,
            min_amount: float | None = None,
            merchant_name: str = "",
            mcc_code: str = "",
            recipient: str = "",
            event_type: str = "",
            max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Выгружает UKO-переводы / списания клиента из uko_event."""

        return await _spark_get_uko_events(
            epk_id=epk_id,
            event_dt=event_dt,
            depth_days=depth_days,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            merchant_name=merchant_name,
            mcc_code=mcc_code,
            recipient=recipient,
            event_type=event_type,
            max_rows=max_rows,
            data_dir=resolved_data_dir,
            delay_seconds=delay_seconds,
        )

    async def spark_get_cards_events(
            epk_id: str,
            event_dt: str,
            depth_days: int = 180,
            start_date: str | None = None,
            end_date: str | None = None,
            min_amount: float | None = None,
            merchant_name: str = "",
            mcc_code: str = "",
            recipient: str = "",
            event_type: str = "",
            max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Выгружает карточные операции клиента из cards_event."""

        return await _spark_get_cards_events(
            epk_id=epk_id,
            event_dt=event_dt,
            depth_days=depth_days,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            merchant_name=merchant_name,
            mcc_code=mcc_code,
            recipient=recipient,
            event_type=event_type,
            max_rows=max_rows,
            data_dir=resolved_data_dir,
            delay_seconds=delay_seconds,
        )

    return [
        StructuredTool.from_function(
            coroutine=spark_lookup_trigger_cases,
            name="spark_lookup_trigger_cases",
            description=(
                "spark_lookup_trigger_cases\n"
                "---\n"
                "Описание: Поиск сработок (триггер-кейсов) в hits.\n"
                "Use cases:\n"
                "  - Найти конкретную сработку по её event_id.\n"
                "  - Получить все сработки клиента за определённый день (epk_id + event_dt).\n"
                "  - Проверить, была ли у клиента сработка в конкретную дату.\n\n"
                "Параметры:\n"
                "  event_id (str, опц.) — идентификатор конкретной сработки. "
                "Если задан, поиск идёт только по нему.\n"
                "  epk_id (str, опц.) — идентификатор клиента. Используется "
                "в паре с event_dt для получения всех сработок за день.\n"
                "  event_dt (str, опц.) — дата события в формате YYYY-MM-DD "
                "или YYYYMMDD. Обязателен, если указан epk_id."
            ),
            args_schema=TriggerCaseInput,
        ),
        StructuredTool.from_function(
            coroutine=spark_get_trigger_cases_by_period,
            name="spark_get_trigger_cases_by_period",
            description=(
                "spark_get_trigger_cases_by_period\n"
                "---\n"
                "Описание: Получение ВСЕХ сработок клиента из hits "
                "за указанный период.\n"
                "Use cases:\n"
                "  - Получить историю всех сработок клиента за конкретный "
                "диапазон дат.\n"
                "  - Проанализировать динамику сработок клиента во временном "
                "разрезе.\n"
                "  - Использовать как вход для построения полной хронологии "
                "событий вместе с UKO и карточными операциями.\n\n"
                "Параметры:\n"
                "  epk_id (str, обяз.) — идентификатор клиента.\n"
                "  start_date (str, обяз.) — начало периода в формате "
                "YYYY-MM-DD или YYYYMMDD.\n"
                "  end_date (str, обяз.) — конец периода в формате "
                "YYYY-MM-DD или YYYYMMDD."
            ),
            args_schema=TriggerCasesByPeriodInput,
        ),
        StructuredTool.from_function(
            coroutine=spark_get_uko_events,
            name="spark_get_uko_events",
            description=(
                "spark_get_uko_events\n"
                "---\n"
                "Описание: Выгрузка UKO-переводов / списаний клиента из uko_event.\n"
                "Use cases:\n"
                "  - Получить историю P2P-переводов клиента (по номеру телефона "
                "или EPK).\n"
                "  - Найти SBOL-платежи (по merchant).\n"
                "  - Проанализировать расходы клиента за период с фильтром "
                "по сумме, типу, MCC.\n"
                "  - Выявить подозрительные переводы (крупные суммы, необычные "
                "получатели).\n\n"
                "Параметры:\n"
                "  epk_id (str, обяз.) — идентификатор клиента из таблицы сработок.\n"
                "  event_dt (str, обяз.) — опорная дата в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  depth_days (int, опц., 180) — глубина периода назад от "
                "event_dt, если start_date/end_date не заданы.\n"
                "  start_date (str, опц.) — начало периода в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  end_date (str, опц.) — конец периода в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  min_amount (float, опц.) — минимальная сумма операции.\n"
                "  merchant_name (str, опц.) — фильтр по названию merchant/организации "
                "(поиск по подстроке в полях MERCHANT_COLUMNS).\n"
                "  mcc_code (str, опц.) — фильтр по MCC-коду или описанию "
                "(поиск по подстроке в MCC_COLUMNS).\n"
                "  recipient (str, опц.) — фильтр по получателю (поиск по "
                "подстроке в RECIPIENT_COLUMNS).\n"
                "  event_type (str, опц.) — точный фильтр по типу события "
                "(например 'OUT', 'IN').\n"
                "  max_rows (int, опц.) — максимальное число строк в результате."
            ),
            args_schema=ClientTransactionsInput,
        ),
        StructuredTool.from_function(
            coroutine=spark_get_cards_events,
            name="spark_get_cards_events",
            description=(
                "spark_get_cards_events\n"
                "---\n"
                "Описание: Выгрузка карточных операций клиента из cards_event.\n"
                "Use cases:\n"
                "  - Проанализировать траты по картам (ATM, POS, онлайн).\n"
                "  - Найти операции в конкретном merchant (магазин) или MCC "
                "(категория).\n"
                "  - Проверить подозрительные карточные операции (крупные "
                "суммы, необычное время).\n"
                "  - Сопоставить карточные траты с UKO-переводами для "
                "полной картины расходов клиента.\n\n"
                "ВАЖНО: cards_event НЕ содержит явного epk_id. Связь "
                "строится через event_id/user_id из таблицы сработок.\n\n"
                "Параметры:\n"
                "  epk_id (str, обяз.) — идентификатор клиента из таблицы сработок.\n"
                "  event_dt (str, обяз.) — опорная дата в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  depth_days (int, опц., 180) — глубина периода назад от "
                "event_dt, если start_date/end_date не заданы.\n"
                "  start_date (str, опц.) — начало периода в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  end_date (str, опц.) — конец периода в формате YYYY-MM-DD "
                "или YYYYMMDD.\n"
                "  min_amount (float, опц.) — минимальная сумма операции.\n"
                "  merchant_name (str, опц.) — фильтр по названию merchant/организации "
                "(поиск по подстроке в полях MERCHANT_COLUMNS).\n"
                "  mcc_code (str, опц.) — фильтр по MCC-коду или описанию "
                "(поиск по подстроке в MCC_COLUMNS).\n"
                "  recipient (str, опц.) — фильтр по получателю (поиск по "
                "подстроке в RECIPIENT_COLUMNS).\n"
                "  event_type (str, опц.) — точный фильтр по типу события "
                "(например 'PURCHASE', 'WITHDRAWAL').\n"
                "  max_rows (int, опц.) — максимальное число строк в результате."
            ),
            args_schema=ClientTransactionsInput,
        ),
    ]


async def _spark_lookup_trigger_cases(
        *,
        event_id: str | None,
        epk_id: str | None,
        event_dt: str | None,
        data_dir: Path,
        delay_seconds: float,
) -> dict[str, Any]:
    """Ищет сработки в таблице hits по event_id или по epk_id + event_dt.

    Use cases:
      - Точечный поиск: известен event_id → получить одну сработку.
      - Дневной поиск: известен epk_id + event_dt → получить все сработки
        клиента за конкретную дату.

    Args:
        event_id: Идентификатор конкретной сработки (точный поиск).
        epk_id: Идентификатор клиента для поиска всех сработок за день.
        event_dt: Дата события для дневного поиска (YYYY-MM-DD или YYYYMMDD).
        data_dir: Директория с CSV-файлами.
        delay_seconds: Искусственная задержка запроса.

    Returns:
        Словарь с признаком found и найденными строками из таблицы сработок.
    """

    await _fake_sleep(delay_seconds)
    hits = _load_hits_table(data_dir)

    if event_id:
        matched = hits[hits["event_id"].astype(str) == str(event_id)].copy()
        records = _to_records(matched)
        if not records:
            return {
                "found": False,
                "mode": "event_id",
                "event_id": event_id,
                "source_file": HITS_FILE,
            }
        return {
            "found": True,
            "mode": "event_id",
            "event_id": event_id,
            "source_file": HITS_FILE,
            "record": records[0],
        }

    normalized_dt = _normalize_event_dt(event_dt)
    matched = hits[
        (hits["epk_id"].astype(str) == str(epk_id))
        & (hits["_lookup_event_dt"] == normalized_dt)
    ].copy()
    return {
        "found": not matched.empty,
        "mode": "epk_id_event_dt",
        "epk_id": str(epk_id),
        "event_dt": normalized_dt,
        "source_file": HITS_FILE,
        "records_count": int(len(matched)),
        "records": _to_records(matched),
    }


async def _spark_get_trigger_cases_by_period(
        *,
        epk_id: str,
        start_date: str,
        end_date: str,
        data_dir: Path,
        delay_seconds: float,
) -> dict[str, Any]:
    """Ищет ВСЕ сработки клиента в hits за указанный период.

    Use cases:
      - Получить историю всех сработок клиента за конкретный диапазон дат.
      - Проанализировать динамику сработок клиента во временном разрезе.
      - Использовать как вход для построения полной хронологии событий
        вместе с UKO и карточными операциями.

    Args:
        epk_id: Идентификатор клиента.
        start_date: Начало периода (YYYY-MM-DD или YYYYMMDD).
        end_date: Конец периода (YYYY-MM-DD или YYYYMMDD).
        data_dir: Директория с CSV-файлами.
        delay_seconds: Искусственная задержка запроса.

    Returns:
        Словарь с признаком found и списком сработок за период.
    """

    await _fake_sleep(delay_seconds)
    hits = _load_hits_table(data_dir)

    parsed_start = _parse_event_dt(start_date)
    parsed_end = _parse_event_dt(end_date)
    normalized_start = parsed_start.strftime("%Y%m%d")
    normalized_end = parsed_end.strftime("%Y%m%d")

    matched = hits[
        (hits["_lookup_epk_id"].astype(str) == str(epk_id))
        & (hits["_lookup_event_dt"].astype(str) >= normalized_start)
        & (hits["_lookup_event_dt"].astype(str) <= normalized_end)
    ].copy()

    return {
        "found": not matched.empty,
        "epk_id": str(epk_id),
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
        "source_file": HITS_FILE,
        "records_count": int(len(matched)),
        "records": _to_records(matched),
    }


async def _spark_get_uko_events(
        *,
        epk_id: str,
        event_dt: str,
        depth_days: int,
        start_date: str | None,
        end_date: str | None,
        min_amount: float | None,
        merchant_name: str,
        mcc_code: str,
        recipient: str,
        event_type: str,
        max_rows: int | None,
        data_dir: Path,
        delay_seconds: float,
) -> list[dict[str, Any]]:
    """Выгружает UKO-переводы / списания клиента из таблицы uko_event.

    Use cases:
      - Получить историю P2P-переводов клиента за N дней.
      - Найти SBOL-платежи в пользу конкретного merchant.
      - Проанализировать все операции клиента с суммой >= X.
      - Выявить операции определённого типа (OUT, IN) за период.

    Args:
        epk_id: Идентификатор клиента из таблицы сработок.
        event_dt: Опорная дата выгрузки.
        depth_days: Глубина периода назад от event_dt.
        start_date: Начальная дата периода.
        end_date: Конечная дата периода.
        min_amount: Минимальная сумма операции.
        merchant_name: Фильтр по merchant/организации.
        mcc_code: Фильтр по MCC.
        recipient: Фильтр по получателю.
        event_type: Фильтр по типу события.
        max_rows: Максимальное число строк.
        data_dir: Директория с CSV-файлами.
        delay_seconds: Искусственная задержка запроса.

    Returns:
        Список JSON-совместимых строк из uko_event.
    """

    await _fake_sleep(delay_seconds)
    table = _load_uko_table(data_dir)
    result = _export_client_transactions(
        table=table,
        epk_id=epk_id,
        event_dt=event_dt,
        depth_days=depth_days,
        start_date=start_date,
        end_date=end_date,
        min_amount=min_amount,
        merchant_name=merchant_name,
        mcc_code=mcc_code,
        recipient=recipient,
        event_type=event_type,
        max_rows=max_rows,
    )
    return _to_records(result)


async def _spark_get_cards_events(
        *,
        epk_id: str,
        event_dt: str,
        depth_days: int,
        start_date: str | None,
        end_date: str | None,
        min_amount: float | None,
        merchant_name: str,
        mcc_code: str,
        recipient: str,
        event_type: str,
        max_rows: int | None,
        data_dir: Path,
        delay_seconds: float,
) -> list[dict[str, Any]]:
    """Выгружает карточные операции клиента из таблицы cards_event.

    Use cases:
      - Проанализировать траты по картам (ATM, POS, онлайн) за период.
      - Найти операции в конкретном магазине (merchant_name) или категории (MCC).
      - Проверить подозрительные крупные списания с карты.
      - Сопоставить карточные траты с UKO-переводами для полной картины
        расходов клиента.

    ВАЖНО: cards_event не содержит epk_id напрямую. Связь с клиентом
    устанавливается через event_id / user_id из таблицы hits-сработок.

    Args:
        epk_id: Идентификатор клиента из таблицы сработок.
        event_dt: Опорная дата выгрузки.
        depth_days: Глубина периода назад от event_dt.
        start_date: Начальная дата периода.
        end_date: Конечная дата периода.
        min_amount: Минимальная сумма операции.
        merchant_name: Фильтр по merchant/организации.
        mcc_code: Фильтр по MCC.
        recipient: Фильтр по получателю.
        event_type: Фильтр по типу события.
        max_rows: Максимальное число строк.
        data_dir: Директория с CSV-файлами.
        delay_seconds: Искусственная задержка запроса.

    Returns:
        Список JSON-совместимых строк из cards_event.
    """

    await _fake_sleep(delay_seconds)
    table = _load_cards_table(data_dir)
    result = _export_client_transactions(
        table=table,
        epk_id=epk_id,
        event_dt=event_dt,
        depth_days=depth_days,
        start_date=start_date,
        end_date=end_date,
        min_amount=min_amount,
        merchant_name=merchant_name,
        mcc_code=mcc_code,
        recipient=recipient,
        event_type=event_type,
        max_rows=max_rows,
    )
    return _to_records(result)


@lru_cache(maxsize=8)
def _load_csv_table(path_text: str) -> pd.DataFrame:
    """Загружает CSV-файл с кешированием по абсолютному пути.

    Args:
        path_text: Абсолютный путь к CSV-файлу.

    Returns:
        DataFrame с содержимым CSV-файла.
    """

    return pd.read_csv(path_text, low_memory=False)


def _load_hits_table(data_dir: Path) -> pd.DataFrame:
    """Загружает таблицу сработок и добавляет технические поля поиска.

    Args:
        data_dir: Директория с CSV-файлами.

    Returns:
        DataFrame таблицы hits с нормализованными датами и источником.
    """

    path = data_dir / HITS_FILE
    table = _load_csv_table(str(path.resolve())).copy()
    table["_source_table"] = "hits_extra_info"
    table["_source_file"] = HITS_FILE
    table["_lookup_epk_id"] = table["epk_id"].astype(str)
    table["_lookup_event_dt"] = table["event_dt"].map(_normalize_event_dt)
    table["_lookup_event_date"] = table["_lookup_event_dt"].map(_date_text_from_yyyymmdd)
    return table


def _load_uko_table(data_dir: Path) -> pd.DataFrame:
    """Загружает таблицу uko_event и обогащает ее связью с таблицей hits.

    Args:
        data_dir: Директория с CSV-файлами.

    Returns:
        DataFrame uko_event с техническими полями epk/date для фильтрации.
    """

    table = _load_csv_table(str((data_dir / UKO_FILE).resolve())).copy()
    return _enrich_operational_table(
        table=table,
        hits=_load_hits_table(data_dir),
        source_table="uko_event",
        source_file=UKO_FILE,
    )


def _load_cards_table(data_dir: Path) -> pd.DataFrame:
    """Загружает таблицу cards_event и обогащает ее связью с таблицей hits.

    Args:
        data_dir: Директория с CSV-файлами.

    Returns:
        DataFrame cards_event с техническими полями epk/date для фильтрации.
    """

    table = _load_csv_table(str((data_dir / CARDS_FILE).resolve())).copy()
    return _enrich_operational_table(
        table=table,
        hits=_load_hits_table(data_dir),
        source_table="cards_event",
        source_file=CARDS_FILE,
    )


def _enrich_operational_table(
        *,
        table: pd.DataFrame,
        hits: pd.DataFrame,
        source_table: str,
        source_file: str,
) -> pd.DataFrame:
    """Добавляет к операционной таблице технические поля связи с hits.

    Args:
        table: Операционная таблица cards_event или uko_event.
        hits: Таблица сработок с event_id, epk_id, user_id и event_dt.
        source_table: Логическое имя источника.
        source_file: Имя CSV-файла источника.

    Returns:
        Обогащенный DataFrame для последующей фильтрации по epk_id и датам.
    """

    hit_lookup = hits[
        ["event_id", "_lookup_epk_id", "user_id", "event_time", "_lookup_event_dt"]
    ].rename(
        columns={
            "event_id": "_join_event_id",
            "_lookup_epk_id": "_hit_epk_id",
            "user_id": "_linked_hit_user_id",
            "event_time": "_linked_hit_event_time",
            "_lookup_event_dt": "_hit_event_dt",
        }
    )
    enriched = table.merge(
        hit_lookup,
        left_on=table["event_id"].astype(str),
        right_on=hit_lookup["_join_event_id"].astype(str),
        how="left",
    ).drop(columns=["key_0", "_join_event_id"], errors="ignore")

    table_epk = (
        enriched["epk_id"].astype(str)
        if "epk_id" in enriched.columns
        else pd.Series([None] * len(enriched), index=enriched.index, dtype="object")
    )
    table_dt = (
        enriched["event_dt"].map(_normalize_event_dt)
        if "event_dt" in enriched.columns
        else pd.Series([None] * len(enriched), index=enriched.index, dtype="object")
    )

    enriched["_source_table"] = source_table
    enriched["_source_file"] = source_file
    enriched["_linked_hit_event_id"] = enriched["event_id"].astype(str)
    enriched["_lookup_epk_id"] = enriched["_hit_epk_id"].where(
        enriched["_hit_epk_id"].notna(),
        table_epk,
    ).astype(str)
    enriched["_lookup_event_dt"] = enriched["_hit_event_dt"].where(
        enriched["_hit_event_dt"].notna(),
        table_dt,
    )
    enriched["_lookup_event_date"] = enriched["_lookup_event_dt"].map(_date_text_from_yyyymmdd)
    return enriched


def _export_client_transactions(
        *,
        table: pd.DataFrame,
        epk_id: str,
        event_dt: str,
        depth_days: int,
        start_date: str | None,
        end_date: str | None,
        min_amount: float | None,
        merchant_name: str,
        mcc_code: str,
        recipient: str,
        event_type: str,
        max_rows: int | None,
) -> pd.DataFrame:
    """Фильтрует операционные события клиента по периоду и параметрам.

    Args:
        table: Операционная таблица с техническими полями поиска.
        epk_id: Идентификатор клиента.
        event_dt: Опорная дата.
        depth_days: Глубина периода назад от опорной даты.
        start_date: Начальная дата периода.
        end_date: Конечная дата периода.
        min_amount: Минимальная сумма.
        merchant_name: Фильтр по merchant.
        mcc_code: Фильтр по MCC.
        recipient: Фильтр по получателю.
        event_type: Фильтр по типу события.
        max_rows: Максимальное число строк.

    Returns:
        Отфильтрованный DataFrame.
    """

    result = table[table["_lookup_epk_id"].astype(str) == str(epk_id)].copy()
    result = _filter_by_period(
        table=result,
        event_dt=event_dt,
        depth_days=depth_days,
        start_date=start_date,
        end_date=end_date,
    )
    result = _apply_optional_filters(
        table=result,
        min_amount=min_amount,
        merchant_name=merchant_name,
        mcc_code=mcc_code,
        recipient=recipient,
        event_type=event_type,
    )
    if max_rows is not None:
        result = result.head(max(0, int(max_rows))).copy()
    return result


def _filter_by_period(
        *,
        table: pd.DataFrame,
        event_dt: str,
        depth_days: int,
        start_date: str | None,
        end_date: str | None,
) -> pd.DataFrame:
    """Фильтрует строки по периоду относительно опорной даты.

    Args:
        table: Таблица с колонкой _lookup_event_dt.
        event_dt: Опорная дата.
        depth_days: Глубина периода назад, если границы не заданы.
        start_date: Начальная дата периода.
        end_date: Конечная дата периода.

    Returns:
        DataFrame со строками внутри выбранного периода.
    """

    anchor = _parse_event_dt(event_dt)
    period_start = _parse_event_dt(start_date) if start_date else anchor - timedelta(days=max(0, depth_days))
    period_end = _parse_event_dt(end_date) if end_date else anchor
    normalized_start = period_start.strftime("%Y%m%d")
    normalized_end = period_end.strftime("%Y%m%d")
    date_values = table["_lookup_event_dt"].astype(str)
    return table[
        (date_values >= normalized_start)
        & (date_values <= normalized_end)
    ].copy()


def _apply_optional_filters(
        *,
        table: pd.DataFrame,
        min_amount: float | None,
        merchant_name: str,
        mcc_code: str,
        recipient: str,
        event_type: str,
) -> pd.DataFrame:
    """Применяет необязательные фильтры к операционной таблице.

    Args:
        table: Таблица для фильтрации.
        min_amount: Минимальная сумма операции.
        merchant_name: Текстовый фильтр по merchant.
        mcc_code: Текстовый фильтр по MCC.
        recipient: Текстовый фильтр по получателю.
        event_type: Точный фильтр по типу события.

    Returns:
        Отфильтрованный DataFrame.
    """

    result = table.copy()
    if min_amount is not None and "transaction_amount" in result.columns:
        result = result[pd.to_numeric(result["transaction_amount"], errors="coerce") >= float(min_amount)]
    if merchant_name:
        result = _filter_text_any_column(result, MERCHANT_COLUMNS, merchant_name)
    if mcc_code:
        result = _filter_text_any_column(result, MCC_COLUMNS, mcc_code)
    if recipient:
        result = _filter_text_any_column(result, RECIPIENT_COLUMNS, recipient)
    if event_type and "event_type" in result.columns:
        result = result[
            result["event_type"].astype(str).str.lower() == event_type.lower()
        ]
    return result.copy()


def _filter_text_any_column(
        table: pd.DataFrame,
        candidate_columns: tuple[str, ...],
        value: str,
) -> pd.DataFrame:
    """Фильтрует строки по вхождению текста хотя бы в одной из колонок.

    Args:
        table: Таблица для фильтрации.
        candidate_columns: Возможные колонки для поиска.
        value: Искомый текст.

    Returns:
        DataFrame со строками, где найдено значение.
    """

    existing_columns = [column for column in candidate_columns if column in table.columns]
    if not existing_columns:
        return table.iloc[0:0].copy()

    mask = pd.Series(False, index=table.index)
    for column in existing_columns:
        mask = mask | table[column].astype(str).str.contains(value, case=False, na=False)
    return table[mask].copy()


def _normalize_event_dt(value: Any) -> str | None:
    """Нормализует дату к строке YYYYMMDD.

    Args:
        value: Дата, число или строка даты.

    Returns:
        Строка YYYYMMDD или None для пустого значения.
    """

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) == 8 and text.isdigit():
        return text
    return _parse_event_dt(text).strftime("%Y%m%d")


def _parse_event_dt(value: str | None) -> date:
    """Разбирает дату в форматах YYYY-MM-DD и YYYYMMDD.

    Args:
        value: Строковое значение даты.

    Returns:
        Объект date.
    """

    if value is None:
        raise ValueError("Дата обязательна для Spark-like инструмента.")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _date_text_from_yyyymmdd(value: Any) -> str | None:
    """Преобразует YYYYMMDD в YYYY-MM-DD.

    Args:
        value: Дата в формате YYYYMMDD, YYYY-MM-DD, число pandas/numpy или пустое значение.

    Returns:
        Дата в формате YYYY-MM-DD или None.
    """

    normalized = _normalize_event_dt(value)
    if not normalized:
        return None
    return datetime.strptime(normalized, "%Y%m%d").date().isoformat()


def _to_records(table: pd.DataFrame) -> list[dict[str, Any]]:
    """Преобразует DataFrame в JSON-совместимый список словарей.

    Args:
        table: Таблица для сериализации.

    Returns:
        Список словарей без NaN-значений и технических колонок с внутренними NaN.
    """

    serializable = table.where(pd.notna(table), None).copy()
    records = serializable.to_dict(orient="records")
    cleaned_records: list[dict[str, Any]] = []
    for record in records:
        cleaned_records.append(
            {
                key: _clean_value(value)
                for key, value in record.items()
                if key not in {"_hit_epk_id", "_hit_event_dt"}
            }
        )
    return cleaned_records


def _clean_value(value: Any) -> Any:
    """Преобразует значение pandas/numpy к JSON-совместимому типу.

    Args:
        value: Значение из DataFrame.

    Returns:
        JSON-совместимое значение.
    """

    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


async def _fake_sleep(delay_seconds: float) -> None:
    """Выполняет безопасную асинхронную задержку.

    Args:
        delay_seconds: Количество секунд задержки.

    Returns:
        None.
    """

    await asyncio.sleep(max(0.0, float(delay_seconds)))


_SOURCE_FILE_MAP = {
    "source_1": SOURCE_1_FILE,
    "source_2": SOURCE_2_FILE,
    "source_3": SOURCE_3_FILE,
}


class SourceToSandboxInput(BaseModel):
    """Параметры загрузки или предпросмотра CSV-источника.

    Args:
        source_name: Имя источника: "source_1", "source_2" или "source_3".
        preview: Если True — показать первые 5 строк без загрузки в sandbox.
        load: Если True — загрузить DataFrame в переменную песочницы.
        variable_name: Имя переменной в sandbox. Если не указано, df_{source_name}.
    """

    source_name: str = Field(
        description="Имя источника: 'source_1', 'source_2' или 'source_3'.",
    )
    preview: bool = Field(
        default=False,
        description="Если True — показать первые 5 строк без загрузки в sandbox.",
    )
    load: bool = Field(
        default=False,
        description="Если True — загрузить DataFrame в переменную песочницы.",
    )
    variable_name: str | None = Field(
        default=None,
        description="Имя переменной в sandbox. Если не указано, df_{source_name}.",
    )

    @model_validator(mode="after")
    def validate_source_name(self) -> "SourceToSandboxInput":
        if self.source_name not in _SOURCE_FILE_MAP:
            raise ValueError(
                f"Неизвестный источник '{self.source_name}'. "
                f"Допустимые: {list(_SOURCE_FILE_MAP)}"
            )
        return self


def build_spark_source_to_sandbox_tool(
    sandbox: Any,
    *,
    data_dir: str | Path | None = None,
    delay_seconds: float = 1.5,
) -> list[BaseTool]:
    """Создаёт инструмент для загрузки или предпросмотра CSV-источника в/из песочницы.

    Логическая группа: работа с CSV-источниками (source_1, source_2, source_3).

    Use cases:
      - Посмотреть структуру и первые строки источника, не загружая его в sandbox.
      - Загрузить CSV-источник как pandas DataFrame в переменную песочницы для
        дальнейшего анализа кодом.
      - Получить метаданные источника (число строк, колонки) без preview/load.

    Args:
        sandbox: Экземпляр ClientPythonSandbox для добавления переменных.
        data_dir: Директория с CSV-файлами. По умолчанию examples/data.
        delay_seconds: Искусственная задержка.

    Returns:
        Список с одним LangChain tool.
    """
    resolved_data_dir = Path(data_dir).resolve() if data_dir else DATA_DIR

    async def spark_source_to_sandbox(
        source_name: str,
        preview: bool = False,
        load: bool = False,
        variable_name: str | None = None,
    ) -> dict[str, Any]:
        """Загружает CSV-источник (source_1/2/3) в песочницу или показывает preview.

        Use cases:
          - Посмотреть структуру данных в source_1 без загрузки (preview=True).
          - Загрузить source_2 как pandas DataFrame в sandbox для кодового анализа.
          - Сразу preview + загрузить source_3 в переменную sandbox.

        Args:
            source_name: "source_1", "source_2" или "source_3".
            preview: Если True — показать первые 5 строк.
            load: Если True — загрузить DataFrame в sandbox.
            variable_name: Имя переменной в sandbox (по умолчанию df_{source_name}).

        Returns:
            Словарь с результатом.
        """
        source_file = _SOURCE_FILE_MAP[source_name]
        var_name = variable_name or f"df_{source_name}"

        await _fake_sleep(delay_seconds)

        path = str((resolved_data_dir / source_file).resolve())
        df = _load_csv_table(path)

        if load:
            await sandbox.add_variable(var_name, df)
            rows_preview = _to_records(df.head(5)) if preview else []
            result = {
                "mode": "load",
                "source_name": source_name,
                "source_file": source_file,
                "variable_name": var_name,
                "total_rows": len(df),
                "columns": list(df.columns),
                "rows_count": len(df),
                "message": (
                    f"Данные из {source_file} ({len(df)} строк, "
                    f"{len(df.columns)} колонок) загружены в переменную "
                    f"'{var_name}' песочницы."
                ),
            }
            if preview:
                result["preview_rows"] = rows_preview
                result["preview_count"] = len(rows_preview)
            return result

        if preview:
            rows = _to_records(df.head(5))
            return {
                "mode": "preview",
                "source_name": source_name,
                "source_file": source_file,
                "total_rows": len(df),
                "columns": list(df.columns),
                "rows_count": len(rows),
                "rows": rows,
                "message": (
                    f"Предпросмотр {source_file}: первые {len(rows)} из "
                    f"{len(df)} строк, {len(df.columns)} колонок."
                ),
            }

        # Ни preview, ни load — просто метаданные
        return {
            "mode": "info",
            "source_name": source_name,
            "source_file": source_file,
            "total_rows": len(df),
            "columns": list(df.columns),
            "rows_count": len(df),
            "message": (
                f"Источник {source_file}: {len(df)} строк, "
                f"{len(df.columns)} колонок. Укажите preview=True "
                "для предпросмотра или load=True для загрузки в песочницу."
            ),
        }

    return [
        StructuredTool.from_function(
            coroutine=spark_source_to_sandbox,
            name="spark_source_to_sandbox",
            description=(
                "spark_source_to_sandbox\n"
                "---\n"
                "Описание: Загрузка CSV-источника (source_1/2/3) в песочницу "
                "как pandas DataFrame, либо предпросмотр.\n"
                "Use cases:\n"
                "  - Посмотреть первые 5 строк source_1 (preview=True).\n"
                "  - Загрузить source_2 в sandbox для анализа кодом (load=True).\n"
                "  - Сразу preview + загрузить source_3 (preview=True & load=True).\n"
                "  - Получить метаданные (число строк, список колонок).\n\n"
                "Параметры:\n"
                "  source_name (str, обяз.) — имя источника: 'source_1', "
                "'source_2' или 'source_3'.\n"
                "  preview (bool, опц., False) — если True, вернуть первые "
                "5 строк без загрузки в sandbox.\n"
                "  load (bool, опц., False) — если True, загрузить DataFrame "
                "в переменную песочницы.\n"
                "  variable_name (str, опц.) — имя переменной в sandbox. "
                "По умолчанию df_{source_name}."
            ),
            args_schema=SourceToSandboxInput,
        ),
    ]


__all__ = [
    "ClientTransactionsInput",
    "TriggerCaseInput",
    "TriggerCasesByPeriodInput",
    "SourceToSandboxInput",
    "build_fake_spark_tools",
    "build_spark_source_to_sandbox_tool",
]
