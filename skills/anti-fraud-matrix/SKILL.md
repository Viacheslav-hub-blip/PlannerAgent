---
name: antifraud-matrix-2-0
description: Use this skill when analyzing or explaining Sber fraud-monitoring Matrix 2.0 data: hits_extra_info_129372427_view, anti-fraud hits, prevented fraud flags, resolutions, purpose/surface/product markup, previous/posterior events, KPI/statistics, or Spark access to the sdp_datastore_fs cluster.
---

# Antifraud Matrix 2.0 Skill

## Purpose

This skill teaches the agent how to work with **Матрица ФМ 2.0**: a set of fraud-monitoring data marts and FS flows used for KPI calculation, statistical reporting, urgent analytical requests, and investigation of anti-fraud hits.

Use it to:

- explain the structure of Matrix 2.0;
- identify which fields to use for fraud-monitoring analysis;
- interpret anti-fraud hits from `hits_extra_info_129372427_view`;
- prepare Spark/PySpark queries against the new cluster;
- reason about prevented fraud, false positives, client complaints, resolutions, and confirmation time;
- interpret `purpose`, `surface`, `product`, `payment_transaction_flag`, `is_save`, `previous_events`, and `posterious_events`;
- help analysts build correct SQL/PySpark logic over Matrix 2.0.

## When to Use This Skill

Use this skill when the user asks about any of the following:

- “Матрица 2.0”, “Матрица ФМ”, “matrix struct”, “matrix-3”;
- `hits_extra_info_129372427_view`;
- сработки антифрода;
- предотвращенное мошенничество;
- резолюции УКО / Эмиссии / ДБО / ВСП;
- разметка `purpose`, `surface`, `product`;
- `is_save`, `has_claim`, `marked_as_not_save_reason`;
- операции до или после сработки;
- `posterious_events`, `previous_events`;
- переход на новый кластер `sdp_datastore_fs`;
- Spark-доступ к таблицам с префиксом `cspfs_`.

Do not use this skill for generic fraud theory unless the user explicitly connects the question to Matrix 2.0, FM marts, or anti-fraud data fields.

---

# Core Context

## What Matrix 2.0 Is

**Матрица 2.0** is the second version of Matrix FM. It contains a set of data marts and FS flows used for:

- calculating fraud-monitoring KPIs;
- building statistical datasets and reports;
- preparing operational analytical requests;
- executing urgent tasks and investigations.

## Main Changes Compared with Matrix 1.0

Matrix 2.0 introduced:

1. Migration of calculations to a new cluster.
2. Updated architecture of FS flow dependencies.
3. Conversion of base marts into `view` format.
4. Updated `purpose` / `surface` / `product` markup.
5. More detailed markup of non-payment operations.
6. New transaction-level analytical dimensions.

---

# Cluster Access Rules

## New Cluster

Previous Matrix FM processing was mostly performed on:

```text
datastore_sdp
```

The cluster had insufficient compute capacity, which caused some tasks to miss execution windows.

Most Matrix 2.0 calculations are now moved to:

```text
sdp_datastore_fs
```

## Spark Configuration

When the agent writes PySpark code that reads Matrix 2.0 data, include access to the new HDFS cluster in the Spark session configuration:

```python
.config(
    "spark.kerberos.access.hadoopFileSystems",
    "hdfs://lab-antifraud-sdp,hdfs://sdp-datastore:8020/,hdfs://sdp-datastore-fs:8020/"
)
```

## Table Prefix Rule

When referring to tables on the new cluster, use the prefix:

```text
cspfs_
```

Example:

```text
cspfs_repo_features3.table_name
```

---

# Main Hit Mart

## Mart Name

Use this mart as the main source for anti-fraud hits:

```text
hits_extra_info_129372427_view
```

If the table is read through the new cluster, use the `cspfs_` prefix according to the project’s actual schema naming convention.

## Coverage

The mart contains hit data for all operation channels starting from:

```text
2026-01-01
```

## Mart Contains

The mart includes:

- anti-fraud hit events across operation channels;
- labels for prevented fraud cases;
- resolutions;
- calculated event confirmation time;
- information about false positives, where available;
- transaction attributes;
- client attributes;
- sender and recipient details;
- previous events before the hit;
- successful expense transactions after the hit;
- JSON fields with channel-specific details.

## Important Historical Reporting Caveat

Prevented fraud cases are marked according to the logic introduced from **2Q2026**. Therefore, Matrix 2.0 values can differ from historical reporting built on previous logic.

When answering the user, explicitly mention this caveat if they compare Matrix 2.0 values with older reports.

---

# Analytical Principles

## Use `is_save` as the Main Prevented Fraud Flag

Use:

```text
is_save
```

as the precomputed flag of prevented fraud.

Interpretation:

- `True` — the case is counted as prevented fraud.
- `False` — the case is not counted as prevented fraud.

Do not add extra filters by operation type unless the user’s task explicitly requires a narrower population. The field is already calculated according to the current logic in the `posterious_flags` flow.

## Use `marked_as_not_save_reason` for Exclusions

Use:

```text
marked_as_not_save_reason
```

when explaining why a hit is not counted as prevented fraud.

It is filled only when:

```text
is_save = False
```

Possible reasons include:

- legitimate operation;
- non-payment operation;
- excluded due to a subsequent successful operation;
- other general exclusion reasons.

The source text contains `marked_as_not_save_reason` twice. Treat this as a duplicate description of the same semantic field unless the physical schema confirms otherwise.

## Use `coalesce(client_balance, transaction_amount_in_rub)` for Prevented Amount

When estimating prevented fraud amount, use:

```sql
coalesce(client_balance, transaction_amount_in_rub)
```

Rationale:

- for some operation types, the client balance is more appropriate than the transaction amount;
- if `client_balance` is missing, fall back to `transaction_amount_in_rub`.

## Use `payment_transaction_flag` for Payment Operation Scope

`payment_transaction_flag = True` for:

- `Покупка/Оплата услуг`;
- `Переводы P2P`;
- `Переводы Me2Me`;
- `Снятие наличных`.

Use this flag when the user needs to separate payment operations from non-payment operations.

## Use `has_claim` for Client Complaint Context

`has_claim = True` if a client complaint was received within this window:

```text
2 weeks before the hit <= complaint date <= 2 weeks after the hit
```

Use this field to connect anti-fraud hits with client feedback or complaints.

---

# Output Behavior for the Agent

When answering Matrix 2.0 questions:

1. Start with the short analytical answer.
2. Then explain which fields or marts should be used.
3. If code is helpful, provide SQL or PySpark.
4. If the user asks for investigation logic, describe the step-by-step analysis path.
5. Explicitly state assumptions and data limitations.
6. Mention channel-specific field availability when relevant.
7. Avoid exposing raw personal data unless the user explicitly needs it for a legitimate internal analysis.

## Recommended Answer Template

```markdown
## Краткий ответ
...

## Какие данные использовать
- Витрина: ...
- Основные поля: ...

## Логика расчета / анализа
...

## Пример SQL/PySpark
...

## Важные ограничения
...
```

---

# Privacy and Safety Rules

The mart contains sensitive client data. Treat these fields as sensitive:

- `fio`;
- `phone`;
- `dul_number`;
- `card_number`;
- `payer_card_number`;
- `payer_account_number`;
- `transaction_sender_account_number`;
- `transaction_beneficiar_account_number`;
- `recipient_info`;
- `payer_inn`;
- `recipient_inn`.

When showing examples:

- mask card numbers;
- mask phone numbers;
- avoid displaying full FIO, DUL, INN, account numbers unless strictly required;
- prefer synthetic examples.

---

# Field Reference: `hits_extra_info_129372427_view`

## Date, Channel, Transaction, and Basic Event Fields

| Field | Meaning | Notes |
|---|---|---|
| `event_dt` | Operation date | Due to `view` specifics, type is `int`. |
| `year` | Operation year | Type `string`. |
| `month` | Operation month | Type `string`, two-digit format with leading zero. |
| `week` | Operation week | Type `string`, format like `W04`. |
| `event_time` | Operation time | — |
| `event_id` | Operation/event identifier | Main key for hit-level analysis. |
| `transaction_amount` | Operation amount | Original amount. |
| `transaction_amount_in_rub` | Operation amount in RUB | Use as fallback for prevented amount. |
| `client_balance` | Client account balance at operation date | Prefer in prevented amount via `coalesce(client_balance, transaction_amount_in_rub)`. |
| `transaction_amount_currency` | Operation currency | — |
| `event_channel` | Channel | Example channel dimension. |
| `sub_channel` | Subchannel | — |
| `event_type` | Event type | — |
| `sub_type` | Event subtype | — |
| `type_operation` | Operation type | Filled only for UKO events. |
| `event_description` | Event description | Human-readable event description. |

## Tree and Rule Fields

| Field | Meaning | Notes |
|---|---|---|
| `tree_info` | Tree information | JSON. Filled only for VSP events. |
| `policy_action` | Policy action | — |
| `main_rule` | Triggered rule | JSON. Contains rule details. |

### `tree_info` JSON Attributes

| Attribute | Meaning |
|---|---|
| `event_id` | Event identifier with tree raised. |
| `verdict` | Employee verdict, related to `type_operation`. |
| `client_balance` | Client account balance. |
| `tree_aim` | Operation type from product selection. |
| `question_amount` | Number of questions. |
| `q_and_a_json` | Questionnaire in JSON format. |

Parse example:

```python
.withColumn(
    "tree_id",
    f.get_json_object(f.col("tree_info"), "$.event_id")
)
```

### `main_rule` JSON Attributes

| Attribute | Meaning | Channel |
|---|---|---|
| `rule_name` | Rule name | All relevant channels. |
| `rule_id` | Rule ID | All relevant channels. |
| `rule_category` | Category for non-acceptance hits | DBO only. |
| `description` | Rule description | VSP only. |
| `tech_rule_flag` | Technical rule flag | Emission only. |

Parse example:

```python
.withColumn(
    "rule_name",
    f.get_json_object(f.col("main_rule"), "$.rule_name")
)
```

## Client Fields

| Field | Meaning | Notes |
|---|---|---|
| `epk_id` | Client PPRB ID | — |
| `user_id` | Client identifier | — |
| `fio` | Client full name | Sensitive. |
| `segment` | Client segment | — |
| `age` | Client age on operation date | — |
| `age_category` | Client age group | For ages 15–90, grouped by 5 years. |
| `phone` | Client mobile phone | Sensitive. |
| `phone_operator` | Mobile operator name | Raw value. |
| `region_phone_operator` | Mobile operator region | Region by phone number. |
| `dul_number` | Client identity document number | Sensitive. |
| `dul_type` | Identity document type | Sensitive. |
| `payer_inn` | Client INN | Emission only. Sensitive. |
| `card_number` | Client card number | Emission only. Sensitive. |

## Sender and Branch Fields

| Field | Meaning | Notes |
|---|---|---|
| `transaction_sender_account_number` | Sender requisite/account number | Not filled for VSP events. Sensitive. |
| `p2p_sender_account_number` | P2P sender account/requisite number | Emission only. Sensitive. |
| `terbank` | Territorial bank name | VSP only. |
| `branch_info` | VSP branch information | JSON. VSP only. |
| `token_number` | Token number | Emission only. |
| `payer_account_number` | Sender account number | UKO only. Sensitive. |
| `payer_card_number` | Sender card number | UKO only. Sensitive. |
| `mobile_phone_number` | Sender mobile phone number | UKO only. Sensitive. |

### `branch_info` JSON Attributes

| Attribute | Meaning |
|---|---|
| `branch_terbank` | Branch territorial bank. |
| `branch_number` | Branch number. |
| `branch_office_number` | Office number. |
| `branch_operator_sap_id` | Operator SAP ID. |
| `branch_operator_vsp` | Operator VSP. |
| `branch_one_hand` | One-hand flag. |

Parse example:

```python
.withColumn(
    "branch_operator_vsp",
    f.get_json_object(f.col("branch_info"), "$.branch_operator_vsp")
)
```

## Transfer Type Markup

### `payer_transfer_type`

Sender requisite type. Filled only for payment operations.

Possible values:

- `Карта`;
- `Счет`;
- `Номер телефона`;
- `Наличные` — VSP cash-only operations;
- `Не подлежит разметке` — trees;
- `Другое` — operations by ЦР or requisites whose type could not be identified;
- `Не определено` — non-payment operations or operations without requisite.

### `payee_transfer_type`

Recipient requisite type. Filled only for payment operations.

Possible values:

- `Карта`;
- `Счет`;
- `Номер телефона`;
- `ТСТ`;
- `Наличные` — cash withdrawal and VSP cash-only operations;
- `Не подлежит разметке` — some operation types and trees;
- `Другое` — operations by ЦР or requisites whose type could not be identified;
- `Не определено` — non-payment operations or operations without requisite.

## Recipient and Bank Fields

| Field | Meaning | Notes |
|---|---|---|
| `transaction_beneficiar_account_number` | Recipient requisite/account number | Sensitive. |
| `recipient_bik` | Recipient bank BIK | UKO only. |
| `payee_bank_name` | Recipient bank name | For some operations, sender bank name. Mapped by recipient bank identifier from operation. |
| `memeber_id` | Recipient bank `member_id` | Field name appears as `memeber_id` in source. Not filled for VSP. |
| `atm_acquiring_iic` | Acquirer bank BIN | Emission only. |
| `sbp_id` | SBP ID | DBO only. |
| `operation_id` | Operation ID | DBO only. |
| `recipient_info` | Recipient information | JSON. UKO only. Sensitive. |

### `recipient_info` JSON Attributes

| Attribute | Meaning | Notes |
|---|---|---|
| `epk_id` | Recipient PPRB ID | — |
| `user_id` | Recipient user ID | — |
| `fio` | Recipient full name | Sensitive. |
| `inn` | Recipient INN | Sensitive. |
| `number_card_recepient` | Recipient card number | Source spelling preserved. Sensitive. |
| `account_number_of_recipient` | Recipient account number | Sensitive. |
| `payee_phone_number` | Recipient phone number | DBO only. Sensitive. |
| `brand_name` | Brand name | DBO only. |
| `legal_name_of_service_provider` | Legal name of service provider | DBO only. |
| `full_name_org` | Full organization name | DBO only. |
| `recipient_bank_name` | Recipient bank name | DBO only. |
| `transaction_beneficiar_nick_name` | Recipient nickname | DBO only. |

