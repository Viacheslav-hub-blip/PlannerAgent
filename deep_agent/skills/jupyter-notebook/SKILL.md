---
name: jupyter-notebook
description: "Используй при создании, редактировании, конвертации и пересборке Jupyter Notebook `.ipynb`, percent-script `# %%`, markdown/code cells, аналитических notebook, pandas/sklearn/plotly notebooks и работе через convert_jupyter_notebook."
---

# Работа с Jupyter Notebook

Используй этот skill для любых задач с `.ipynb`, Jupyter Notebook, percent-script,
markdown cells и code cells. Notebook должен быть читаемым аналитическим документом,
а не набором склеенных code cells.

## Модель мышления

Перед записью notebook мысленно разложи работу на ячейки:

1. Markdown-ячейка формулирует цель, контекст, проверку или вывод.
2. Code-ячейка выполняет один логический шаг.
3. Следующая markdown-ячейка объясняет, зачем нужен следующий шаг или что показал предыдущий.
4. Итоговый `.ipynb` всегда создаётся или пересобирается через `convert_jupyter_notebook`.

Не пиши длинные объяснения комментариями внутри кода. Комментарий в code cell нужен только
для неочевидной логики, нестандартного преобразования или важного ограничения данных.

## Базовый percent-script

Хорошо:

```python
# %% [markdown]
# # Анализ транзакций
#
# Цель notebook — загрузить данные, проверить качество полей и построить агрегаты
# по типам операций.

# %%
from pathlib import Path

import pandas as pd


DATA_PATH = Path("data/transactions.csv")


# %% [markdown]
# ## Загрузка данных
#
# Загружаем CSV и сразу проверяем размерность, чтобы убедиться, что файл прочитан
# корректно.

# %%
transactions = pd.read_csv(DATA_PATH)

transactions.shape
```

Плохо:

```python
# %%
# Markdown: Анализ транзакций
"""Цель notebook — загрузить данные и построить агрегаты."""
import pandas as pd
transactions = pd.read_csv("data/transactions.csv")
transactions.shape
```

Почему плохо:

- текстовая часть попала в code cell;
- standalone triple-quoted string не является markdown-ячейкой;
- imports, загрузка и проверка результата склеены без структуры.

## Функции и читаемый Python

Хорошо:

```python
# %% [markdown]
# ## Подготовка данных
#
# Нормализуем названия колонок и оставляем только успешные операции. Эти функции
# вынесены отдельно, потому что переиспользуются в нескольких расчётах.

# %%
def normalize_column_names(frame: pd.DataFrame) -> pd.DataFrame:
    """Возвращает dataframe с нормализованными названиями колонок."""
    result = frame.copy()
    result.columns = (
        result.columns.str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )
    return result


def filter_successful_operations(frame: pd.DataFrame) -> pd.DataFrame:
    """Возвращает только успешные операции."""
    return frame.loc[frame["status"].eq("success")].copy()


# %%
transactions = normalize_column_names(transactions)
successful_transactions = filter_successful_operations(transactions)
```

Плохо:

```python
# %%
def normalize_column_names(frame):
    result = frame.copy()
    result.columns = result.columns.str.lower()
    return result
def filter_successful_operations(frame):
    return frame[frame["status"] == "success"]
transactions = filter_successful_operations(normalize_column_names(transactions))
```

Почему плохо:

- функции склеены без двух пустых строк;
- нет типов и docstring, хотя функция уже является самостоятельной единицей логики;
- финальное выражение трудно отлаживать по шагам.

## Pandas pipeline

Хорошо:

```python
# %% [markdown]
# ## Агрегация по каналам
#
# Считаем количество операций, общий объём и медианную сумму по каждому каналу.
# Сортировка по сумме показывает каналы с наибольшим вкладом.

# %%
channel_summary = (
    successful_transactions
    .groupby("channel", as_index=False)
    .agg(
        operations_count=("operation_id", "count"),
        total_amount=("amount", "sum"),
        median_amount=("amount", "median"),
    )
    .sort_values("total_amount", ascending=False)
)

channel_summary
```

