---
name: text-column-semantic-filter
description: "Используй этот skill, когда нужно определить точные значения любого текстового столбца, которые соответствуют смысловой категории пользователя, а сами значения заранее неизвестны. Подходит для текстовых перечислений и описаний: event_description, merchant/name, rule/category, product, channel, comment, status, reason и других строковых колонок"
---

## Алгоритм

1. Определи `text_column`
2. Получи полный список уникальных непустых значений этой колонки в рамках уже заданного источника
3. Загрузи полный список `unique_values` в контекст анализа. Не классифицируй только preview, sample или первые строки.
4. Сравни каждое значение из `unique_values` со смысловой категорией пользователя.
5. Верни только точные значения из исходной колонки, без переформулировок, масок, `LIKE`, `CONTAINS` и выдуманных
   вариантов.
6. Если значений слишком много для одного контекста, раздели `unique_values` на батчи, классифицируй каждый батч и
   объедини результаты. Не переходи к итоговому списку, пока не проверены все батчи.
7. Если подходящих значений нет, верни пустой `exact_candidates` и evidence: источник значений, колонка, количество
   проверенных уникальных значений и примененные ограничения.

Не привязывай workflow к `event_description`: используй колонку, которую требует пользовательский запрос или
подтвержденный schema/skill-контекст. Не используй `LIKE` или `CONTAINS` вместо точных значений из `exact_candidates`.
Не добавляй логику финальной выборки строк в этот skill: он отвечает только за подбор точных значений текстовой
колонки.

Для решения таких задач важно использовать именно llm для определения подходящих значений
## Шаблон Делегирования

```text
delegate data-retrieval-agent:
  objective: загрузить все уникальные непустые значения выбранной текстовой колонки
  inputs:
    text_column: <колонка для смысловой классификации>
    source: <таблица или существующий artifact, если уже определен>
    period: <event_dt/date range, если уже задан пользователем или workflow>
    base_filters: <фильтры, которые уже подтверждены до применения semantic filter>
  expected evidence:
    source, period, text_column, unique value count, artifact path
  stopping condition:
    полный список unique_values доступен для LLM-классификации значений text_column
```

```text
classify_text_column_values:
    input:
        text_column: <имя текстовой колонки>
        user_category: <смысловая категория из запроса пользователя>
        unique_values: <полный список уникальных значений text_column>

    process:
        exact_candidates = []
        for value in unique_values:
            if value точно соответствует user_category по смыслу:
                exact_candidates.append(value)

    output:
        text_column
        user_category
        exact_candidates
        checked_unique_values_count
        evidence: source, period, filters, unique_values_artifact
        limitations
```

## Примеры Запросов

### Получить все значения текстовой колонки

```text
LOAD hits
PERIOD event_dt FROM '20260619' TO '20260621'
SELECT event_description
WHERE event_description IS NOT NULL
```

```text
LOAD cards
PERIOD event_dt FROM '20260619' TO '20260621'
SELECT atm_merchant_name
WHERE atm_merchant_name IS NOT NULL
```

## Пример Результата Классификации

```text
text_column: atm_merchant_name
user_category: образовательные сервисы
checked_unique_values_count: 3842
exact_candidates:
  - UNIVERSITY STORE
  - ONLINE SCHOOL
  - COURSE PLATFORM
evidence:
  unique_values_artifact: /artifacts/atm_merchant_name_unique_values.pkl
limitations:
  - классификация выполнена только по значениям text_column, без анализа остальных полей записи
```
