---
name: cards-event-table
description: "Используй источник cards для raw-истории карточных операций, POS, e-commerce, ATM, merchant/MCC, card_number и связи карточного события со сработкой hits. Не используй cards как источник антифрод-резолюций."
---

# Таблица cards

Источник для `load_data`: `cards`.

Когда использовать:

- нужна raw-история карточной операции;
- пользователь спрашивает про POS, e-commerce, ATM, MCC, merchant, терминал, карточные скоринги;
- нужно восстановить карточное поведение до/после сработки из `hits`;
- по `hits` видно карточный канал или карточный тип операции.

Зерно: одна строка = одно raw-событие карточного канала. Это не строка антифрод-сработки.

## Ключи

- `event_id` - может совпадать с `hits.event_id`.
- `epk_id` - клиентский ключ для fallback-связи.
- `event_dt` - дата события `YYYYMMDD`.
- `event_time` - читаемое время `YYYY-MM-DD HH:MM:SS`.

## Главные поля

- `event_id`
- `event_dt`
- `event_time`
- `epk_id`
- `user_id`
- `event_description`
- `event_channel`
- `event_type`
- `sub_type`
- `type_operation`
- `transaction_amount`
- `transaction_amount_currency`
- `card_number`
- `atm_merchant_name`
- `atm_mcc`
- `atm_mcc_name`
- `atm_city`
- `atm_country`
- `response_code`
- `token_device_ip`
- `user_ip_location_city`
- `user_ip_location_country`

## Формат значений

- `event_id` - строковый UUID, например `ae107b8e-4788-4073-9bb4-4f209a6e02aa`.
- `epk_id` - длинный строковый идентификатор, например `2099007770421986000001`; передавай в кавычках.
- `event_dt` - строка `YYYYMMDD`, например `20260124`.
- `event_time` - строка `YYYY-MM-DD HH:MM:SS`, например `2026-01-24 08:00:00`.
- `transaction_amount` - десятичное число, например `118410.20`.
- `transaction_amount_currency` - код валюты, например `RUB`.
- `event_type`, `sub_type`, `type_operation` - категориальные строки, например
  `PURCHASE`, `PURCHASE`, `CARD_PURCHASE`.
- `atm_merchant_name` - название торгового предприятия, например `Университет Синергия`.
- `atm_mcc` - код MCC, который может читаться как строка или число, например `8299`.
- `atm_mcc_name` - человекочитаемая категория MCC, например `Educational Services`.
- `response_code` - код ответа, например `00` или `05`; обрабатывай как строку, чтобы сохранить ведущий ноль.
- `cards_dsl_model_risk_score` - числовой score, например `841`.

## Ограничения

- Для связи с `hits` обычно достаточно `event_id`; fallback - `epk_id` + `event_dt`.
- IP/гео полей меньше, чем в `uko`.
- Не используй `cards` как источник антифрод-резолюций; резолюции находятся в `hits`.
- В `cards` нет поля `transaction_amount_in_rub`; для суммы используй `transaction_amount`, для валюты - `transaction_amount_currency`.

## Дополнительный контекст

- `/skills/cards-event-table/fields.md` - полный список полей `cards`.
- `/skills/hit-table/joins.md` - маршрут связи `hits` -> `cards` / `uko`.

Читай `fields.md`, если нужно редкое карточное поле, MCC/merchant-разбивка, IP/гео или schema error.

