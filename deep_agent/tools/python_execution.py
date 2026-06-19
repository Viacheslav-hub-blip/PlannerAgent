"""Инструмент генерации и выполнения Python-кода для DeepAgent supervisor.

Содержит:
- PythonExecutionResult: контейнер результата выполнения Python-кода.
- ExecutePythonCodeInput: схема аргументов инструмента ``execute_python_code``.
- ExecutePythonCodeTool: LangChain tool выполнения Python-кода в sandbox.
- build_execute_python_code_tool: фабрика инструмента ``execute_python_code``.
- _normalize_code_text: нормализация текста Python-кода.
- _normalize_target_variable: проверка имени целевой переменной результата.
- _execute_python_code: компиляция и выполнение Python-кода.
- _validate_code_policy: базовая проверка непустого Python-кода.
- _working_directory_context: временная смена рабочей директории процесса.
- _get_cwd_execution_lock: получение общего lock для смены cwd.
- _combined_stdio: объединение stdout и stderr.
- _preview_stdio_result: preview результата без целевой переменной.
- _preview_value: preview значения целевой переменной.
- _python_error_possible_causes: вероятные причины ошибки выполнения.
- _python_error_solution_options: варианты исправления ошибки выполнения.
- _python_retry_guidance: инструкция для повторного запуска после ошибки.
- _visible_variable_names: список пользовательских переменных sandbox.
- _is_dataframe: проверка значения на сходство с pandas DataFrame.
- _is_series: проверка значения на сходство с pandas Series.
- _json_default: JSON-сериализация нестандартных объектов.
- _limit_text: ограничение длинного текста.
- _compact_error_message: краткая строка с причиной ошибки.
- _policy_error_payload: компактный JSON-ответ при ошибке статической политики.
- _result_to_json: сериализация результата без служебного traceback при ошибке.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import keyword
import os
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from deep_agent.runtime.python_sandbox import DeepAgentPythonSandbox, SANDBOX_HELPER_NAMES

EXECUTE_PYTHON_CODE_TOOL_NAME = "execute_python_code"
MAX_TEXT_PREVIEW_CHARS = 4_000
MAX_STDIO_CHARS = 8_000
MAX_DATAFRAME_PREVIEW_ROWS = 10
CWD_EXECUTION_LOCK_ATTR = "_deep_agent_sandbox_cwd_lock"
ERROR_RETRY_HINT = (
    "Попробуйте вызвать инструмент с другими параметрами или использовать другой инструмент."
)

@dataclass
class PythonExecutionResult:
    """Результат выполнения Python-кода в sandbox.

    Attributes:
        success: Признак успешного выполнения кода.
        message: Краткое сообщение о результате выполнения.
        generated_code: Нормализованный Python-код, который был выполнен.
        target_variable: Имя переменной результата или пустая строка.
        variable_preview: Компактное описание значения результата.
        execution_output: Текст stdout/stderr, полученный при выполнении.
        error: Краткое описание ошибки.
        traceback_text: Полный traceback ошибки.
        available_variables: Список доступных переменных sandbox.
        possible_causes: Вероятные причины ошибки.
        solution_options: Практические варианты исправления ошибки.
        retry_guidance: Инструкция для повторного запуска после ошибки.
    """

    success: bool
    message: str
    generated_code: str
    target_variable: str
    variable_preview: str = ""
    execution_output: str = ""
    error: str = ""
    traceback_text: str = ""
    available_variables: list[str] | None = None
    possible_causes: list[str] | None = None
    solution_options: list[str] | None = None
    retry_guidance: str = ""

    def to_json(self) -> str:
        """Сериализует результат выполнения в JSON-строку.

        Returns:
            JSON-строка с результатом, stdout/stderr, traceback и подсказками.
        """

        payload = {
            "success": self.success,
            "message": self.message,
            "generated_code": self.generated_code,
            "target_variable": self.target_variable,
            "variable_preview": self.variable_preview,
            "execution_output": self.execution_output,
            "error": self.error,
            "traceback": self.traceback_text,
            "available_variables": self.available_variables or [],
            "possible_causes": self.possible_causes or [],
            "solution_options": self.solution_options or [],
            "retry_guidance": self.retry_guidance,
        }
        return json.dumps(payload, ensure_ascii=False, default=_json_default)


EXECUTE_PYTHON_CODE_DESCRIPTION = """
execute_python_code
---
Назначение:
Генерирует и выполняет Python-код в persistent runtime. Используй инструмент активно,
когда код дает более точный, воспроизводимый и проверяемый результат, чем ручное
рассуждение модели.

