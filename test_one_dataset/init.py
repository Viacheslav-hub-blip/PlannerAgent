"""
Generate synthetic antifraud data for 4 tables with records for ONE client only.

Output directory:
    one_client_antifraud_dataset/

Output files:
    csp_repo_features.history_automarking_big_148078_155487.csv
    cspfs_repo_features3.hits_extra_info_129372427_view.csv
    csp_afpc_sss_inc.cards_event.csv
    csp_afpc_sss_inc.uko_event.csv
    demo_client_timeline.csv
    integrity_report.json
    TASK_FOR_AGENT.md
    one_client_antifraud_dataset.zip

Run:
    pip install pandas
    python generate_one_client_antifraud_dataset.py
"""

from __future__ import annotations

import csv
import json
import random
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


OUT_DIR = Path("one_client_antifraud_dataset")
OUT_ZIP = Path("one_client_antifraud_dataset.zip")

random.seed(42)

DEMO_CLIENT = {
    "user_id": "7770421986",
    "epk_id": "2099007770421986000001",
    "fio": "Кузнецов Андрей Сергеевич",
    "last_name": "Кузнецов",
    "first_name": "Андрей",
    "middle_name": "Сергеевич",
    "age": 42,
    "age_category": "40-45 лет",
    "phone": "+7 916 742-18-65",
    "phone_masked": "+7 (916) 742-18-65",
    "dul_number": "4519884216",
    "dul_number_uko": "451-98-84216",
    "inn": "772845913248",
    "segment": "МВС",
    "region_phone_operator": "77",
    "phone_operator": "МТС",
    "city": "MOSCOW",
    "ip_city": "Moscow",
    "ip_region": "MOW",
    "ip_country": "RU",
    "card_number": "5599004387129866",
    "payer_card_number": "5599004387129866",
    "account_number": "40817810400077421865",
    "number_acc": "42307810900077421865",
    "card_expire_date": "2031-02-28",
    "hardware_id": "A7F98B33D014CC2E93AA7B20477D11F8",
    "os_id": "F68D12C9237B4C8EA5D03184C930B6AF",
    "user_login_id": "login777042198600001",
    "birth_date_client": "14/05/1984",
}

DAY_N = datetime(2026, 3, 9, 13, 47, 4)
KEY_EVENT_ID = "f9246b19-3bf5-4883-8076-d1d4356a6cf8"

BANKS = [
    ("ПАО Сбербанк", "044525225"),
    ("Альфа-Банк", "044525593"),
    ("ВТБ", "044525187"),
    ("Т-Банк", "044525974"),
    ("Газпромбанк", "044525823"),
]

MERCHANTS = [
    ("Пятёрочка", "5411", "MOSCOW", "MOSCOW, ул. Профсоюзная, д. 12"),
    ("Магнит", "5411", "MOSCOW", "MOSCOW, Ленинский пр-т, д. 45"),
    ("Ozon", "5969", "MOSCOW", "MOSCOW, интернет-магазин"),
    ("Wildberries", "5999", "MOSCOW", "MOSCOW, интернет-магазин"),
    ("Мегафон", "4814", "MOSCOW", "MOSCOW, ул. Тверская, д. 7"),
    ("Яндекс Go", "4121", "MOSCOW", "MOSCOW, online"),
]

RECIPIENTS = [
    ("Смирнов Павел Максимович", "Коллега", "+7 916 114-22-75"),
    ("Иванова Мария Игоревна", "Сестра", "+7 925 331-19-82"),
    ("Петров Денис Алексеевич", "Мастер", "+7 903 742-88-10"),
    ("Соколова Анна Дмитриевна", "Друг", "+7 977 541-04-19"),
]


def uuid_str() -> str:
    return str(uuid.uuid4())


def hex32() -> str:
    return uuid.uuid4().hex


def digits(n: int) -> str:
    return "".join(random.choice("0123456789") for _ in range(n))