Parse example:

```python
.withColumn(
    "payee_epk_id",
    f.get_json_object(f.col("recipient_info"), "$.epk_id")
)
```

## Card, Account, and Trust Fields

| Field | Meaning | Notes |
|---|---|---|
| `card_info` | Sender card information | JSON. |
| `account_type` | Account type | VSP only. |
| `trust_info` | Power-of-attorney information | JSON. VSP only. |

### `card_info` JSON Attributes

| Attribute | Meaning |
|---|---|
| `card_type` | Card type: credit, debit, corporate. |
| `card_linked_account` | Account linked to card. |
| `momentum_flg` | Instant/non-personalized card flag. |
| `virt_flg` | Virtual/no-plastic card flag. |
| `payment_system` | Payment system. |

### `trust_info` JSON Attributes

| Attribute | Meaning |
|---|---|
| `truster_epk_id` | Principal PPRB ID. |
| `trustee_epk_id` | Trustee PPRB ID. |
| `operation_person` | Person performing operation. |
| `dul_trustee` | Trustee identity document. |

Parse example:

```python
.withColumn(
    "truster_epk_id",
    f.get_json_object(f.col("trust_info"), "$.truster_epk_id")
)
```

## Merchant, POS, Link, and SDK Fields

| Field | Meaning | Notes |
|---|---|---|
| `recipient_inn` | Recipient INN | Emission only. Sensitive. |
| `atm_merchant_name` | Merchant/TST name | Emission only. |
| `merchant_info` | Merchant/TST information | JSON. Emission only. |
| `pos_info` | POS information | JSON. Emission only. |
| `link_cf` | Custom facts for sender-recipient link | JSON. DBO only. |
| `mobile_sdk_info` | SDK/operator information | JSON. DBO only. |
| `scoring_oss` | Scoring OSS | — |

### `merchant_info` JSON Attributes

- `atm_id`
- `atm_terminal_id`
- `atm_merchant_id`
- `atm_mcc`
- `atm_mcc_name`

Parse example:

```python
.withColumn(
    "atm_id",
    f.get_json_object(f.col("merchant_info"), "$.atm_id")
)
```

### `pos_info` JSON Attributes

- `pos_data_input_mode`
- `pos_cardholder_auth_method`
- `pos_type`
- `elcomm_cvv2_data`
- `sbp_type_message`
- `response_code`

Parse example:

```python
.withColumn(
    "pos_data_input_mode",
    f.get_json_object(f.col("pos_info"), "$.pos_data_input_mode")
)
```

### `link_cf` JSON Attributes

- `recipient_from_address_book`
- `export_user_payee_days_since_first_hit`

Parse example:

```python
.withColumn(
    "recipient_from_address_book",
    f.get_json_object(f.col("link_cf"), "$.recipient_from_address_book")
)
```

### `mobile_sdk_info` JSON Attributes

- `phone_brand`
- `name_os`
- `app_version`

Parse example:

```python
.withColumn(
    "phone_brand",
    f.get_json_object(f.col("mobile_sdk_info"), "$.phone_brand")
)
```

## Confirmation and Resolution Fields

| Field | Meaning | Notes |
|---|---|---|
| `type_accept` | Confirmation type markup | — |
| `source_type_accept` | Actual confirmation channel | Extracted from `uko_resolutions`. UKO only. |
| `resolution_first` | First resolution | UKO only. |
| `resolution_first_dttm` | First resolution timestamp | UKO only. |
| `resolution_last` | Last resolution | For UKO: last resolution. For Emission: auto-marking. |
| `resolution_last_dttm` | Last resolution / marking timestamp | For UKO: last resolution time. For Emission: marking time, usually flow processing date. |
| `accept_time_sec` | Confirmation time in seconds | For `review`: time between hit and marking. For `deny`: time between hit and repeated transaction. |

## Operation Markup and Fraud Flags

| Field | Meaning | Notes |
|---|---|---|
| `purpose` | Operation purpose | See taxonomy below. |
| `surface` | Operation surface/channel surface | See taxonomy below. |
| `product` | Product | See taxonomy below. |
| `product_type` | Detailed operation product | — |
| `payment_transaction_flag` | Payment operation flag | True for purchase/payment, P2P, Me2Me, cash withdrawal. |
| `has_claim` | Client complaint flag | True if complaint exists within ±2 weeks from hit. |
| `is_save` | Prevented fraud flag | Main flag for prevented fraud. |
| `marked_as_not_save_reason` | Reason case is not counted as prevented fraud | Filled only when `is_save = False`. |
| `posterious_events` | Successful expense transactions after hit | Array, 5-day window after hit. |
| `previous_events` | Events before hit | Array: prior hits, deposits, credit events. |
| `hits_extra_facts` | Additional hit facts | JSON. For VSP: `accept_channel`. |
| `posterious_event_additional_info` | Additional info for events after hit | JSON. |
| `previous_events_additional_info` | Additional info for events before hit | JSON. |

