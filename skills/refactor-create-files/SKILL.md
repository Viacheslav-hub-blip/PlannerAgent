---
name: refactor-create-files
description: "Используй этот skill для создания и рефакторинга файлов кода, включая `.py` и Jupyter Notebook `.ipynb`"
---

# Рефакторинг и создание файлов

Используй этот skill, когда пользователь просит создать, доработать или
отрефакторить файл проекта. Skill применим к обычным исходным файлам и notebook.

Этот skill может использоваться только `coding-agent`.

## Последовательность шагов

1. **Перед правками проанализируй текущий файл и соседний код**:
   - какие данные, функции, классы, типы и публичные контракты уже есть;
   - как код вызывается и в какой последовательности выполняется;
   - какие inputs, outputs, exceptions и side effects нужно сохранить;
   - какие есть комментарии автора

2. **Если файл существует, полностью прочитай релевантные участки до записи и
   продумай правку**:
   - что именно нужно изменить и какие части файла лучше не трогать;
   - как сохранить сигнатуры, типы, возвращаемые значения и ошибки;
   - какие улучшения нужны для текущей задачи, а какие являются лишним
     рефакторингом.

3. **Вноси изменения в порядке использования кода**:
   - imports, constants и настройки;
   - схемы данных и типы;
   - функции;
   - основная бизнес-логика;

4. **Сохраняй поведение пользователя**:
   - не меняй публичные имена, параметры, возвращаемые значения и ошибки без
     явного запроса;
   - оставляй комментарии пользователя;
   - не добавляй абстракции, которые не нужны для текущей задачи.

5. **Улучшай качество кода там, где это связано с задачей**:
   - добавляй type hints к измененным и новым функциям, методам, классам и
     структурам данных;
   - пиши docstring на русском языке для всех измененных и новых функций,
     классов и `BaseModel`-схем;
   - в docstring описывай входные данные, возвращаемое значение и важные
     исключения;
   - добавляй комментарии через `#` возле каждой новой строки кода, чтобы обьяснить пользователю что в ней происходит

6. **Перед завершением сравни обновленную версию с исходной и проверь, что логика
   не потеряна**.

7. **не забывай конвертировать .py файлы обратно в .ipynb**

8. **Сохраняй файл в ту же директории где был исходный файл а не в арткфакты**

9. **При конвертации через `convert_jupyter_notebook` не меняй имя файла без
   расширения: можно выбрать путь и нужное расширение, но stem должен совпадать**

## Примеры вызова инструментов по шагам

Используй эти примеры как шаблоны. Подставляй реальные пути, имена файлов и аргументы из задачи.

1. Анализ текущего файла и соседнего кода:

```text
read_file(file_path="/project/src/module.py")
list_files(directory_path="/project/src")
search_files(query="normalize_column_names", directory_path="/project")
```

2. Полное чтение релевантных участков перед записью:

```text
read_file(file_path="/project/src/module.py", start_line=1, end_line=220)
read_file(file_path="/project/tests/test_module.py")
```

3. Внесение изменений в порядке использования кода:

```text
write_file(file_path="/project/src/module.py", content="<полное обновленное содержимое файла>")
```

4. Сохранение поведения пользователя:

```text
search_files(query="changed_function_name", directory_path="/project")
read_file(file_path="/project/tests/test_module.py")
```

5. Улучшение качества кода:

```text
write_file(file_path="/project/src/module.py", content="<код с type hints, docstring и нужными комментариями>")
```

6. Сравнение обновленной версии с исходной:

```text
read_file(file_path="/project/src/module.py")
execute(command="git diff -- /project/src/module.py")
```

7. Конвертация `.py` обратно в `.ipynb`:

```text
convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="/project/notebooks/analysis.py",
  output_path="/project/notebooks/analysis.ipynb"
)
```

8. Сохранение файла в исходной директории:

```text
write_file(file_path="/project/src/module.py", content="<полное обновленное содержимое файла>")
```

## Если редактируешь или создаешь `.py` файл

Не используй Python, shell-команды или временные скрипты для записи `.py` файла, если доступен `write_file`.
Записывай `.py` файл через `write_file` полным содержимым.

Пример записи нового `.py` файла:

```text
write_file(
  file_path="/project/src/normalization.py",
  content="\"\"\"Файл содержит функции для нормализации табличных данных.\n\nФункции:\n    normalize_column_names: Возвращает dataframe с нормализованными названиями колонок.\n\"\"\"\n\nimport pandas as pd\n\n\ndef normalize_column_names(frame: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"Возвращает dataframe с нормализованными названиями колонок.\n\n    Args:\n        frame: Исходный dataframe с произвольными названиями колонок.\n\n    Returns:\n        DataFrame с очищенными и приведенными к snake_case названиями колонок.\n    \"\"\"\n    result = frame.copy()\n    result.columns = (\n        result.columns.str.strip()\n        .str.lower()\n        .str.replace(\" \", \"_\", regex=False)\n    )\n    return result\n"
)
```