Предпочитай инструмент:
- для нетривиальных вычислений, сравнений, преобразований и проверок;
- для генерации и проверки алгоритмов, небольших модулей, функций и примеров использования;
- для прототипирования решения до внесения изменений в исходники проекта;
- для разбора и преобразования структурированных форматов: `list[dict]`, DataFrame, pickle, CSV или JSON;
- для проверки гипотезы на фактических входах перед формулированием вывода;
- для обработки полного `.pkl`, сохраненного middleware после `load_data`, вместо выводов
  по ограниченному preview;
- для построения таблиц, графиков, отчётов и других воспроизводимых артефактов;
- для чтения, записи, удаления и преобразования файлов внутри configured workspace;
- для запуска shell/subprocess-команд через Python, когда это проще выразить кодом;
- для генерации текстового содержимого файла или готового артефакта;
- когда несколько последовательных преобразований проще надежно выразить кодом.

Правило выбора:
- если результат зависит от точного вычисления, структуры данных, поведения алгоритма,
  преобразования формата или проверки условия, сначала выполни код;
- вычисляй такие результаты кодом, когда это повышает точность;
- один содержательный вызов с несколькими связанными операциями лучше серии мелких
  вызовов, если промежуточный результат не нужен для принятия следующего решения.

Аргументы:
- `code`: исполняемый Python-код;
- `target_variable`: необязательное имя переменной с главным результатом. Передавай
  только когда результат удобно сохранить в переменную и нужен preview значения;
- `description`: краткая цель вычисления на русском языке для трассировки.

Доступные helpers:
- `PROJECT_ROOT`: корень текущего workspace;
- `WORKSPACE_ROOT`: корень текущего workspace из настроек `workspace_root`;
- `TOOL_OUTPUTS_DIR`: каталог текущей сессии из настроек `tool_outputs_dir` для `.pkl` и созданных артефактов;
- `read_pickle_file(path)`: чтение pickle по локальному пути из tool output;
- `describe_pickle_file(path)`: тип, число строк, колонки и preview;
- `rows_to_dataframe(rows)`: преобразование `list[dict]` в DataFrame;
- `pd`, `np`: pandas и numpy, если они установлены;
- пользовательские переменные сохраняются между вызовами в одной сессии.

Хорошее решение: сгенерировать и проверить самостоятельную функцию.
```python
def chunked(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[index:index + size] for index in range(0, len(items), size)]

assert chunked([1, 2, 3], 2) == [[1, 2], [3]]
result = chunked([1, 2, 3, 4], 3)
```
Если нужен preview значения, передай `target_variable="result"`.

Хорошее решение: сохранить запрошенный артефакт в каталог текущей сессии.
```python
from pathlib import Path
output_path = Path(TOOL_OUTPUTS_DIR) / "generated_report.json"
output_path.write_text('{"status": "ok"}', encoding="utf-8")
print(output_path)
```
Для задач, где главным результатом является созданный файл, `target_variable` можно не передавать:
достаточно stdout или факта успешного выполнения.

Работа с путями:
- для workspace-файлов используй полный путь из configured root или `Path(WORKSPACE_ROOT)`;
- для временных артефактов используй `Path(TOOL_OUTPUTS_DIR)`;
- при работе с pickle бери точный `workspace_file` из результата tool.

Обработка ошибок:
- для stdout, файловых операций, side effects и действий без единственного Python-значения
  не передавай `target_variable`;