---

# How to Interpret `posterious_events`

`posterious_events` is an array of successful outgoing transactions after the hit.

Window:

```text
5 days after the hit
```

Each item is encoded with `|` separators:

```text
Event type | Recipient type | Link age | Amount difference bucket | Amount sign | Time difference bucket | Same-channel flag | Posterior channel | Reason flag
```

## Attribute 1: Event Type

| Value | Meaning |
|---|---|
| `WITHDRAW` | Cash withdrawal. |
| `PURCHASE` | Purchase / service payment. |
| `P2P` | P2P transfer. |
| `ME2ME` | Me2Me transfer. |
| `BOOKING` | Cash booking. |
| `CASHOUT` | Investment cashout. |

## Attribute 2: Recipient Type

| Value | Meaning |
|---|---|
| `SB` | Same recipient or same merchant/TST. |
| `--` | Other. |

## Attribute 3: Link Age

| Value | Meaning |
|---|---|
| `NEW` | Sender-recipient relationship is less than 11 days. |
| `OLD` | Sender-recipient relationship is more than 11 days. |

## Attribute 4: Amount Difference Bucket

Possible values:

```text
0_1p
1_5p
5_10p
10_15p
15_20p
20_25p
25_50p
50_100p
```

For some operation types, compare against client balance instead of hit amount.

## Attribute 5: Amount Sign

| Value | Meaning |
|---|---|
| `+` | Subsequent transaction amount is greater than the hit amount. |
| `-` | Subsequent transaction amount is lower than the hit amount. |

## Attribute 6: Time Difference Bucket

```text
0_1h
1_12h
12_24h
24_48h
48_72h
72_120h
```

## Attribute 7: Same-Channel Flag

| Value | Meaning |
|---|---|
| `SC` | Hit channel matches the subsequent transaction channel. |
| `--` | Channels do not match. |

## Attribute 8: Posterior Channel

Possible values:

```text
VSP
DBO
CARDS
```

## Attribute 9: Reason Flag

| Value | Meaning |
|---|---|
| `main_reason` | Main reason for excluding the case from prevented fraud. This transaction is written to `marked_as_not_save_reason`. Maximum one per array. |
| `reason` | Additional reason. If `main_reason` did not exist, this transaction would still exclude the case from prevented fraud. |
| `--` | Other. |

Example:

```python
[
    "P2P|--|NEW|20_25p|+|0_1h|SC|DBO|main_reason",
    "PURCHASE|--|NEW|15_20p|-|12_24h|--|CARDS|reason",
    "PURCHASE|--|NEW|20_25p|+|1_12h|--|CARDS|reason"
]
```

---

# How to Interpret `previous_events`

`previous_events` is an array of events before the hit.

Included events:

- other hits;
- deposits/top-ups;
- credit-taking events.

Windows:

- hits and deposits: 3 days before hit;
- credits: 7 days before hit.

Each item is encoded with `|` separators:

```text
Event type | Recipient type | Same-purpose flag | Amount difference bucket | Amount sign | Time difference bucket
```

## Attribute 1: Event Type

| Value | Meaning |
|---|---|
| `hit` | Anti-fraud hit. |
| `me2me_deposit_sbp` | Me2Me incoming transfer via SBP. |
| `p2p_deposit_sbp` | P2P incoming transfer via SBP. |
| `p2p_deposit_internal` | P2P incoming transfer via interhosting. |
| `me2me_deposit_cash` | Me2Me cash deposit in VSP. |
| `p2p_deposit_cash` | P2P cash deposit in VSP. |
| `atm_deposit_cash` | Cash deposit via ATM. |
| `p2p_atm_deposit` | ATM deposit from account/card. |
| `credit` | Credit-taking event. |

## Attribute 2: Recipient Type

| Value | Meaning |
|---|---|
| `SB` | Same recipient or same merchant/TST. |
| `--` | Other. |

## Attribute 3: Same-Purpose Flag

| Value | Meaning |
|---|---|
| `SP` | Hit `purpose` matches previous hit `purpose`. |
| `--` | Other. |

## Attribute 4: Amount Difference Bucket

```text
0_1p
1_5p
5_10p
10_20p
20_25p
25_50p
50_100p
```

## Attribute 5: Amount Sign