def js(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def event_dt(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


@dataclass
class Operation:
    event_id: str
    table_type: str  # cards / uko
    dt: datetime
    amount: float | None
    type_operation: str
    event_type: str
    sub_type: str
    description: str
    policy_action: str = "allow"
    is_hit: bool = False
    main_rule_name: str = ""
    rule_category: str = ""
    risk_score: int = 0
    resolution_last: str = ""
    reason: str = ""


def generate_operations() -> list[Operation]:
    ops: list[Operation] = []

    # Normal history across previous 180 days.
    normal_specs = [
        (-179, "uko",  "VIEW_DEPOSIT_INFO", "VIEW_STATEMENT", "ACCOUNT", "Карточка вклада. Просмотр информации по вкладу/счёту", None),
        (-172, "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 1450.40),
        (-166, "uko",  "PHONE_PAYMENT", "PAYMENT", "PHONE", "Оплата мобильной связи", 750.00),
        (-159, "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 3280.10),
        (-151, "uko",  "ME2ME_TRANSFER", "PAYMENT", "ME2ME", "Перевод между своими счетами", 15000.00),
        (-137, "cards", "CARD_ATM_WITHDRAW", "WITHDRAW", "ATM_CASH", "Снятие наличных в банкомате", 10000.00),
        (-129, "uko",  "UTILITY_PAYMENT", "PAYMENT", "UTILITY", "Оплата услуг ЖКХ", 6420.55),
        (-118, "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 5120.90),
        (-109, "uko",  "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 4200.00),
        (-98,  "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 2890.00),
        (-84,  "uko",  "VIEW_DEPOSIT_INFO", "VIEW_STATEMENT", "ACCOUNT", "Карточка вклада. Просмотр информации по вкладу/счёту", None),
        (-73,  "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 7300.00),
        (-66,  "uko",  "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 9800.00),
        (-58,  "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 1990.00),
        (-47,  "uko",  "PHONE_PAYMENT", "PAYMENT", "PHONE", "Оплата мобильной связи", 900.00),
        (-35,  "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 4590.20),
        (-22,  "uko",  "UTILITY_PAYMENT", "PAYMENT", "UTILITY", "Оплата услуг ЖКХ", 7110.40),
        (-14,  "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 3600.00),
        (-6,   "uko",  "ME2ME_TRANSFER", "PAYMENT", "ME2ME", "Перевод между своими счетами", 12000.00),
    ]

    for day_offset, table_type, type_op, event_type, sub_type, desc, amount in normal_specs:
        dt = DAY_N + timedelta(days=day_offset, hours=random.randint(-5, 5), minutes=random.randint(0, 59))
        ops.append(Operation(uuid_str(), table_type, dt, amount, type_op, event_type, sub_type, desc))

    # Historical hits within previous 180 days.
    historical_hits = [
        (-147, "uko", "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 18500.00, "DENY новый получатель и высокий риск устройства", "New Payee", 744, "allow", "new_payee_high_risk"),
        (-92, "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 38990.00, "CARD_DENY крупная покупка после cash-in", "Behavior Anomaly", 812, "allow", "cashin_before_purchase"),
        (-41, "uko", "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 56000.00, "DENY перевод новому получателю после смены реквизитов", "Black List", 901, "deny", "recipient_blacklist"),
    ]

    for day_offset, table_type, type_op, event_type, sub_type, desc, amount, rule, category, risk, resolution, reason in historical_hits:
        dt = DAY_N + timedelta(days=day_offset, hours=random.randint(-2, 2), minutes=random.randint(0, 59))
        ops.append(Operation(uuid_str(), table_type, dt, amount, type_op, event_type, sub_type, desc, "deny", True, rule, category, risk, resolution, reason))

    # Day N: several hits in one day.
    day_n_hits = [
        (DAY_N.replace(hour=9, minute=18, second=22), "uko", "VIEW_DEPOSIT_INFO", "VIEW_STATEMENT", "ACCOUNT", "Карточка вклада. Просмотр информации по вкладу/счёту", None, "INFO просмотр вклада после смены устройства", "Device Anomaly", 412, "review", "new_device_view_statement"),
        (DAY_N.replace(hour=10, minute=6, second=51), "uko", "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 15000.00, "DENY новый получатель после просмотра счетов", "New Payee", 768, "allow", "new_payee_after_account_view"),
        (DAY_N.replace(hour=12, minute=42, second=18), "uko", "PAYMENT_SBP", "PAYMENT", "RURPAYMENT", "Перевод С2С из Сбербанка в сторонний Банк", 92000.00, "DENY смена реквизита после Blacklist MarkerD NOT_ORM", "Black List", 955, "deny", "blacklist_marker"),
        (DAY_N.replace(hour=13, minute=47, second=4), "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 70986.27, "CARD_DENY_BLACK_LIST_FROM_DBO_2_group_potok", "Behavior Anomaly", 998, "allow", "cashin_and_multiple_hits"),
    ]

    for dt, table_type, type_op, event_type, sub_type, desc, amount, rule, category, risk, resolution, reason in day_n_hits:
        event_id = KEY_EVENT_ID if type_op == "CARD_PURCHASE" else uuid_str()
        ops.append(Operation(event_id, table_type, dt, amount, type_op, event_type, sub_type, desc, "deny", True, rule, category, risk, resolution, reason))

    # Explicit post-event operations.
    post_ops = [
        (1, "uko", "ME2ME_TRANSFER", "PAYMENT", "ME2ME", "Перевод между своими счетами", 10000.00),
        (2, "cards", "CARD_PURCHASE", "PURCHASE", "PURCHASE", "Покупка по карте в торговой точке", 2450.80),
        (4, "uko", "PHONE_PAYMENT", "PAYMENT", "PHONE", "Оплата мобильной связи", 950.00),
    ]

    for day_offset, table_type, type_op, event_type, sub_type, desc, amount in post_ops:
        dt = DAY_N + timedelta(days=day_offset, hours=random.randint(1, 6), minutes=random.randint(0, 59))
        ops.append(Operation(uuid_str(), table_type, dt, amount, type_op, event_type, sub_type, desc))

    return sorted(ops, key=lambda x: x.dt)


def make_hits_row(op: Operation, hit_index_in_day: int, total_hits_day: int) -> dict[str, Any]:
    is_card = op.table_type == "cards"
    bank, bik = random.choice(BANKS)
    recipient_fio, nickname, payee_phone = random.choice(RECIPIENTS)
    amount = None if op.amount is None else round(op.amount, 2)

    previous_events = [
        "atm_deposit_cash|--|--|--|0_1h" if hit_index_in_day > 0 else "ME2ME|--|OLD|15_20p|-|24_48h|SC|DBO|reason",
        "hit|SB|SP|0_1p|0_1h" if total_hits_day > 1 else "p2p_deposit_sbp|--|--|--|48_96h",
    ]
    posterious_events = [
        "P2P|--|OLD|0_1p|+|12_24h|SC|DBO|main_reason",
        "PURCHASE|--|OLD|50_100p|-|24_48h|SC|DBO|--",
    ]

    return {
        "index": "",
        "event_time": op.dt.strftime("%Y-%m-%d %H:%M:%S"),
        "event_id": op.event_id,
        "transaction_amount": amount,
        "transaction_amount_in_rub": amount,
        "client_balance": round(random.uniform(2000, 250000), 2),
        "transaction_amount_currency": "RUB" if amount is not None else "",
        "event_channel": "MOBILE" if not is_card else "CARDS",
        "sub_channel": "UFS.MOBILEAPI" if not is_card else "ISSUER",
        "event_type": op.event_type,
        "sub_type": op.sub_type,
        "type_operation": op.type_operation,
        "event_description": op.description,
        "tree_info": "",
        "policy_action": op.policy_action,
        "main_rule": js({"rule_name": op.main_rule_name, "rule_id": uuid_str(), "rule_category": op.rule_category}),
        "epk_id": DEMO_CLIENT["epk_id"],
        "user_id": DEMO_CLIENT["user_id"],
        "fio": DEMO_CLIENT["fio"],
        "segment": DEMO_CLIENT["segment"],
        "age": DEMO_CLIENT["age"],
        "age_category": DEMO_CLIENT["age_category"],
        "phone": DEMO_CLIENT["phone"],
        "phone_operator": DEMO_CLIENT["phone_operator"],
        "region_phone_operator": DEMO_CLIENT["region_phone_operator"],
        "dul_number": DEMO_CLIENT["dul_number"],
        "dul_type": "21",
        "payer_inn": DEMO_CLIENT["inn"],
        "card_number": DEMO_CLIENT["card_number"] if is_card else "",
        "transaction_sender_account_number": DEMO_CLIENT["account_number"],
        "p2p_sender_account_number": DEMO_CLIENT["account_number"] if is_card else "",
        "payer_account_number": DEMO_CLIENT["account_number"],
        "payer_card_number": DEMO_CLIENT["payer_card_number"] if is_card else "",
        "mobile_phone_number": DEMO_CLIENT["phone"],
        "payer_transfer_type": "Номер телефона" if not is_card else "Карта",
        "payee_transfer_type": "Номер телефона" if not is_card else "Мерчант",
        "transaction_beneficiar_account_number": digits(20),
        "recipient_bik": bik,
        "payee_bank_name": bank,
        "member_id": digits(14),
        "sbp_id": hex32()[:23] if op.type_operation == "PAYMENT_SBP" else "",
        "operation_id": hex32()[:24],
        "recipient_info": js({
            "epk_id": None,
            "user_id": None,
            "fio": recipient_fio,
            "inn": None,
            "payee_phone_number": payee_phone,
            "brand_name": None,
            "legal_name_of_service_provider": None,
            "full_name_org": None,
            "recipient_bank_name": bank,
            "transaction_beneficiar_nick_name": nickname,
        }),
        "card_info": js({
            "card_type": "DC" if is_card else "CC",
            "card_linked_account": DEMO_CLIENT["account_number"],
            "momentum_flg": "false",
            "virt_flg": "true" if is_card and op.event_id == KEY_EVENT_ID else "false",
            "payment_system": "Sberbank",
        }),
        "trust_info": js({"trusted_device": True, "trusted_payee": nickname in {"Сестра", "Коллега"}, "device_age_days": 125}),
        "recipient_inn": "",
        "atm_merchant_name": random.choice(MERCHANTS)[0] if is_card else "",
        "merchant_info": js({"merchant_group": "retail"}) if is_card else "",
        "pos_info": js({"pos_type": "ECOM"}) if is_card else "",
        "link_cf": js({"recipient_from_address_book": "ДА" if nickname in {"Сестра", "Коллега"} else "НЕТ", "export_user_payee_days_since_first_hit": str(random.randint(0, 260))}),
        "mobile_sdk_info": js({"phone_brand": "Samsung Galaxy S23", "name_os": "Android", "app_version": "16.13.0"}),
        "scoring_oss": js({"phone_reciver_ScoreMTS_se_2024": f"{random.random():.6f}"}),
        "type_accept": "Black List" if op.policy_action == "deny" else "Review",
        "source_type_accept": "rule",
        "resolution_first": "deny" if op.policy_action == "deny" else "review",
        "resolution_first_dttm": (op.dt + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
        "resolution_last": op.resolution_last,
        "resolution_last_dttm": (op.dt + timedelta(minutes=7)).strftime("%Y-%m-%d %H:%M:%S"),
        "accept_time_sec": random.randint(120, 700),
        "purpose": "Покупки по карте" if is_card else "Переводы P2P" if op.type_operation == "PAYMENT_SBP" else "ДБО операции",
        "surface": "Карты" if is_card else "ДБО",
        "product": "Карта" if is_card else "СБП" if op.type_operation == "PAYMENT_SBP" else "Счета и платежи",
        "product_type": "",
        "payment_transaction_flag": amount is not None,
        "has_claim": False,
        "is_save": False if op.resolution_last == "allow" else True,
        "marked_as_not_save_reason": "Операция подтверждена" if op.resolution_last == "allow" else "Сработка требует проверки",
        "posterious_events": str(posterious_events),
        "previous_events": str(previous_events),
        "hits_extra_facts": js({"demo_client_trace": True, "day_n": DAY_N.strftime("%Y-%m-%d"), "has_180d_history": True}),
        "posterious_events_additional_info": js({"visit_event_dt": None, "visit_event_id": None, "db_visit_dttm": None}),
        "previous_events_additional_info": js({"hit_cnt_per_client_72h": total_hits_day, "operations_cnt_180d": 25, "days_with_hits_180d": 4}),
        "own_loading_id": digits(8),
        "own_dt": event_dt(op.dt),
        "event_dt": event_dt(op.dt),
    }


def make_cards_row(op: Operation) -> dict[str, Any]:
    merchant, mcc, city, address = random.choice(MERCHANTS)
    return {
        "index": "",
        "event_id": op.event_id,
        "user_id": DEMO_CLIENT["user_id"],
        "card_number": DEMO_CLIENT["card_number"],
        "event_type": op.event_type,
        "sub_type": op.sub_type,
        "type_operation": op.type_operation,
        "client_transaction_id": hex32() + hex32()[:12],
        "card_owner": DEMO_CLIENT["fio"],
        "client_lastname": DEMO_CLIENT["last_name"],
        "client_firstname": DEMO_CLIENT["first_name"],
        "client_patronymicname": DEMO_CLIENT["middle_name"],
        "client_id_document_number": DEMO_CLIENT["dul_number"],
        "client_inn": DEMO_CLIENT["inn"],
        "client_phone": DEMO_CLIENT["phone"],
        "event_description": op.description,
        "event_channel": "ISSUER",
        "transaction_amount": "" if op.amount is None else round(op.amount, 2),
        "transaction_amount_currency": "RUB" if op.amount is not None else "",
        "transaction_sender_account_number": DEMO_CLIENT["account_number"],
        "transaction_beneficiar_account_number": digits(20),
        "atm_merchant_name": merchant,
        "atm_mcc": mcc,
        "atm_mcc_name": "Specialty Retail Stores" if mcc == "5999" else "Retail",
        "atm_city": city,
        "atm_address": address,
        "atm_country": "RU",
        "atm_acquiring_country": "RU",
        "user_ip_location_country": "RU",
        "user_ip_location_city": "Moscow",
        "token_device_ip": f"95.31.{random.randint(1,254)}.{random.randint(1,254)}",
        "atm_terminal_id": "T" + digits(9),
        "atm_id": "ATM" + digits(7),
        "atm_merchant_id": "M" + digits(9),
        "atm_acquiring_iic": digits(6),
        "card_bin": DEMO_CLIENT["card_number"][:6],
        "card_type": "DC",
        "card_ps": random.choice(["MIR", "VISA", "MASTERCARD"]),
        "card_brand": "SBERCARD",
        "time_transaction_local": op.dt.strftime("%H:%M:%S"),
        "data_transaction_local": op.dt.strftime("%d.%m"),
        "response_code": "00" if op.policy_action == "allow" else "05",
        "cards_response_code_1": "00" if op.policy_action == "allow" else "05",
        "cards_dsl_model_risk_score": op.risk_score if op.is_hit else random.randint(20, 350),
        "cards_dsl_model_receiver_score": f"{random.random():.6f}",
        "cards_dsl_nspk_fraud_score": f"{random.random():.6f}",
        "cards_client_markers": "---|SUSP|---|---|----|---|---|---|-|---|---|---|---|---|---|---|card_purchase|---|---|---|---|---|pos_CRD|---|adjOUT|-----------" if op.is_hit else "---|NEP|---|---|----|---|---|---|-|---|---|---|---|---|---|---|card_purchase|---|---|---|---|---|pos_CRD|---|adjOUT|-----------",
        "cards_fs_comprpid_marker": "HIGH_RISK" if op.is_hit else "NORM",
        "dbo_client_markers": "---|U00|---|---|----|---|--------|-------|---|----|---|---|--|------|----|---|-C2F-|-F2C-|-C2T-|-T2C-|Y0107|----|---|---|-----|--|N00|----|--|----|----|----|-------",
        "phone_os": "Android",
        "version_mp": "16.13.0",
        "channel_ext_system": "CARDS",
        "own_dt": event_dt(op.dt),
        "event_time": op.dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def make_device_source_sdk(dt: datetime) -> str:
    return js({
        "AccessibilityServices": {"enabled": False},
        "AdvertiserId": uuid_str().upper(),
        "AgentAppInfo": "SberBank 16.13.0 arm64-v8a",
        "AgentBrand": "Samsung Galaxy S23",
        "AgentConnectionType": random.choice(["4G", "5G", "WiFi"]),
        "AppKey": uuid_str().upper(),
        "ApplicationMD5": hex32().upper(),
        "AuthenticationInfo": {"HasSavedBioData": True, "IsDeviceUnlocked": True, "IsHardwareAvailable": True},
        "BootCount": random.randint(20, 180),
        "BootId": uuid_str().upper(),
        "Compromised": 0,
        "Debugger": 0,
        "DeveloperTools": 0,
        "DeviceModel": "Samsung Galaxy S23",
        "DeviceName": "Unknown",
        "DeviceSystemName": "Android",
        "DeviceSystemVersion": "14",
        "Emulator": 0,
        "HardwareID": DEMO_CLIENT["hardware_id"],
        "InstallationSource": "com.android.vending",
        "Languages": "ru_RU",
        "LocalIPv4": f"10.0.{random.randint(1,99)}.{random.randint(2,254)}",
        "MCC": "250",
        "MNC": "1",
        "OS_ID": DEMO_CLIENT["os_id"],
        "OSCodeName": "Android",
        "PhoneLastCall": {"answered": False, "direction": 0, "duration": 0, "state": 0, "type": "unknown"},
        "RdpConnection": "0",
        "ScreenshotCounter": 0,
        "ScreenSize": "1080x2340",
        "SDK_VERSION": "5.7.1.1032",
        "ShareScreen": False,
        "TIMESTAMP": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "TimeZone": "MSK",
        "VpnConnection": False,
        "LocationHash": hex32().upper() + hex32().upper(),
    })


def make_uko_row(op: Operation) -> dict[str, Any]:
    bank, bik = random.choice(BANKS)
    recipient_fio, nickname, payee_phone = random.choice(RECIPIENTS)
    amount = None if op.amount is None else round(op.amount, 2)

    return {
        "index": "",
        "event_id": op.event_id,
        "event_time": str(int(op.dt.timestamp() * 1000)),
        "event_dttm_readable": op.dt.strftime("%Y-%m-%d %H:%M:%S"),
        "event_dt": event_dt(op.dt),
        "load_dt": event_dt(op.dt),
        "own_dttm": (op.dt + timedelta(minutes=random.randint(5, 90))).strftime("%Y-%m-%d %H:%M:%S.%f"),
        "user_id": DEMO_CLIENT["user_id"],
        "epk_id": DEMO_CLIENT["epk_id"],
        "event_channel": "MOBILE",
        "sub_channel": "UFS.MOBILEAPI",
        "event_type": op.event_type,
        "sub_type": op.sub_type,
        "type_operation": op.type_operation,
        "event_description": op.description,
        "first_name": DEMO_CLIENT["first_name"],
        "last_name": DEMO_CLIENT["last_name"],
        "middle_name": DEMO_CLIENT["middle_name"],
        "mobile_phone_number": DEMO_CLIENT["phone_masked"],
        "client_phone_number": DEMO_CLIENT["phone_masked"],
        "dul_number": DEMO_CLIENT["dul_number_uko"],
        "client_card_number": DEMO_CLIENT["card_number"],
        "payer_card_number": DEMO_CLIENT["payer_card_number"],
        "payer_account_number": DEMO_CLIENT["account_number"],
        "number_acc": DEMO_CLIENT["number_acc"],
        "transaction_sender_account_number": DEMO_CLIENT["account_number"],
        "transaction_amount": amount,
        "transaction_amount_currency": "RUB" if amount is not None else "",
        "transaction_beneficiar_account_number": digits(20) if amount is not None else "",
        "transaction_beneficiar_bik": bik if amount is not None else "",
        "recipient_bank_name": bank if amount is not None else "",
        "payee_phone_number": payee_phone if op.type_operation in {"PAYMENT_SBP", "PHONE_PAYMENT"} else "",
        "recepient_fio": recipient_fio if amount is not None else "",
        "transaction_beneficiar_nick_name": nickname if amount is not None else "",
        "operation_id": hex32()[:24],
        "member_id": digits(14),
        "sbp_id": hex32()[:23] if op.type_operation == "PAYMENT_SBP" else "",
        "user_ip_location_country_code": "RU",
        "user_ip_location_city": "Moscow",
        "user_ip_location_region": "MOW",
        "ip_device": f"95.31.{random.randint(1,254)}.{random.randint(1,254)}",
        "longitude_ip": "37.6171",
        "latitude_ip": "55.7483",
        "hardware_id": DEMO_CLIENT["hardware_id"],
        "os_id": DEMO_CLIENT["os_id"],
        "device_time": "AndroidT16",
        "app_version": "16.13.0",
        "name_os": "Android",
        "phone_brand": "Samsung Galaxy S23",
        "phone_model": "Samsung Galaxy S23",
        "user_login_id": DEMO_CLIENT["user_login_id"],
        "card_expire_date": DEMO_CLIENT["card_expire_date"],
        "birth_date_client": DEMO_CLIENT["birth_date_client"],
        "segment_client": "2",
        "client_groups": "95,2",
        "user_mobile_hardware_id_days_since_first_hit": random.randint(1, 180),
        "device_mobile_days_since_first_hit": random.randint(1, 180),
        "payment_new_ip_provider": "2284",
        "device_source_sdk": make_device_source_sdk(op.dt),
        "final_marker_payer": "B20|U00|---|---|----|---|--------|-------|---|RM31|---|---|--|------|RI00|---|-C2F-|-F2C-|-C2T-|-T2C-|Y0304|----|---|---|-----|--|N00|----|--|----|----|----|-------",
        "tfm_client_marker": "G73|B20|ABS-------|---|M050|----|---|---------|----|--------|Y0203|usdlim|-------|------|U00|RI00|DIGIT01110|----------|---------|TFM_EPK|CBCUR0|ABREL--|-----------",
        "client_made_payment_to_recipient": str(amount is not None).lower(),
        "client_accepted_transfer_to_recipient_ignite": "ДА" if nickname in {"Сестра", "Коллега"} else "НЕТ",
        "main_rule": js({"rule_name": op.main_rule_name, "rule_id": uuid_str(), "rule_category": op.rule_category}) if op.is_hit else "",
        "rules": js([op.main_rule_name]) if op.is_hit else "[]",
        "subrules": "[]",
        "risk_score_dsl": op.risk_score if op.is_hit else random.randint(1, 150),
        "kafka_input_time": int(op.dt.timestamp()) + 20,
        "kafka_output_time": int(op.dt.timestamp()) + 80,
        "indicators_vk_max": "{}",
        "scoring_oss": "{}",
        "indicators_sbp": "{}",
        "params": js({"demo_client_trace": True}),
    }


def make_history_row(op: Operation) -> dict[str, Any]:
    merchant, mcc, city, address = random.choice(MERCHANTS)
    return {
        "index": "",
        "event_id": op.event_id.replace("-", "")[:32],
        "source_event_id": op.event_id,
        "user_id": DEMO_CLIENT["user_id"],
        "entity_id": DEMO_CLIENT["epk_id"],
        "event_time": op.dt.strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": op.event_type,
        "sub_type": op.sub_type,
        "event_description": op.description,
        "client_id_document_number": DEMO_CLIENT["dul_number"],
        "client_transaction_id": hex32(),
        "card_number": DEMO_CLIENT["card_number"],
        "client_lastname": DEMO_CLIENT["last_name"],
        "client_firstname": DEMO_CLIENT["first_name"],
        "client_patronymicname": DEMO_CLIENT["middle_name"],
        "client_birthdate": "1984-05-14",
        "atm_merchant_name": merchant,
        "atm_terminal_id": "T" + digits(9),
        "atm_mcc": mcc,
        "terbank_code": "99",
        "atm_city": city,
        "atm_address": address,
        "risk_score": op.risk_score,
        "transaction_amount": "" if op.amount is None else round(op.amount, 2),
        "transaction_amount_currency": "RUB" if op.amount is not None else "",
        "rule_name": op.main_rule_name,
        "rule_num": random.randint(10000, 99999),
        "rule_order": random.randint(1000, 9999),
        "mark": random.choice(["F", "L", "G"]),
        "mcc_group": "R",
        "resolution": op.resolution_last,
        "sub_channel": "ISSUER" if op.table_type == "cards" else "UFS.MOBILEAPI",
        "status": "processed",
        "transaction_sender_account_number": DEMO_CLIENT["account_number"],
        "p2p_sender_account_number": DEMO_CLIENT["account_number"],
        "reason": op.reason,
        "atm_country": "RU",
        "atm_acquiring_country": "RU",
        "atm_acquiring_iic": digits(6),
        "marking_time": (op.dt + timedelta(days=1, minutes=20)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "is_tech_rule": False,
        "own_loading_id": digits(8),
        "own_dt": event_dt(op.dt),
        "load_dt": event_dt(op.dt),
    }


def build_tables(ops: list[Operation]) -> dict[str, pd.DataFrame]:
    hits_by_day: dict[str, list[Operation]] = {}
    for op in ops:
        if op.is_hit:
            hits_by_day.setdefault(op.dt.strftime("%Y-%m-%d"), []).append(op)

    hits_rows = []
    cards_rows = []
    uko_rows = []
    history_rows = []

    for op in ops:
        if op.table_type == "cards":
            cards_rows.append(make_cards_row(op))
        else:
            uko_rows.append(make_uko_row(op))

        if op.is_hit:
            day_hits = sorted(hits_by_day[op.dt.strftime("%Y-%m-%d")], key=lambda x: x.dt)
            idx = day_hits.index(op)
            hits_rows.append(make_hits_row(op, idx, len(day_hits)))
            history_rows.append(make_history_row(op))

    timeline_rows = []
    for op in ops:
        timeline_rows.append({
            "event_time": op.dt.strftime("%Y-%m-%d %H:%M:%S"),
            "event_id": op.event_id,
            "target_table": "cards_event" if op.table_type == "cards" else "uko_event",
            "is_hit": op.is_hit,
            "event_type": op.event_type,
            "sub_type": op.sub_type,
            "type_operation": op.type_operation,
            "amount": "" if op.amount is None else round(op.amount, 2),
            "policy_action": op.policy_action if op.is_hit else "",
            "resolution_last": op.resolution_last if op.is_hit else "",
            "risk_score": op.risk_score if op.is_hit else "",
            "rule": op.main_rule_name if op.is_hit else "",
            "reason": op.reason if op.is_hit else "",
        })

    tables = {
        "cspfs_repo_features3.hits_extra_info_129372427_view.csv": pd.DataFrame(hits_rows),
        "csp_afpc_sss_inc.cards_event.csv": pd.DataFrame(cards_rows),
        "csp_afpc_sss_inc.uko_event.csv": pd.DataFrame(uko_rows),
        "csp_repo_features.history_automarking_big_148078_155487.csv": pd.DataFrame(history_rows),
        "demo_client_timeline.csv": pd.DataFrame(timeline_rows),
    }

    for df in tables.values():
        if "index" in df.columns:
            df["index"] = range(len(df))

    return tables


def make_integrity_report(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    hits = tables["cspfs_repo_features3.hits_extra_info_129372427_view.csv"]
    cards = tables["csp_afpc_sss_inc.cards_event.csv"]
    uko = tables["csp_afpc_sss_inc.uko_event.csv"]
    timeline = tables["demo_client_timeline.csv"]

    hit_ids = set(hits["event_id"].astype(str))
    cards_ids = set(cards["event_id"].astype(str))
    uko_ids = set(uko["event_id"].astype(str))

    found_cards = hit_ids & cards_ids
    found_uko = hit_ids & uko_ids
    found_any = found_cards | found_uko

    return {
        "client": DEMO_CLIENT,
        "day_n": DAY_N.strftime("%Y-%m-%d"),
        "key_event_id": KEY_EVENT_ID,
        "rows_by_table": {name: len(df) for name, df in tables.items()},
        "hits_total": len(hits),
        "hits_found_in_cards": len(found_cards),
        "hits_found_in_uko": len(found_uko),
        "hits_found_in_exactly_one_target_table": sum((eid in cards_ids) ^ (eid in uko_ids) for eid in hit_ids),
        "hits_missing_target_event": sorted(hit_ids - found_any),
        "hits_in_both_cards_and_uko": sorted(found_cards & found_uko),
        "day_n_hits": timeline[(timeline["is_hit"] == True) & (timeline["event_time"].str.startswith(DAY_N.strftime("%Y-%m-%d")))].to_dict("records"),
        "history_window_days": 180,
        "only_one_client_check": {
            "hits_user_ids": sorted(hits["user_id"].astype(str).unique().tolist()),
            "cards_user_ids": sorted(cards["user_id"].astype(str).unique().tolist()),
            "uko_user_ids": sorted(uko["user_id"].astype(str).unique().tolist()),
            "history_user_ids": sorted(tables["csp_repo_features.history_automarking_big_148078_155487.csv"]["user_id"].astype(str).unique().tolist()),
        },
    }


def make_task_md(report: dict[str, Any]) -> str:
    return f"""# Задача для AI-агента

Разбери, что произошло с клиентом `{DEMO_CLIENT['fio']}` по ключевой сработке:

```text
 event_id = {KEY_EVENT_ID}
 user_id = {DEMO_CLIENT['user_id']}
 epk_id = {DEMO_CLIENT['epk_id']}
 день N = {DAY_N:%Y-%m-%d}
```

Нужно определить:

1. Какая операция была заблокирована.
2. Почему антифрод мог заблокировать транзакцию.
3. Какие ещё сработки были у клиента в день N.
4. Как выглядела цепочка событий в день N.
5. Какие операции были у клиента за предыдущие 180 дней.
6. В какие дни за предыдущие 180 дней у клиента тоже были сработки.
7. Есть ли похожие операции в истории клиента.
8. Что говорит история авторазметки.
9. Итог: блокировка похожа на корректную антифрод-сработку или на ложное срабатывание.

Используй таблицы:

- `cspfs_repo_features3.hits_extra_info_129372427_view.csv` — сработки;
- `csp_afpc_sss_inc.cards_event.csv` — карточные операции;
- `csp_afpc_sss_inc.uko_event.csv` — некарточные операции / ДБО / UKO;
- `csp_repo_features.history_automarking_big_148078_155487.csv` — история авторазметки;
- `demo_client_timeline.csv` — контрольная timeline-таблица для проверки.

Контрольные ожидания:

- В датасете есть записи только про одного клиента.
- Всего сработок: `{report['hits_total']}`.
- В день N есть 4 сработки.
- Есть обычная история операций за 180 дней.
- Есть исторические сработки за предыдущие 180 дней.
- Каждая сработка из `hits_extra_info` есть ровно в одной операционной таблице: `cards_event` или `uko_event`.
"""


def write_outputs(tables: dict[str, pd.DataFrame], report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(exist_ok=True)

    for name, df in tables.items():
        df.to_csv(OUT_DIR / name, index=False, quoting=csv.QUOTE_MINIMAL, encoding="utf-8")

    (OUT_DIR / "integrity_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "TASK_FOR_AGENT.md").write_text(make_task_md(report), encoding="utf-8")

    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(OUT_DIR.iterdir()):
            zf.write(path, arcname=path.name)


def main() -> None:
    ops = generate_operations()
    tables = build_tables(ops)
    report = make_integrity_report(tables)
    write_outputs(tables, report)

    print(f"Created directory: {OUT_DIR.resolve()}")
    print(f"Created archive:   {OUT_ZIP.resolve()}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