- если инструмент вернул ошибку, измени код с учетом причины и повтори вызов;
- если Python не подходит для следующего шага, используй другой доступный tool.
""".strip()


class ExecutePythonCodeInput(BaseModel):
    """Аргументы tool ``execute_python_code``: код, опциональная переменная результата, описание."""

    code: str = Field(
        description=(
            "Python-код для точного и воспроизводимого вычисления. Используй helpers "
            "`read_pickle_file`, `rows_to_dataframe`, `pd`, `np` и переменные из "
            "предыдущих вызовов. Связанные преобразования объединяй в один вызов."
        ),
    )
    target_variable: str | None = Field(
        default=None,
        description=(
            "Необязательное имя переменной, в которую нужно сохранить главный результат. "
            "Передавай только если нужен preview значения этой переменной. Если результатом "
            "является stdout, созданный файл или другой side effect, опусти аргумент."
        ),
    )
    description: str = Field(
        default="",
        description="Краткая цель кода на русском языке для трассировки.",
    )


class ExecutePythonCodeTool(BaseTool):
    """LangChain tool выполнения Python-кода в persistent runtime DeepAgent.

    Перед выполнением код нормализуется и проверяется только на непустое значение.
    Импорты, файловые операции, удаление файлов и subprocess доступны внутри настроенного
    workspace. Само выполнение и формирование информативного результата делегируются
    локальной переиспользуемой функции ``_execute_python_code``.

    Успешный результат возвращается строкой JSON. При ошибке возвращается только строка
    ``ТипИсключения: сообщение`` без traceback и служебных метаданных.
    """

    name: str = EXECUTE_PYTHON_CODE_TOOL_NAME
    description: str = EXECUTE_PYTHON_CODE_DESCRIPTION
    args_schema: type[BaseModel] = ExecutePythonCodeInput

    _sandbox: DeepAgentPythonSandbox = PrivateAttr()

    def __init__(self, *, sandbox: DeepAgentPythonSandbox) -> None:
        """Создаёт tool поверх готового persistent sandbox.

        Args:
            sandbox: Песочница с общими переменными между вызовами в одной сессии.
        """

        super().__init__()
        self._sandbox = sandbox

    def _run(
        self,
        code: str,
        target_variable: str | None = None,
        description: str = "",
        **_: Any,
    ) -> str:
        """Синхронно проверяет входные аргументы, выполняет код и сериализует результат.

        Args:
            code: Python-код для выполнения.
            target_variable: Необязательное имя переменной результата или ``None``.
            description: Краткая цель кода для трассировки.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            JSON-строка с результатом или краткая строка ошибки.
        """

        generated_code = _normalize_code_text(str(code or ""))
        try:
            _validate_code_policy(generated_code)
            _normalize_target_variable(target_variable)
        except Exception as exc:
            return _policy_error_payload(
                generated_code,
                target_variable,
                exc,
                sandbox=self._sandbox,
            )

        result = _execute_python_code(
            sandbox=self._sandbox,
            code=generated_code,
            target_variable=target_variable,
            description=description,
        )
        return _result_to_json(result, sandbox=self._sandbox)

    async def _arun(
        self,
        code: str,
        target_variable: str | None = None,
        description: str = "",
        **_: Any,
    ) -> str:
        """Асинхронная обёртка над :meth:`_run` (выполнение синхронное).

        Args:
            code: Python-код для выполнения.
            target_variable: Имя переменной результата или ``None``.
            description: Краткая цель кода.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            JSON-строка с результатом или краткая строка ошибки.
        """

        return self._run(
            code=code,
            target_variable=target_variable,
            description=description,
        )


def build_execute_python_code_tool(sandbox: DeepAgentPythonSandbox) -> ExecutePythonCodeTool:
    """Фабрика tool ``execute_python_code`` для supervisor.

    Args:
        sandbox: Persistent sandbox с helpers чтения pickle и аналитическими библиотеками.

    Returns:
        Готовый ``ExecutePythonCodeTool`` для регистрации в списке tools.
    """

    return ExecutePythonCodeTool(sandbox=sandbox)


def _normalize_code_text(code: str) -> str:
    """Нормализует текст Python-кода перед проверкой.

    Args:
        code: Исходный код, переданный в инструмент.

    Returns:
        Исходный код или код с преобразованными JSON-escaped переносами строк.
    """

    raw_code = str(code or "")
    try:
        ast.parse(raw_code, mode="exec")
        return raw_code
    except SyntaxError as exc:
        message = str(exc)

    if "\\n" not in raw_code:
        return raw_code
    if "unexpected character after line continuation character" not in message:
        return raw_code
    return raw_code.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def _normalize_target_variable(target_variable: str | None) -> str | None:
    """Проверяет имя целевой переменной результата.

    Args:
        target_variable: Имя переменной результата или ``None``.

    Returns:
        Нормализованное имя переменной или ``None``.

    Raises:
        ValueError: Имя переменной не является валидным Python-идентификатором.
    """

    name = str(target_variable or "").strip()
    if not name:
        return None
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError("target_variable must be a valid Python identifier, for example result_df")
    return name


def _execute_python_code(
    *,
    sandbox: DeepAgentPythonSandbox,
    code: str,
    target_variable: str | None = None,
    description: str = "",
) -> PythonExecutionResult:
    """Выполняет Python-код в persistent sandbox.

    Args:
        sandbox: Sandbox с общими переменными и рабочими директориями.
        code: Python-код для проверки, компиляции и выполнения.
        target_variable: Опциональное имя переменной результата.
        description: Краткое описание цели кода для сообщения об успехе.

    Returns:
        ``PythonExecutionResult`` с результатом выполнения или подробной ошибкой.
    """

    generated_code = _normalize_code_text(str(code or ""))
    try:
        target_name = _normalize_target_variable(target_variable)
        _validate_code_policy(generated_code)
        compiled = compile(generated_code, "<execute_python_code>", "exec")
    except Exception as exc:
        return PythonExecutionResult(
            success=False,
            message="Python code did not pass validation or compilation.",
            generated_code=generated_code,
            target_variable=str(target_variable or ""),
            error=f"{exc.__class__.__name__}: {exc}",
            traceback_text=_limit_text(traceback.format_exc(), max_chars=MAX_STDIO_CHARS),
            available_variables=_visible_variable_names(sandbox.globals),
            possible_causes=_python_error_possible_causes(exc),
            solution_options=_python_error_solution_options(exc),
            retry_guidance=_python_retry_guidance(),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with (
            _working_directory_context(sandbox.working_directory),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exec(compiled, sandbox.globals, sandbox.globals)
    except Exception as exc:
        return PythonExecutionResult(
            success=False,
            message="Python code execution failed. Fix generated_code and retry.",
            generated_code=generated_code,
            target_variable=target_name or "",
            execution_output=_combined_stdio(stdout, stderr),
            error=f"{exc.__class__.__name__}: {exc}",
            traceback_text=_limit_text(traceback.format_exc(), max_chars=MAX_STDIO_CHARS),
            available_variables=_visible_variable_names(sandbox.globals),
            possible_causes=_python_error_possible_causes(exc),
            solution_options=_python_error_solution_options(exc),
            retry_guidance=_python_retry_guidance(),
        )

    execution_output = _combined_stdio(stdout, stderr)
    purpose = f" Purpose: {description.strip()}" if description.strip() else ""
    if target_name is None:
        return PythonExecutionResult(
            success=True,
            message=f"Python code executed successfully.{purpose}",
            generated_code=generated_code,
            target_variable="",
            variable_preview=_preview_stdio_result(execution_output),
            execution_output=execution_output,
            available_variables=_visible_variable_names(sandbox.globals),
        )

    if target_name not in sandbox.globals:
        return PythonExecutionResult(
            success=False,
            message=(
                "Python code executed but did not create target_variable. "
                f"Create variable '{target_name}' and retry."
            ),
            generated_code=generated_code,
            target_variable=target_name,
            execution_output=execution_output,
            error=f"MissingTargetVariable: {target_name}",
            available_variables=_visible_variable_names(sandbox.globals),
            possible_causes=[f"Код выполнился, но не создал переменную '{target_name}'."],
            solution_options=[
                f"Добавь присваивание результата в переменную '{target_name}'.",
                "Проверь, что присваивание выполняется на всех ветках кода.",
                "Если достаточно stdout, повтори вызов без target_variable.",
            ],
            retry_guidance=_python_retry_guidance(),
        )

    return PythonExecutionResult(
        success=True,
        message=f"Python code executed successfully.{purpose}",
        generated_code=generated_code,
        target_variable=target_name,
        variable_preview=_preview_value(sandbox.globals[target_name]),
        execution_output=execution_output,
        available_variables=_visible_variable_names(sandbox.globals),
    )


def _validate_code_policy(code: str) -> None:
    """Проверяет, что Python-код передан для выполнения.

    Args:
        code: Python-код, который нужно проверить.

    Raises:
        ValueError: Код пустой.
    """
    if not str(code or "").strip():
        raise ValueError("code is required")


@contextlib.contextmanager
def _working_directory_context(directory: Path | None):
    """Временно переключает рабочую директорию процесса.

    Args:
        directory: Рабочая директория sandbox или ``None``.

    Yields:
        ``None``. После выхода исходная директория восстанавливается.
    """

    with _get_cwd_execution_lock():
        if directory is None:
            yield
            return
        if not directory.exists() or not directory.is_dir():
            raise FileNotFoundError(f"Sandbox working directory does not exist: {directory}")

        previous_directory = Path.cwd()
        os.chdir(directory)
        try:
            yield
        finally:
            os.chdir(previous_directory)


def _get_cwd_execution_lock() -> threading.RLock:
    """Возвращает общий lock для временной смены текущей директории.

    Returns:
        ``threading.RLock`` для защиты ``os.chdir`` во время выполнения кода.
    """

    lock = getattr(builtins, CWD_EXECUTION_LOCK_ATTR, None)
    if lock is None:
        lock = threading.RLock()
        setattr(builtins, CWD_EXECUTION_LOCK_ATTR, lock)
    return lock


def _combined_stdio(stdout: io.StringIO, stderr: io.StringIO) -> str:
    """Объединяет stdout и stderr в ограниченную строку.

    Args:
        stdout: Буфер стандартного вывода.
        stderr: Буфер стандартной ошибки.

    Returns:
        Строка с stdout/stderr или пустая строка.
    """

    parts: list[str] = []
    out_text = stdout.getvalue()
    err_text = stderr.getvalue()
    if out_text:
        parts.append(f"stdout:\n{out_text}")
    if err_text:
        parts.append(f"stderr:\n{err_text}")
    return _limit_text("\n".join(parts), max_chars=MAX_STDIO_CHARS)


def _preview_stdio_result(stdio: str) -> str:
    """Формирует preview для успешного выполнения без целевой переменной.

    Args:
        stdio: Текст stdout/stderr после выполнения кода.

    Returns:
        Краткий preview консольного вывода или пустая строка.
    """

    text = str(stdio or "").strip()
    if not text:
        return ""
    return _limit_text(f"type: console_output\n{text}", max_chars=MAX_TEXT_PREVIEW_CHARS)


def _preview_value(value: Any) -> str:
    """Формирует компактный preview значения результата.

    Args:
        value: Значение переменной результата.

    Returns:
        Строка с типом и кратким содержимым значения.
    """

    if _is_dataframe(value):
        shape = getattr(value, "shape", None)
        columns = list(getattr(value, "columns", []))
        dtypes = {str(column): str(dtype) for column, dtype in getattr(value, "dtypes", {}).items()}
        head_text = value.head(MAX_DATAFRAME_PREVIEW_ROWS).to_string()
        return _limit_text(
            "\n".join(
                [
                    "type: DataFrame",
                    f"shape: {shape}",
                    f"columns: {columns}",
                    f"dtypes: {dtypes}",
                    "head:",
                    head_text,
                ]
            ),
            max_chars=MAX_TEXT_PREVIEW_CHARS,
        )

    if _is_series(value):
        shape = getattr(value, "shape", None)
        head_text = value.head(MAX_DATAFRAME_PREVIEW_ROWS).to_string()
        return _limit_text(
            f"type: Series\nshape: {shape}\nhead:\n{head_text}",
            max_chars=MAX_TEXT_PREVIEW_CHARS,
        )

    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        text = repr(value)
    return _limit_text(f"type: {type(value).__name__}\nvalue:\n{text}", max_chars=MAX_TEXT_PREVIEW_CHARS)


def _python_error_possible_causes(exc: Exception) -> list[str]:
    """Возвращает вероятные причины ошибки выполнения кода.

    Args:
        exc: Исключение валидации, компиляции или выполнения.

    Returns:
        Список причин, которые помогают исправить следующий вызов.
    """

    if isinstance(exc, SyntaxError):
        return ["Сгенерированный Python-код содержит синтаксическую ошибку."]
    if isinstance(exc, NameError):
        return ["Код ссылается на переменную, которой нет в sandbox."]
    if isinstance(exc, KeyError):
        return ["В DataFrame/dict отсутствует запрошенная колонка или ключ."]
    if isinstance(exc, ImportError):
        return ["Импортируемая библиотека недоступна в текущем Python runtime."]
    if isinstance(exc, ValueError):
        return ["Аргумент, имя переменной или операция имеют недопустимое значение."]
    return ["Код столкнулся с ошибкой выполнения; точная причина указана в traceback."]


def _python_error_solution_options(exc: Exception) -> list[str]:
    """Возвращает варианты исправления ошибки выполнения кода.

    Args:
        exc: Исключение валидации, компиляции или выполнения.

    Returns:
        Список практических вариантов для повторного запуска.
    """

    options = [
        "Проверь available_variables и используй только существующие имена переменных.",
        "Исправь generated_code с учетом traceback и повтори execute_python_code.",
        "Если нужна именованная переменная, сохрани результат в target_variable.",
        "Если достаточно print-вывода, повтори вызов без target_variable и читай execution_output.",
    ]
    if isinstance(exc, SyntaxError):
        options.insert(0, "Исправь синтаксис Python-кода перед повторным запуском.")
    if isinstance(exc, NameError):
        options.insert(0, "Замени отсутствующую переменную на существующую из available_variables или создай ее явно.")
    if isinstance(exc, KeyError):
        options.insert(0, "Проверь реальные названия колонок через preview/schema перед обращением к ним.")
    if isinstance(exc, ImportError):
        options.insert(0, "Используй доступную библиотеку, установи зависимость другим tool или примени pandas/numpy helpers.")
    return options


def _python_retry_guidance() -> str:
    """Возвращает инструкцию по повторному вызову после ошибки.

    Returns:
        Текст с правилом исправления кода перед retry.
    """

    return (
        "Не повторяй тот же код без изменений. Используй generated_code, error, "
        "traceback и available_variables из этого ответа, исправь причину и повтори execute_python_code."
    )


def _visible_variable_names(globals_dict: dict[str, Any]) -> list[str]:
    """Возвращает список пользовательских переменных sandbox.

    Args:
        globals_dict: Словарь глобальных переменных sandbox.

    Returns:
        Отсортированный список имен без служебных и встроенных переменных.
    """

    return sorted(
        name
        for name in globals_dict
        if not str(name).startswith("__") and name not in vars(builtins)
    )


def _is_dataframe(value: Any) -> bool:
    """Проверяет, похоже ли значение на pandas DataFrame.

    Args:
        value: Проверяемое значение.

    Returns:
        ``True``, если значение похоже на DataFrame.
    """

    return value.__class__.__name__ == "DataFrame" and hasattr(value, "head")


def _is_series(value: Any) -> bool:
    """Проверяет, похоже ли значение на pandas Series.

    Args:
        value: Проверяемое значение.

    Returns:
        ``True``, если значение похоже на Series.
    """

    return value.__class__.__name__ == "Series" and hasattr(value, "head")


def _json_default(value: Any) -> Any:
    """Преобразует нестандартное значение к JSON-совместимому виду.

    Args:
        value: Значение, которое не смог сериализовать стандартный JSON.

    Returns:
        JSON-совместимое значение или ``repr(value)``.
    """

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return repr(value)


def _limit_text(value: str | None, *, max_chars: int) -> str:
    """Обрезает текст до заданной длины.

    Args:
        value: Исходный текст или ``None``.
        max_chars: Максимальное количество символов.

    Returns:
        Исходный или обрезанный текст с пометкой ``[truncated]``.
    """

    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated]"


def _policy_error_payload(
    generated_code: str,
    target_variable: str | None,
    exc: Exception,
    *,
    sandbox: DeepAgentPythonSandbox,
) -> str:
    """Формирует компактный JSON-ответ при провале статической проверки кода.

    Args:
        generated_code: Нормализованный код, который не прошёл проверку.
        target_variable: Запрошенное имя переменной результата или ``None``.
        exc: Исключение валидации политики.
        sandbox: Sandbox для перечисления доступных переменных и путей.

    Returns:
        Краткая строка с причиной ошибки.
    """
    del generated_code, target_variable, sandbox
    return _compact_error_message(f"{exc.__class__.__name__}: {exc}")


def _compact_error_message(error: str) -> str:
    """Формирует минимальную строку ошибки для передачи в контекст агента.

    Args:
        error: Последняя строка исключения в формате ``Тип: сообщение``.

    Returns:
        Строка ``Тип: сообщение`` без traceback, JSON и служебных метаданных.
    """

    message = str(error or "UnknownError").strip()
    if ERROR_RETRY_HINT in message:
        return message
    return f"{message}\n{ERROR_RETRY_HINT}"


def _result_to_json(result: PythonExecutionResult, *, sandbox: DeepAgentPythonSandbox) -> str:
    """Дополняет результат выполнения контекстом sandbox и сериализует в JSON.

    Args:
        result: Результат ``_execute_python_code`` (успех или ошибка выполнения).
        sandbox: Sandbox для добавления helpers и разрешённых путей в ответ.

    Returns:
        JSON-строка при успехе или краткая строка причины при неуспехе.
    """

    if not result.success:
        return _compact_error_message(result.error)

    payload = json.loads(result.to_json())
    payload["sandbox_helpers"] = sorted(SANDBOX_HELPER_NAMES)
    payload["working_directory"] = str(sandbox.working_directory)
    payload["tool_outputs_dir"] = str(sandbox.tool_outputs_dir)
    payload["readable_roots"] = [str(path) for path in sandbox.readable_roots]
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "EXECUTE_PYTHON_CODE_DESCRIPTION",
    "EXECUTE_PYTHON_CODE_TOOL_NAME",
    "ExecutePythonCodeTool",
    "build_execute_python_code_tool",
]
