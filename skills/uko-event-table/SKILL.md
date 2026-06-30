---
name: uko-event-table
description: "Используй источник uko для raw-истории ДБО, СБП, переводов и операций по счетам, а также данных получателя, мобильного устройства, hardware_id, IP и связи со сработкой hits. Выбирай uko для не карточного канала."
---

# Таблица uko

Источник для `load_data`: `uko`.

Когда использовать:

- нужна raw-история не карточного канала;
- пользователь спрашивает про ДБО, СБП, переводы, счета, мобильное приложение, устройство, IP;
- нужно восстановить UKO/ДБО-поведение до/после сработки из `hits`;
- нужны признаки получателя, IP/гео, hardware/device, правила raw-события.

Зерно: одна строка = одно raw-событие не карточного канала. Это не строка антифрод-сработки.

## Ключи

- `event_id` - может совпадать с `hits.event_id`.
- `epk_id` - клиентский ключ.
- `event_dt` - дата `YYYYMMDD`.
- `event_dttm_readable` - читаемое время `YYYY-MM-DD HH:MM:SS`.
- `event_time` - Unix epoch в миллисекундах, не совместим с `hits.event_time`.

## Главные поля

- `event_id`
- `event_dt`
- `event_dttm_readable`
- `event_time`
- `epk_id`
- `user_id`
- `event_description`
- `event_channel`
- `sub_channel`
- `event_type`
- `sub_type`
- `type_operation`
- `transaction_amount`
- `transaction_amount_currency`
- `payer_account_number`
- `number_acc`
- `transaction_sender_account_number`
- `transaction_beneficiar_account_number`
- `transaction_beneficiar_bik`
- `recipient_bank_name`
- `payee_phone_number`
- `recepient_fio`
- `transaction_beneficiar_nick_name`
- `ip_device`
- `user_ip_location_city`
- `user_ip_location_region`
- `user_ip_location_country_code`
- `hardware_id`
- `os_id`
- `phone_brand`
- `phone_model`

## Формат значений

- `event_id` - строковый UUID, например `72e0bed6-a95d-4100-b55c-dc6a6c9f08ce`.
- `epk_id` - длинный строковый идентификатор, например `2099007770421990000001`; передавай в кавычках.
- `event_dt` - строка `YYYYMMDD`, например `20260124`.
- `event_time` - Unix epoch в миллисекундах, например `1769245629000`.
- `event_dttm_readable` - строка `YYYY-MM-DD HH:MM:SS`, например `2026-01-24 09:07:09`.
- `transaction_amount` - десятичное число, например `12280.58`.
- `transaction_amount_currency` - код валюты, например `RUB`.
- `event_type`, `sub_type`, `type_operation` - категориальные строки, например
  `PAYMENT`, `UTILITY`, `UTILITY_PAYMENT`.
- `recipient_bank_name` - человекочитаемое название, например `Газпромбанк`.
- `hardware_id` - строковый идентификатор устройства, например `F1C44E660347FF5B26DDAE537AAF55F4`.
- `risk_score_dsl` - числовой score, например `312`.
- `main_rule` может быть пустым или содержать JSON-строку:

```json
{"rule_name":"DENY оплата обучения после смены устройства","rule_id":"49f872b6-00b4-4560-94cf-ec1c566e3f13","rule_category":"Device Anomaly"}
```

- `rules` и `subrules` могут храниться как JSON-массивы, например `[]`.
- `params` может храниться как JSON-объект, например
  `{"demo_client_trace":true,"synthetic_education_dataset":true}`.

Для поиска названия внутри JSON-строки используй `CONTAINS`, а не точное равенство всему полю.

## Ограничения

- Никогда не фильтруй `uko.event_time` значением `event_time` из `hits`.
- Для точного читаемого времени используй `event_dttm_readable`.
- Для связи с `hits` используй `event_id`, либо fallback `epk_id` + `event_dt`.
- В `uko` нет поля `transaction_amount_in_rub`; для суммы используй `transaction_amount`, для валюты - `transaction_amount_currency`.

## Дополнительный контекст

- `/skills/uko-event-table/fields.md` - полный список полей `uko`.
- `/skills/hit-table/joins.md` - маршрут связи `hits` -> `cards` / `uko`.

Читай `fields.md`, если нужны редкие поля устройства, IP, правил raw-события или schema error.