Пример перезаписи существующего `.py` файла после анализа:

```text
read_file(file_path="/project/src/normalization.py")
write_file(file_path="/project/src/normalization.py", content="<полное обновленное содержимое файла>")
```

1. В начале файла добавь или обнови описание файла:
   - кратко опиши назначение файла;
   - перечисли основные функции и классы, которые содержит файл.

2. Соблюдай читаемую структуру Python:
   - стандартные imports отделяй от сторонних и локальных;
   - константы размещай до функций и классов;
   - функции верхнего уровня разделяй двумя пустыми строками;
   - длинные pandas pipeline и цепочки вызовов переноси по строкам.

3. Для функций и классов используй docstring:

```python
def normalize_column_names(frame: pd.DataFrame) -> pd.DataFrame:
    """Возвращает dataframe с нормализованными названиями колонок.

    Args:
        frame: Исходный dataframe с произвольными названиями колонок.

    Returns:
        DataFrame с очищенными и приведенными к snake_case названиями колонок.
    """
    result = frame.copy()
    result.columns = (
        result.columns.str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )
    return result
```

4. Для `BaseModel`-схем обязательно добавляй docstring класса и описания полей,
   если они помогают понять контракт:

```python
class TransactionFilter(BaseModel):
    """Схема фильтров для отбора транзакций.

    Attributes:
        status: Статус операции, который нужно оставить в выборке.
        min_amount: Минимальная сумма операции.
    """

    status: str = Field(description="Статус операции для фильтрации.")
    min_amount: float = Field(description="Минимальная сумма операции.")
```



Если `ruff` недоступен, явно укажи это в отчете и приложи текст ошибки tool.

## Если редактируешь или создаешь `.ipynb` файл

Перед записью notebook мысленно разложи работу на ячейки:

1. Markdown-ячейка объясняет, зачем нужен следующий шаг.
2. Code-ячейка выполняет один шаг.
3. Итоговый `.ipynb` создается через `write_file` или пересобирается через
   `convert_jupyter_notebook` при явной конвертации.


### Создание notebook

1. Вызови `write_file` сразу с путем `.ipynb`.
2. Передай в `content` Python/percent-script.
3. Используй `# %% [markdown]` или верхнеуровневые строки с `#` для markdown-ячеек.
4. Используй `# %%` для явного разделения code-ячеек.
5. Не записывай сырой JSON notebook вручную: `write_file` сам соберет `.ipynb`.

```text
write_file(file_path="/file_1.ipynb", content="<complete percent-script>")
```

### Важно: для нового `.ipynb` можно использовать `write_file` напрямую. Для явной конвертации между `.py` и `.ipynb` используй `convert_jupyter_notebook`.

### Редактирование notebook

1. Вызови `convert_jupyter_notebook` с `mode="ipynb_to_py"`.
2. Редактируй полученный percent-script.
3. Сохраняй структуру markdown/code cells.
4. Старайся сохранять близкое к исходному количество ячеек и не склеивать весь
   код в одну ячейку.
5. Снова вызови `convert_jupyter_notebook` с `mode="py_to_ipynb"`.
6. Если пользователь не просил новый файл, перезапиши исходный notebook.

```text
convert_jupyter_notebook(
  mode="ipynb_to_py",
  source_path="/file_1.ipynb",
  output_path="/file_1.py"
)
convert_jupyter_notebook(
  mode="py_to_ipynb",
  source_path="/file_1.py",
  output_path="/file_1.ipynb"
)
```

### Стиль notebook

Хорошо:

```python
# %% [markdown]
# ## Загрузка данных
#
# Загружаем CSV и проверяем размерность, чтобы убедиться, что файл прочитан
# корректно.

# %%
from pathlib import Path

import pandas as pd


DATA_PATH = Path("artifacts/transactions.csv")

transactions = pd.read_csv(DATA_PATH)
transactions.shape
```

Плохо:

```python
# %%
"""Загрузка данных."""
import pandas as pd
transactions = pd.read_csv("artifacts/transactions.csv")
transactions.shape
```

Текстовая часть должна быть markdown-ячейкой,


## Формат отчета

После сохранения изменений отвечай пользователю на русском языке и показывай
главные изменения:

```text
Изменено:

1. <файл или участок>
   Было:
   <прошлый фрагмент кода>

   Стало:
   <новый фрагмент кода>
```
