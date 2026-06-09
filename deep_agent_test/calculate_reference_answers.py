"""Расчёт эталонных ответов для набора аналитических тестов.

Содержит функции:
- load_tables: загрузка и нормализация локальных CSV-таблиц.
- parse_json_field: безопасное чтение значения из JSON-строки.
- select_period: фильтрация таблицы по включительному периоду.
- calculate_answers: расчёт эталонных метрик для 30 тестовых кейсов.
- main: вывод эталонных ответов в JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
FIRST_PERIOD = ("20260124", "20260206")
SECOND_PERIOD = ("20260207", "20260220")
FULL_PERIOD = ("20260124", "20260220")
CARD_EVENT_ID = "ae107b8e-4788-4073-9bb4-4f209a6e02aa"
UKO_EVENT_ID = "3486d84b-4eba-4ba4-b044-94764fc9e7a4"


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Загружает и нормализует таблицы для расчёта эталонов.

    Returns:
        Кортеж из таблиц ``hits``, ``cards`` и ``uko`` с нормализованными датами, временем и числами.
    """
    hits = pd.read_csv(
        DATA_ROOT / "cspfs_repo_features3.hits_extra_info_129372427_view.csv",
        dtype={"epk_id": "string"},
    )
    cards = pd.read_csv(
        DATA_ROOT / "csp_afpc_sss_inc.cards_event.csv",
        dtype={"epk_id": "string"},
    )
    uko = pd.read_csv(
        DATA_ROOT / "csp_afpc_sss_inc.uko_event.csv",
        dtype={"epk_id": "string"},
    )

    for table in (hits, cards, uko):
        table["event_dt"] = table["event_dt"].astype(str)
        table["transaction_amount"] = pd.to_numeric(table["transaction_amount"], errors="coerce")

    hits["event_time"] = pd.to_datetime(hits["event_time"])
    cards["event_time"] = pd.to_datetime(cards["event_time"])
    uko["event_dttm_readable"] = pd.to_datetime(uko["event_dttm_readable"])
    hits["transaction_amount_in_rub"] = pd.to_numeric(
        hits["transaction_amount_in_rub"],
        errors="coerce",
    )
    cards["cards_dsl_model_risk_score"] = pd.to_numeric(
        cards["cards_dsl_model_risk_score"],
        errors="coerce",
    )
    uko["risk_score_dsl"] = pd.to_numeric(uko["risk_score_dsl"], errors="coerce")
    return hits, cards, uko


def parse_json_field(value: Any, field_name: str) -> Any:
    """Извлекает поле из JSON-строки без выброса исключения.

    Args:
        value: Исходная JSON-строка.
        field_name: Имя извлекаемого поля.

    Returns:
        Значение поля или ``None``, если JSON отсутствует либо некорректен.
    """
    try:
        return json.loads(value).get(field_name)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def select_period(table: pd.DataFrame, period: tuple[str, str]) -> pd.DataFrame:
    """Фильтрует таблицу по включительному интервалу ``event_dt``.

    Args:
        table: Исходная таблица с колонкой ``event_dt``.
        period: Дата начала и окончания в формате ``YYYYMMDD``.

    Returns:
        Копия строк, попавших в заданный период.
    """
    return table.loc[table["event_dt"].between(*period)].copy()