Плохо:

```python
# %%
channel_summary = successful_transactions.groupby("channel").agg({"operation_id": "count", "amount": ["sum", "median"]}).reset_index().sort_values(("amount", "sum"), ascending=False)
channel_summary
```

Почему плохо:

- строка слишком длинная и плохо читается в notebook;
- multi-index колонки появляются неявно;
- имена итоговых колонок не выражают бизнес-смысл.

## Проверка качества данных

Хорошо:

```python
# %% [markdown]
# ## Проверка пропусков
#
# Смотрим долю пропусков по ключевым полям. Это помогает понять, можно ли
# использовать поля в фильтрах и группировках без дополнительной очистки.

# %%
required_columns = ["operation_id", "operation_dt", "amount", "channel", "status"]

missing_summary = (
    transactions[required_columns]
    .isna()
    .mean()
    .rename("missing_share")
    .reset_index(names="column")
    .sort_values("missing_share", ascending=False)
)

missing_summary
```

## Визуализация

Хорошо:

```python
# %% [markdown]
# ## Визуализация объёма операций
#
# Показываем топ каналов по сумме операций. Перед построением графика ограничиваем
# выборку, чтобы диаграмма оставалась читаемой.

# %%
import matplotlib.pyplot as plt


top_channels = channel_summary.head(10)

fig, ax = plt.subplots(figsize=(10, 5))
ax.bar(top_channels["channel"], top_channels["total_amount"])
ax.set_title("Топ каналов по сумме операций")
ax.set_xlabel("Канал")
ax.set_ylabel("Сумма операций")
ax.tick_params(axis="x", rotation=45)

plt.tight_layout()
plt.show()
```

Плохо:

```python
# %%
channel_summary.head(10).plot(kind="bar")
```

Почему плохо:

- непонятно, какие поля попали на оси;
- нет заголовка и подписей;
- результат сложнее интерпретировать в готовом notebook.

## Markdown для выводов

Хорошо:

```python
# %% [markdown]
# ## Выводы
#
# - Основной объём операций приходится на мобильный канал.
# - У части строк отсутствует `channel`, поэтому агрегаты по каналам не покрывают
#   весь набор данных.
# - Перед использованием результата в отчёте нужно согласовать правило обработки
#   пропусков.
```

Плохо:

```python
# %%
# Выводы:
# основной объём операций приходится на мобильный канал
# есть пропуски
```

## Workflow создания `.ipynb`

1. Создай `.py` percent-script.
2. Используй `# %% [markdown]` для текста.
3. Используй `# %%` для кода.
4. Вызови `convert_jupyter_notebook` с `mode="py_to_ipynb"`.
5. Не вызывай отдельный formatter: `convert_jupyter_notebook` форматирует notebook
   при записи.

Пример вызова:

```text
convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="analysis.py",
  output_path="analysis.ipynb"
)
```

## Workflow редактирования существующего `.ipynb`

1. Вызови `convert_jupyter_notebook` с `mode="ipynb_to_py"`.
2. Редактируй полученный percent-script.
3. Сохраняй структуру markdown/code cells.
4. Снова вызови `convert_jupyter_notebook` с `mode="py_to_ipynb"`.
5. Если пользователь не просил новый файл, перезапиши исходный notebook.

Пример:

```text
convert_jupyter_notebook(
  mode="ipynb_to_py",
  source_path="analysis.ipynb",
  output_path="analysis.py"
)

convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="analysis.py",
  output_path="analysis.ipynb"
)
```

## Checklist перед завершением

- Есть markdown-заголовок с целью notebook.
- Большие этапы разделены markdown-ячейками.
- Нет `# Markdown:` внутри code cells.
- Нет standalone triple-quoted strings вместо markdown.
- Top-level функции и классы не склеены.
- Кодовые ячейки короткие и выполняют один логический шаг.
- Объяснения и выводы находятся в markdown-ячейках.
- Итоговый `.ipynb` создан или пересобран через `convert_jupyter_notebook`.