| Value | Meaning |
|---|---|
| `+` | Compared transaction amount is greater than the hit amount. |
| `-` | Compared transaction amount is lower than the hit amount. |

## Attribute 6: Time Difference Bucket

```text
0_1h
1_12h
12_24h
24_48h
48_96h
96_168h
```

---

# Additional JSON Fields

## `hits_extra_facts`

Additional hit information.

For VSP, includes:

- `accept_channel`

Parse example:

```python
.withColumn(
    "accept_channel",
    f.get_json_object(f.col("hits_extra_facts"), "$.accept_channel")
)
```

## `posterious_event_additional_info`

Additional information about events after the hit.

Attributes:

- `visit_event_dt` — Special VSP visit date;
- `visit_event_id` — Special VSP visit event ID;
- `db_visit_dttm` — Special VSP visit timestamp.

Parse example:

```python
.withColumn(
    "visit_event_id",
    f.get_json_object(f.col("posterious_event_additional_info"), "$.visit_event_id")
)
```

## `previous_events_additional_info`

Additional information about events before the hit.

Attributes:

- `hit_cnt_per_client_72h` — number of hits for the client over the previous 72 hours across all channels.

Parse example:

```python
.withColumn(
    "hit_cnt_per_client_72h",
    f.get_json_object(f.col("previous_events_additional_info"), "$.hit_cnt_per_client_72h")
)
```

---

# Purpose / Surface / Product Taxonomy

Use this taxonomy when interpreting operation markup. The taxonomy is intentionally grouped for agent use rather than copied as a raw report table.

## Payment Purposes

Payment operations are usually counted when `payment_transaction_flag = True`.

### `Покупка/Оплата услуг`

Common combinations:

| Surface | Product examples | Notes |
|---|---|---|
| `ВСП` | `Карта`, `Счет/вклад`, `Наличные`, `ДомКлик`, `Продукты банка` | `Продукты банка` is a special product for trees. |
| `ДБО` | `СМС-банк`, `СБОЛ WEB`, `SberPay`, `СБОЛ МП`, `СБП` | — |
| `ATM` | `СБОЛ СИРИУС`, `Карта`, `ATM` | — |
| `E-comm` | `SberPay`, `СБПэй МП`, `Карта` | — |
| `POS` | `Биометрия`, `NFC-токен`, `QR`, `Вжух`, `Карта` | — |

### `Переводы P2P`

Common combinations:

| Surface | Product examples | Notes |
|---|---|---|
| `ВСП` | `Карта`, `Счет/вклад`, `Продукты банка` | `Продукты банка` is a special product for trees. |
| `ДБО` | `СМС-банк`, `СБОЛ WEB`, `СБОЛ МП`, `СБП`, `Бонусы СберСпасибо` | — |
| `ATM` | `СБОЛ СИРИУС` | — |
| `E-comm` | `Карта` | — |

### `Переводы Me2Me`

Common combinations:

| Surface | Product examples |
|---|---|
| `ВСП` | `Карта`, `Счет/вклад`, `Наличные` |
| `ДБО` | `СМС-банк`, `СБОЛ WEB`, `СБОЛ МП`, `СБП` |
| `ATM` | `СБОЛ СИРИУС` |

### `Снятие наличных`

Common combinations:

| Surface | Product examples | Notes |
|---|---|---|
| `ВСП` | `Карта`, `Счет/вклад`, `Продукты банка` | `Продукты банка` is a special product for trees. |
| `ATM` | `QR`, `Карта`, `Биометрия`, `NFC-токен` | QR cash withdrawal is authorized through `СБОЛ СИРИУС`, so transactions can appear in both DBO and Emission. In turnover marts, use Emission only to avoid duplicates. |
| `POS` | `Карта`, `NFC-токен` | — |

## Deposit and Top-Up Purpose

### `Взнос/пополнение`

Common combinations:

| Surface | Product examples | Notes |
|---|---|---|
| `ВСП` | `Карта`, `Счет/вклад`, `Наличные`, `ДомКлик`, `Продукты банка` | Product is determined as the top-up requisite. `Продукты банка` is special for trees. |
| `ДБО` | `СМС-банк`, `СБОЛ WEB`, `СБОЛ МП`, `Бонусы СберСпасибо` | — |
| `ATM` | `СБОЛ СИРИУС`, `QR`, `Карта`, `NFC-токен`, `ATM` | QR cash deposit can appear in both DBO and Emission; in turnover marts, use Emission only to avoid duplicates. `ATM` product is acquiring and marked only in turnovers. |
| `E-comm` | `Карта` | — |
| `POS` | `Карта`, `NFC-токен`, `QR` | — |

## Credit and Cash Ordering