def calculate_answers() -> dict[str, Any]:
    """Рассчитывает эталонные ответы для всех тестовых запросов.

    Returns:
        Словарь, где ключ — номер кейса, а значение — проверяемый эталонный результат.
    """
    hits, cards, uko = load_tables()
    hits_first = select_period(hits, FIRST_PERIOD)
    hits_second = select_period(hits, SECOND_PERIOD)
    hits_full = select_period(hits, FULL_PERIOD)
    cards_first = select_period(cards, FIRST_PERIOD)
    cards_second = select_period(cards, SECOND_PERIOD)
    cards_full = select_period(cards, FULL_PERIOD)
    uko_first = select_period(uko, FIRST_PERIOD)
    uko_second = select_period(uko, SECOND_PERIOD)
    uko_full = select_period(uko, FULL_PERIOD)

    for table in (hits_first, hits_second, hits_full):
        table["rule_name_parsed"] = table["main_rule"].map(
            lambda value: parse_json_field(value, "rule_name")
        )
        table["rule_category_parsed"] = table["main_rule"].map(
            lambda value: parse_json_field(value, "rule_category")
        )

    answers: dict[str, Any] = {}
    rule_mask = hits_first["main_rule"].str.contains(
        "DENY оплата обучения после смены устройства",
        na=False,
        regex=False,
    )
    answers["1"] = {"count": int(rule_mask.sum())}

    rule_mask = hits_first["main_rule"].str.contains(
        "DENY нетипичная сумма оплаты курсов",
        na=False,
        regex=False,
    )
    answers["2"] = {"unique_clients": int(hits_first.loc[rule_mask, "epk_id"].nunique())}

    client_mask = hits_full["epk_id"] == "2099007770421995000001"
    answers["3"] = {"count": int(client_mask.sum())}
    answers["4"] = {
        "amount_rub": round(float(hits_full.loc[client_mask, "transaction_amount_in_rub"].sum()), 2)
    }

    rule_mask = hits_full["main_rule"].str.contains(
        "CARD_DENY крупная покупка образовательных услуг после cash-in",
        na=False,
        regex=False,
    )
    answers["5"] = {
        "average_amount_rub": round(
            float(hits_full.loc[rule_mask, "transaction_amount_in_rub"].mean()),
            2,
        )
    }
    answers["6"] = {
        "maximum_amount_rub": round(
            float(
                hits_first.loc[
                    hits_first["event_channel"] == "MOBILE",
                    "transaction_amount_in_rub",
                ].max()
            ),
            2,
        )
    }

    claims = hits_first["has_claim"].astype(str).str.lower().eq("true")
    answers["7"] = {
        "claims": int(claims.sum()),
        "all_hits": int(len(hits_first)),
        "percent": round(float(100 * claims.mean()), 2),
    }

    save_not_null = hits_full["is_save"].notna()
    saves = hits_full["is_save"].astype(str).str.lower().eq("true")
    answers["8"] = {
        "saves": int(saves.loc[save_not_null].sum()),
        "non_null_hits": int(save_not_null.sum()),
        "percent": round(float(100 * saves.loc[save_not_null].mean()), 2),
    }

    channels = (
        hits_first.groupby("event_channel")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "event_channel"], ascending=[False, True])
    )
    answers["9"] = channels.iloc[0].to_dict()
    answers["10"] = {"unique_descriptions": int(hits_full["event_description"].dropna().nunique())}
    answers["11"] = {"count": int(hits_first["event_description"].notna().sum())}
    answers["12"] = {
        "unique_rule_categories": int(hits_first["rule_category_parsed"].dropna().nunique())
    }
    answers["13"] = {
        "count": int((cards_first["epk_id"] == "2099007770421995000001").sum())
    }
    answers["14"] = {
        "unique_merchants": int(
            cards_first["atm_merchant_name"]
            .dropna()
            .loc[lambda values: values.astype(str).str.strip().ne("")]
            .nunique()
        )
    }
    answers["15"] = {
        "unique_hardware_ids": int(
            uko_first.loc[
                uko_first["epk_id"] == "2099007770421993000001",
                "hardware_id",
            ]
            .dropna()
            .loc[lambda values: values.astype(str).str.strip().ne("")]
            .nunique()
        )
    }

    card_hit = hits.loc[hits["event_id"] == CARD_EVENT_ID].iloc[0]
    card_day = cards.loc[
        (cards["event_dt"] == card_hit["event_dt"])
        & (cards["epk_id"] == card_hit["epk_id"])
    ]
    answers["16"] = {
        "date": card_hit["event_dt"],
        "epk_id": card_hit["epk_id"],
        "count": int(len(card_day)),
    }

    uko_hit = hits.loc[hits["event_id"] == UKO_EVENT_ID].iloc[0]
    uko_day = uko.loc[
        (uko["event_dt"] == uko_hit["event_dt"])
        & (uko["epk_id"] == uko_hit["epk_id"])
    ]
    answers["17"] = {
        "date": uko_hit["event_dt"],
        "epk_id": uko_hit["epk_id"],
        "event_types": (
            uko_day.groupby(["event_type", "sub_type"])
            .size()
            .reset_index(name="count")
            .to_dict("records")
        ),
    }

    answers["18"] = {
        "transactions": int(len(card_day)),
        "amount": round(float(card_day["transaction_amount"].sum()), 2),
    }

    answers["19"] = {
        "transactions": int(len(uko_day)),
        "amount": round(float(uko_day["transaction_amount"].sum()), 2),
    }

    card_hits = hits_first.loc[hits_first["event_channel"] == "CARDS"].copy()
    mobile_hits = hits_first.loc[hits_first["event_channel"] == "MOBILE"].copy()
    linked_cards = card_hits[["event_id", "rule_name_parsed"]].merge(
        cards_first[
            [
                "event_id",
                "event_type",
                "sub_type",
                "atm_merchant_name",
                "atm_mcc_name",
                "response_code",
            ]
        ],
        on="event_id",
    )
    linked_uko = mobile_hits[["event_id", "rule_name_parsed"]].merge(
        uko_first[
            [
                "event_id",
                "event_type",
                "sub_type",
                "recipient_bank_name",
                "type_operation",
            ]
        ],
        on="event_id",
    )
    linked_events = pd.concat(
        [
            linked_cards[["event_type", "sub_type"]],
            linked_uko[["event_type", "sub_type"]],
        ]
    )
    answers["20"] = (
        linked_events.groupby(["event_type", "sub_type"])
        .size()
        .reset_index(name="count")
        .sort_values(["count", "event_type", "sub_type"], ascending=[False, True, True])
        .to_dict("records")
    )

    answers["21"] = (
        linked_cards.groupby(["atm_merchant_name", "atm_mcc_name"])
        .size()
        .reset_index(name="count")
        .sort_values(["count", "atm_merchant_name"], ascending=[False, True])
        .head(3)
        .to_dict("records")
    )
    answers["22"] = (
        linked_uko.groupby("recipient_bank_name")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "recipient_bank_name"], ascending=[False, True])
        .head(3)
        .to_dict("records")
    )
    answers["23"] = (
        linked_cards.groupby(["rule_name_parsed", "atm_mcc_name"])
        .size()
        .reset_index(name="count")
        .sort_values(["count", "rule_name_parsed", "atm_mcc_name"], ascending=[False, True, True])
        .to_dict("records")
    )
    answers["24"] = (
        linked_uko.groupby(["rule_name_parsed", "type_operation"])
        .size()
        .reset_index(name="count")
        .sort_values(["count", "rule_name_parsed", "type_operation"], ascending=[False, True, True])
        .to_dict("records")
    )

    claims = hits_full.loc[hits_full["has_claim"].astype(str).str.lower().eq("true")].copy()
    claim_cards = claims.loc[claims["event_channel"] == "CARDS"].merge(
        cards_full[["event_id", "event_type", "sub_type"]],
        on="event_id",
    )
    claim_uko = claims.loc[claims["event_channel"] == "MOBILE"].merge(
        uko_full[["event_id", "event_type", "sub_type"]],
        on="event_id",
    )
    claim_events = pd.concat(
        [
            claim_cards[["product", "event_type_y", "sub_type_y"]],
            claim_uko[["product", "event_type_y", "sub_type_y"]],
        ]
    ).rename(columns={"event_type_y": "event_type", "sub_type_y": "sub_type"})
    answers["25"] = (
        claim_events.groupby(["product", "event_type", "sub_type"])
        .size()
        .reset_index(name="count")
        .sort_values(["product", "count", "event_type"], ascending=[True, False, True])
        .to_dict("records")
    )

    education_mobile = hits_full.loc[
        (hits_full["event_channel"] == "MOBILE")
        & hits_full["event_description"].str.contains("Оплата", na=False, regex=False)
    ].merge(
        uko_full[["event_id", "recipient_bank_name"]],
        on="event_id",
    )
    answers["26"] = (
        education_mobile.groupby("recipient_bank_name")
        .size()
        .reset_index(name="count")
        .sort_values(["count", "recipient_bank_name"], ascending=[False, True])
        .head(5)
        .to_dict("records")
    )

    answers["27"] = (
        card_day.groupby(["event_type", "sub_type", "type_operation"])
        .size()
        .reset_index(name="count")
        .to_dict("records")
    )

    saved_card_hits = hits_full.loc[
        hits_full["is_save"].astype(str).str.lower().eq("true")
        & hits_full["event_channel"].eq("CARDS")
    ]
    merchant_counts = (
        saved_card_hits[["event_id"]]
        .merge(
            cards_full[["event_id", "atm_merchant_name"]],
            on="event_id",
        )
        .dropna(subset=["atm_merchant_name"])
        .groupby("atm_merchant_name")["event_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values(["count", "atm_merchant_name"], ascending=[False, True])
    )
    answers["28"] = merchant_counts.iloc[0].to_dict()

    product_periods = []
    for period_name, period_hits, period_cards, period_uko in (
        ("first", hits_first, cards_first, uko_first),
        ("second", hits_second, cards_second, uko_second),
    ):
        client_days = period_hits[["product", "event_channel", "epk_id", "event_dt"]].drop_duplicates()
        card_activity = client_days.loc[client_days["event_channel"] == "CARDS"].merge(
            period_cards[["epk_id", "event_dt", "event_id"]],
            on=["epk_id", "event_dt"],
        )
        uko_activity = client_days.loc[client_days["event_channel"] == "MOBILE"].merge(
            period_uko[["epk_id", "event_dt", "event_id"]],
            on=["epk_id", "event_dt"],
        )
        counts = (
            pd.concat([card_activity, uko_activity])
            .groupby("product")
            .size()
            .rename(period_name)
        )
        product_periods.append(counts)

    product_change = pd.concat(product_periods, axis=1).fillna(0).astype(int)
    product_change["difference"] = product_change["second"] - product_change["first"]
    product_change["percent"] = (
        100 * product_change["difference"] / product_change["first"]
    ).where(product_change["first"].ne(0))
    answers["29"] = [
        {
            "product": product,
            "first": int(row["first"]),
            "second": int(row["second"]),
            "difference": int(row["difference"]),
            "percent": None if pd.isna(row["percent"]) else round(float(row["percent"]), 2),
        }
        for product, row in product_change.iterrows()
    ]

    client_days = hits_full[["surface", "event_channel", "epk_id", "event_dt"]].drop_duplicates()
    card_activity = client_days.loc[client_days["event_channel"] == "CARDS"].merge(
        cards_full[["epk_id", "event_dt", "event_id"]],
        on=["epk_id", "event_dt"],
    )
    uko_activity = client_days.loc[client_days["event_channel"] == "MOBILE"].merge(
        uko_full[["epk_id", "event_dt", "event_id"]],
        on=["epk_id", "event_dt"],
    )
    all_activity = pd.concat([card_activity, uko_activity])
    surface_activity = (
        all_activity.groupby("surface")
        .agg(raw_events=("event_id", "count"), client_days=("event_dt", "count"))
        .reset_index()
    )
    client_day_counts = (
        all_activity.groupby(["surface", "epk_id", "event_dt"])
        .size()
        .reset_index(name="events")
    )
    surface_average = (
        client_day_counts.groupby("surface")["events"].mean().reset_index(name="average_events")
    )
    surface_activity = surface_activity.drop(columns=["client_days"]).merge(
        surface_average,
        on="surface",
    )
    answers["30"] = [
        {
            "surface": row["surface"],
            "raw_events": int(row["raw_events"]),
            "average_events_per_client_day": round(float(row["average_events"]), 2),
        }
        for _, row in surface_activity.sort_values(
            ["average_events", "surface"],
            ascending=[False, True],
        ).iterrows()
    ]
    return answers


def main() -> None:
    """Выводит рассчитанные эталонные ответы в JSON.

    Returns:
        ``None``.
    """
    print(json.dumps(calculate_answers(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
