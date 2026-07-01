---
name: convert-data-structures
description: "Используй этот skill, когда пользователь просит преобразовать код или логику обработки данных между pandas, NumPy и PySpark: переписать pandas на numpy, pandas на pyspark, numpy на pandas, pyspark на pandas, ускорить pandas через векторизацию или выбрать подходящую структуру данных для объема и ограничений задачи."
---

# Конвертация структур данных

Используй этот skill для преобразования кода обработки данных между `pandas`, `NumPy` и `PySpark` с сохранением исходной бизнес-логики.

Skill применим для:

- замены `pandas.apply`, `iterrows`, циклов и построчной логики на векторизованный `NumPy`;
- переноса pandas pipeline на `PySpark` для больших данных;
- переноса PySpark-результата в pandas только после фильтрации и агрегации;
- добавления семантики к `NumPy`-массивам через `pandas.DataFrame`;
- выбора гибридного решения `pandas + NumPy`, когда полный перенос не нужен.

## Алгоритм

1. Определи исходную структуру данных: `pandas.DataFrame`, `pandas.Series`, `np.ndarray`, `PySpark DataFrame` или смешанный pipeline.
2. Определи целевую структуру из запроса пользователя. Если цель не задана, выбери ее по объему данных, операции и ограничениям памяти.
3. Зафиксируй поведение, которое нельзя потерять:
   - входные колонки, индексы, типы и ключи группировки;
   - фильтры, join-условия, сортировку и обработку пропусков;
   - форму результата: массив, Series, DataFrame, Spark DataFrame или новая колонка.
4. Перепиши только нужный участок. Не меняй остальной pipeline без причины.
5. Если создаешь или меняешь `.py` код, соблюдай проектные правила docstring: файл, функции, классы и `BaseModel`-схемы должны иметь русские docstring с входами и выходами.
6. Проверь эквивалентность на небольшом примере или через сравнение формы, колонок и ключевых значений, если запуск доступен без API-ключей.

## Формат ответа

Отвечай на русском языке и показывай результат в такой структуре:

1. `Анализ`: исходная структура, целевая структура, проблема текущего подхода.
2. `Код`: преобразованный фрагмент или точечная правка файла.
3. `Пояснение`: что заменено, почему поведение сохранено, какие ограничения остались.
4. `Проверка`: как проверить эквивалентность результата.

Не обещай фиксированный прирост производительности без измерений. Допускается писать качественную оценку: "обычно быстрее на больших массивах", "уменьшает Python-level loop", "масштабируется на кластер".

## Pandas -> NumPy

Используй, когда данные помещаются в память одной машины, а узкое место находится в построчной Python-логике.

Типовые замены:

- `df.apply(func, axis=1)` -> `np.where`, `np.select`, broadcasting или векторные операции над массивами.
- `iterrows()` / `itertuples()` -> операции над колонками как `np.ndarray`.
- `groupby(...).sum()` -> `np.unique(..., return_inverse=True)` + `np.bincount`.
- `groupby(...).mean()` -> суммы через `np.bincount(weights=...)` и количество через `np.bincount`.
- фильтрация -> boolean mask: `mask = (a > 0) & (b < 0)`.

Пример:

```python
score = df["score"].to_numpy()
df["category"] = np.where(score > 80, "high", "low")
```

Для нескольких условий:

```python
a = df["a"].to_numpy()
b = df["b"].to_numpy()

df["result"] = np.select(
    condlist=[(a > 0) & (b < 0), (a == 0)],
    choicelist=[a * b, b],
    default=a + b,
)
```

Ограничения:

- NumPy теряет имена колонок и часть семантики индекса.
- Для строковых, смешанных и объектных данных прирост может быть слабым.
- `np.vectorize` не является настоящей низкоуровневой векторизацией; используй его только как интерфейсную замену, если нет чистого broadcasting.

## Pandas -> PySpark

Используй, когда данных слишком много для одной машины, нужен кластер или операции естественно выражаются как фильтры, join и агрегации.

Типовые замены:

- `pd.read_csv(path)` -> `spark.read.option("header", True).option("inferSchema", True).csv(path)`.
- `df[df["status"] == "active"]` -> `df.filter(F.col("status") == "active")`.
- `df.groupby(keys).agg(...)` -> `df.groupBy(*keys).agg(...)`.
- `pd.Grouper(key="date", freq="M")` -> `F.date_trunc("month", F.col("date"))`.
- `merge(..., on=..., how=...)` -> `join(other, on=..., how=...)`.
- `pivot_table` -> `groupBy(...).pivot(...).agg(...)`.
- `apply` -> встроенные `pyspark.sql.functions`; UDF используй только если встроенной функции нет.

Пример:

```python
from pyspark.sql import functions as F

monthly = (
    df.withColumn("month", F.date_trunc("month", F.col("date")))
    .groupBy("region", "month")
    .agg(
        F.sum("amount").alias("total"),
        F.avg("price").alias("avg_price"),
        F.countDistinct("id").alias("count"),
    )
    .orderBy("region", "month")
)
```

Ограничения:

- `groupBy`, `join`, `distinct`, `orderBy` часто вызывают shuffle.
- Python UDF ухудшает оптимизацию Catalyst и может стать узким местом.
- Spark не сохраняет pandas index; если индекс значим, преврати его в явную колонку до переноса.
- Для маленьких данных Spark может быть медленнее из-за overhead запуска и планирования.

## PySpark -> Pandas

Используй, когда результат уже достаточно мал для памяти драйвера или нужен локальный анализ/визуализация.

Правила:

- Сначала фильтруй и агрегируй в Spark.
- Выбирай только нужные колонки через `select`.
- Вызывай `.toPandas()` только в конце pipeline.
- Если есть риск большого результата, явно предупреди пользователя.

Пример:

```python
result_pd = (
    events.filter(F.col("event_dt") >= F.lit("2026-01-01"))
    .groupBy("user_id")
    .agg(F.sum("amount").alias("total_amount"))
    .limit(100_000)
    .toPandas()
)
```

## NumPy -> Pandas

Используй, когда массивам нужно вернуть семантику колонок, индекса или табличных операций.

Пример:

```python
result = pd.DataFrame(
    data=values,
    columns=["user_id", "amount", "score"],
)
```

Правила:

- Передавай `columns`, если известно значение каждого измерения.
- Передавай `index`, если позиция строки несет смысл.
- Для двумерных массивов проверяй `values.shape[1] == len(columns)`.

## Pandas + NumPy hybrid

Используй, когда основная читаемость pandas нужна, но отдельная операция должна быть векторной.

Пример:

```python
amount = df["amount"].to_numpy()
limit = df["limit"].to_numpy()

df["is_over_limit"] = amount > limit
```

Такой вариант предпочтителен, если:

- остальные шаги pipeline уже хорошо выражены в pandas;
- нужно ускорить только расчет новой колонки;
- результат должен остаться `DataFrame`.

## Мини-проверки эквивалентности

Для pandas/NumPy:

```python
pd.testing.assert_series_equal(actual.sort_index(), expected.sort_index(), check_names=False)
pd.testing.assert_frame_equal(actual.sort_index(axis=1), expected.sort_index(axis=1))
np.testing.assert_allclose(actual_array, expected_array)
```

Для PySpark:

```python
expected_rows = {tuple(row) for row in expected.collect()}
actual_rows = {tuple(row) for row in actual.collect()}
assert actual_rows == expected_rows
```

Для больших Spark-результатов не делай полный `collect`. Проверяй схему, количество строк, агрегированные контрольные суммы и несколько детерминированных срезов.