| Purpose | Surface | Product | Notes |
|---|---|---|---|
| `Расходная операция` | `ВСП` | `Продукты банка` | Special purpose for expense-operation trees. |
| `Взятие кредита` | `ВСП` | `ВСП`, `Продукты банка` | `Продукты банка` is special for trees. |
| `Взятие кредита` | `ДБО` | `СБОЛ WEB`, `СБОЛ МП` | — |
| `Взятие кредита` | `POS` | `Карта` | — |
| `Заказ наличных` | `ВСП` | `ВСП` | — |
| `Заказ наличных` | `ДБО` | `СБОЛ МП` | — |

## Non-Payment and Service Purposes

Use these purposes for non-payment operation analysis.

| Purpose | Common surfaces/products | Notes |
|---|---|---|
| `Операция без открытия счета` | `ВСП` / `ВСП` | Transactions in VSP by visitors who are not Sber clients. Used in turnovers for 203 form assembly. |
| `Открытие профиля клиента` | `ВСП` / `ВСП` | — |
| `Активация карты` | `ВСП` / `Карта`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Заявка на карту` | `ВСП` / `Карта`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Заявка на кредит` | `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Авторизация в СБОЛПро` | `ВСП` / `ВСП` | — |
| `Обновление данных` | `ВСП` / `ВСП`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП`, `ATM` / `СБОЛ СИРИУС` | — |
| `Предоставление совместного доступа ко вкладу` | `ДБО` / `СБОЛ МП` | — |
| `Поднятие опроса по дереву` | `ВСП` / `ВСП` | In turnovers has this markup. In hits, `purpose` is marked by custom facts from the questionnaire. |
| `Посещение сейфа` | `ВСП` / `ВСП` | — |
| `Управление услугами` | `ВСП` / `ВСП`, `ДБО` / `СМС-банк`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП`, `ATM` / `СБОЛ СИРИУС` | — |
| `Авторизация в СБОЛ` | `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП`, `ATM` / `СБОЛ СИРИУС` | — |
| `Верификация карты` | `ВСП` / `Карта`, `ATM` / `Карта`, `E-comm` / `Карта`, `POS` / `Карта` | — |
| `Оформление страхового продукта` | `ВСП` / `ВСП`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Запрос данных карты` | `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Выдача карты` | `ВСП` / `Карта` | — |
| `Редактирование автоплатежа` | `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Запрос документов` | `ВСП` / `ВСП` | — |
| `Печать документов` | `ВСП` / `ВСП` | — |
| `Увеличение лимита` | `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Подтверждение транзакции` | `ВСП` / `ВСП`, `ДБО` / `СМС-банк`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Установка/изменение ПИН-кода карты` | `ВСП` / `ВСП`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Разблокировка профиля СБОЛ` | `ВСП` / `ВСП` | — |
| `Открытие счета/вклада` | `ВСП` / `Счет/вклад`, `ДБО` / `СБОЛ WEB`, `ДБО` / `СБОЛ МП` | — |
| `Токенизация карты` | `ДБО` / `СБОЛ МП` | — |
| `Просмотр информации о клиенте` | `ВСП` / `ВСП` | — |
| `Сгенерированное событие ФС` | `FS` / `Продукты банка` | Hits that card team drops through FS flow, e.g. sending to DB. |
| `Дубль события` | `Не определено` / `Дубль события` | Loop events. |
| `Неплатежная операция` | `Не определено` / `Не определено` | Could not classify. |

---

# Common Analysis Patterns

## Pattern 1: Count Prevented Fraud

Use this logic when the user asks for saved/prevented fraud cases:

```sql
select
    event_dt,
    event_channel,
    purpose,
    surface,
    product,
    count(*) as hit_cnt,
    sum(coalesce(client_balance, transaction_amount_in_rub)) as saved_amount_rub
from cspfs_repo_features3.hits_extra_info_129372427_view
where is_save = true
group by event_dt, event_channel, purpose, surface, product
```

Explain that the amount uses `client_balance` first and falls back to `transaction_amount_in_rub`.

## Pattern 2: Explain Why a Case Was Not Prevented Fraud

Use these fields:

- `is_save`;
- `marked_as_not_save_reason`;
- `posterious_events`;
- `payment_transaction_flag`;
- `resolution_last`;
- `resolution_last_dttm`.

Reasoning:

1. If `is_save = False`, inspect `marked_as_not_save_reason`.
2. If the reason points to a later successful transaction, inspect `posterious_events`.
3. Decode the `main_reason` item in `posterious_events`.
4. Compare event type, amount bucket, time bucket, channel, and recipient relation.

## Pattern 3: Investigate a Specific Hit by `event_id`

Recommended fields:

- `event_id`;
- `event_dt`;
- `event_time`;
- `event_channel`;
- `sub_channel`;
- `event_type`;
- `sub_type`;
- `type_operation`;
- `transaction_amount_in_rub`;
- `client_balance`;
- `purpose`, `surface`, `product`;
- `main_rule`;
- `resolution_first`, `resolution_last`;
- `accept_time_sec`;
- `is_save`;
- `marked_as_not_save_reason`;
- `previous_events`;
- `posterious_events`.

Example PySpark filter:

```python
df = spark.table("cspfs_repo_features3.hits_extra_info_129372427_view")

hit = (
    df
    .filter(f.col("event_id") == "<event_id>")
    .select(
        "event_dt",
        "event_time",
        "event_channel",
        "sub_channel",
        "event_type",
        "sub_type",
        "type_operation",
        "transaction_amount_in_rub",
        "client_balance",
        "purpose",
        "surface",
        "product",
        "main_rule",
        "resolution_first",
        "resolution_last",
        "accept_time_sec",
        "is_save",
        "marked_as_not_save_reason",
        "previous_events",
        "posterious_events"
    )
)
```

## Pattern 4: Analyze False Positives or Customer Friction

Use:

- `has_claim`;
- `is_save`;
- `marked_as_not_save_reason`;
- `accept_time_sec`;
- `resolution_last`;
- `event_channel`;
- `purpose`, `surface`, `product`.

Typical logic:

```sql
select
    event_channel,
    purpose,
    surface,
    product,
    count(*) as hits,
    sum(case when is_save = false then 1 else 0 end) as not_save_hits,
    sum(case when has_claim = true then 1 else 0 end) as claim_hits,
    avg(accept_time_sec) as avg_accept_time_sec
from cspfs_repo_features3.hits_extra_info_129372427_view
group by event_channel, purpose, surface, product
```

## Pattern 5: Decode JSON Fields

When fields are JSON strings, use `get_json_object` in PySpark.

Example:

```python
df_parsed = (
    df
    .withColumn("rule_name", f.get_json_object(f.col("main_rule"), "$.rule_name"))
    .withColumn("rule_id", f.get_json_object(f.col("main_rule"), "$.rule_id"))
    .withColumn("branch_operator_vsp", f.get_json_object(f.col("branch_info"), "$.branch_operator_vsp"))
    .withColumn("payee_epk_id", f.get_json_object(f.col("recipient_info"), "$.epk_id"))
)
```

---

# Common Pitfalls

1. **Do not compare Matrix 2.0 saved-fraud numbers with historical reports without noting the 2Q2026 logic change.**
2. **Do not treat `transaction_amount_in_rub` as the only saved amount.** Prefer `coalesce(client_balance, transaction_amount_in_rub)`.
3. **Do not assume all fields are filled for all channels.** Many fields are channel-specific.
4. **Do not use `posterious_events` as all client activity.** It contains successful outgoing transactions after the hit, within a 5-day window, with specific encoding.
5. **Do not use `previous_events` as full client history.** It only includes selected prior hits, deposits, and credit events within specific windows.
6. **Do not expose sensitive fields unmasked in explanations.**
7. **Do not silently rename physical fields with typos.** For example, `memeber_id` and `number_card_recepient` may be misspelled but should be preserved if they are real schema fields.

---

# Example User Requests and Expected Agent Behavior

## Example 1

User:

```text
Как посчитать предотвращенное мошенничество по Матрице 2.0?
```

Agent should answer:

- use `hits_extra_info_129372427_view`;
- filter `is_save = true`;
- amount is `coalesce(client_balance, transaction_amount_in_rub)`;
- group by required dimensions;
- mention 2Q2026 logic caveat.

## Example 2

User:

```text
Почему сработка не попала в предотвращенное мошенничество?
```

Agent should answer:

- check `is_save`;
- if false, inspect `marked_as_not_save_reason`;
- decode `posterious_events`, especially item with `main_reason`;
- explain if a later successful operation excluded the case.

## Example 3

User:

```text
Что означает PURCHASE|--|NEW|20_25p|+|1_12h|--|CARDS|reason?
```

Agent should decode:

- subsequent successful purchase/service payment;
- not same recipient/merchant;
- new sender-recipient link under 11 days;
- amount differs by 20–25%;
- subsequent amount is greater than hit amount;
- happened 1–12 hours after hit;
- channel differs from hit channel;
- subsequent channel is cards;
- additional reason for exclusion from prevented fraud, not the main reason.

## Example 4

User:

```text
Какие поля нужны для разбора сработки по event_id?
```

Agent should propose:

- event identity fields;
- transaction fields;
- client/channel fields;
- rule fields;
- resolution fields;
- `previous_events` and `posterious_events`;
- fraud flags and reasons;
- optional JSON parsing for `main_rule`, `recipient_info`, `branch_info`, etc.

---

# Final Instruction to Agent

When this skill is active, behave like a senior AI/anti-fraud data engineer. Be precise with field names, preserve real schema names, separate business meaning from technical implementation, and prefer operationally useful SQL/PySpark logic over generic explanations.
