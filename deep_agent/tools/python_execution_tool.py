"""Инструмент persistent Python REPL для DeepAgent.

Содержит:
- PythonExecutionResult: контейнер результата выполнения Python-кода.
- PythonInput: схема аргументов инструмента ``python``.
- PythonTool: LangChain tool выполнения Python-кода в persistent runtime.
- _normalize_code_text: нормализация текста Python-кода.
- _execute_python_repl: компиляция и выполнение Python-кода.
- _validate_code_policy: базовая проверка непустого Python-кода.
- _working_directory_context: временная смена рабочей директории процесса.
- _get_cwd_execution_lock: получение общего lock для смены cwd.
- _combined_stdio: объединение stdout и stderr.
- _python_error_possible_causes: вероятные причины ошибки выполнения.
- _python_error_solution_options: варианты исправления ошибки выполнения.
- _python_retry_guidance: инструкция для повторного запуска после ошибки.
- _visible_variable_names: список пользовательских переменных sandbox.
- _artifact_file_snapshot: снимок файлов артефактов до выполнения Python-кода.
- _changed_artifacts: список созданных или измененных artifact-файлов.
- _workspace_artifact_path: преобразование artifact-пути в workspace-путь.
- _artifact_type: определение типа artifact по расширению.
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
import os
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from deep_agent.execution.python_sandbox import DeepAgentPythonSandbox, SANDBOX_HELPER_NAMES
from deep_agent.tools.python_execution_helpers import (
    artifact_preview,
    normalize_workspace_path_arguments,
)

PYTHON_TOOL_NAME = "python"
MAX_STDIO_CHARS = 8_000
CWD_EXECUTION_LOCK_ATTR = "_deep_agent_sandbox_cwd_lock"
ERROR_RETRY_HINT = (
    "Попробуйте вызвать инструмент с другими параметрами или использовать другой инструмент."
)
PYTHON_VALIDATION_FAILED_MESSAGE = "Python-код не прошёл проверку или компиляцию."
PYTHON_EXECUTION_FAILED_MESSAGE = "Выполнение Python-кода завершилось ошибкой. Исправь generated_code и повтори вызов."
PYTHON_EXECUTION_SUCCESS_MESSAGE = "Python-код выполнен успешно."

@dataclass
class PythonExecutionResult:
    """Результат выполнения Python-кода в sandbox.

    Attributes:
        success: Признак успешного выполнения кода.
        message: Краткое сообщение о результате выполнения.
        generated_code: Нормализованный Python-код, который был выполнен.
        execution_output: Текст stdout/stderr, полученный при выполнении.
        artifacts: Созданные или изменённые файлы в каталоге артефактов.
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
    execution_output: str = ""
    artifacts: list[dict[str, Any]] | None = None
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
            "execution_output": self.execution_output,
            "artifacts": self.artifacts or [],
            "error": self.error,
            "traceback": self.traceback_text,
            "available_variables": self.available_variables or [],
            "possible_causes": self.possible_causes or [],
            "solution_options": self.solution_options or [],
            "retry_guidance": self.retry_guidance,
        }
        return json.dumps(payload, ensure_ascii=False, default=_json_default)


PYTHON_TOOL_DESCRIPTION = """
python
---
Назначение:
Используй этот инструмент для выполнения Python-кода

Используй для:
- для вычислений, сравнений, преобразований и проверок;
- для обработки `.pkl`, CSV, JSON, DataFrame и результатов `load_data`;
- для проверки гипотезы на фактических входах перед формулированием вывода;
- для генерации CSV/JSON/Markdown-выгрузок, таблиц, графиков и других файлов, связанных с обработкой данных;
- для обработки полного `.pkl` или `.jsonl`, сохраненного после `load_data`, вместо выводов
  по ограниченному preview;

Аргументы:
- `code`:  Python-код;
- `description`: краткая цель вычисления.

Доступные helpers:
- `PROJECT_ROOT`: корень текущего workspace;
- `WORKSPACE_ROOT`: корень текущего workspace из настроек `workspace_root`;
- `ARTIFACTS_DIR`: реальный путь ОС к единому каталогу `/artifacts`;
- `resolve_workspace_path(path)`: преобразование workspace-пути `/artifacts/...` в реальный путь ОС для pandas/open;
- `read_pickle_file(path)`: чтение pickle по локальному пути из tool output;
- `describe_pickle_file(path)`: тип, число строк, колонки и preview;
- `rows_to_dataframe(rows)`: преобразование `list[dict]` в DataFrame;
- `pd`, `np`: pandas и numpy, если они установлены;
- пользовательские переменные сохраняются между вызовами в одной сессии.

Для JSONL artifact из Spark `load_data` используй:
`df = pd.read_json(resolve_workspace_path(r"<artifact_path>"), lines=True)`.

Правило путей:
- В Python-коде не передавай строки вида `"/file"` или `"/artifacts/file.csv"` напрямую в pandas, open, pathlib или subprocess.
- Сначала преобразуй workspace-путь в реальный путь: `path = resolve_workspace_path(r"/file")`.
- Для новых файлов используй `Path(ARTIFACTS_DIR) / "file.csv"` или `Path(WORKSPACE_ROOT) / "relative/file"`.
- Если в `generated_code` после вызова видно, что путь был автоматически заменен на `resolve_workspace_path(...)`, используй
  этот исправленный вариант в следующих вызовах. Для переменных с путями всё равно нормализуй значение явно.

Видимый результат:
- результат доступен агенту только если он напечатан через `print(...)`;
- или если файл создан/изменён обычным Python-кодом внутри `ARTIFACTS_DIR` и появился в `artifacts` с `change`,
  `size_bytes`, `absolute_path` и `preview`;

Плохое решение: присвоить результат без вывода.
```python
result = df.groupby("rule").size()
```

Хорошее решение: явно вывести компактный результат.
```python
result = df.groupby("rule").size()
print(result.to_string())
```

Плохой вызов: передать несуществующий аргумент.
```json
{"code": "print(result)", "target_variable": "result"}
```

Хороший вызов: использовать только публичный контракт.
```json
{"code": "print(result)", "description": "Показать итог расчета"}
```

Хорошее решение: сгенерировать и проверить самостоятельную функцию.
```python
def chunked(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[index:index + size] for index in range(0, len(items), size)]

assert chunked([1, 2, 3], 2) == [[1, 2], [3]]
result = chunked([1, 2, 3, 4], 3)
print(result)
```

Хорошее решение: сохранить JSON-выгрузку или результат преобразования данных обычным Python-кодом.
```python
from pathlib import Path
import json

output_path = Path(ARTIFACTS_DIR) / "generated_report.json"
output_path.write_text(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2), encoding="utf-8")
print(output_path)
```

Хорошее решение: сохранить DataFrame обычным pandas-кодом в каталог артефактов.
```python
from pathlib import Path

output_path = Path(ARTIFACTS_DIR) / "export.csv"
df.to_csv(output_path, index=False)
print(output_path)
```

Плохое решение: строковый workspace-путь с начальным `/`.
```python
df.to_csv("/artifacts/export.csv", index=False)
```
""".strip()


class PythonInput(BaseModel):
    """Аргументы tool ``python``: код и краткое описание цели выполнения."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        description=(
            "Python-код для точного и воспроизводимого вычисления. Используй helpers "
            "`resolve_workspace_path`, `read_pickle_file`, `rows_to_dataframe`, `ARTIFACTS_DIR`, `pd`, `np` "
            "и переменные из предыдущих вызовов. Важные "
            "результаты выводи через print()."
        ),
    )
    description: str = Field(
        default="",
        description="Краткая цель кода на русском языке для трассировки.",
    )


class PythonTool(BaseTool):
    """LangChain tool выполнения Python-кода в persistent runtime DeepAgent.

    Перед выполнением код нормализуется и проверяется только на непустое значение.
    Импорты, файловые операции, удаление файлов и subprocess доступны внутри настроенного
    workspace. Само выполнение и формирование информативного результата делегируются
    локальной переиспользуемой функции ``_execute_python_repl``.

    Успешный результат возвращается строкой JSON. При ошибке возвращается только строка
    ``ТипИсключения: сообщение`` без traceback и служебных метаданных.
    """

    name: str = PYTHON_TOOL_NAME
    description: str = PYTHON_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = PythonInput

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
        description: str = "",
        **_: Any,
    ) -> str:
        """Синхронно проверяет входные аргументы, выполняет код и сериализует результат.

        Args:
            code: Python-код для выполнения.
            description: Краткая цель кода для трассировки.
            **_: Служебные аргументы LangChain, не используются.

        Returns:
            JSON-строка с результатом или краткая строка ошибки.
        """

        generated_code = normalize_workspace_path_arguments(
            _normalize_code_text(str(code or "")),
            self._sandbox,
        )
        try:
            _validate_code_policy(generated_code)
        except Exception as exc:
            return _policy_error_payload(
                generated_code,
                exc,
                sandbox=self._sandbox,
            )

        result = _execute_python_repl(
            sandbox=self._sandbox,
            code=generated_code,
            description=description,
        )
        return _result_to_json(result, sandbox=self._sandbox)

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


def _execute_python_repl(
    *,
    sandbox: DeepAgentPythonSandbox,
    code: str,
    description: str = "",
) -> PythonExecutionResult:
    """Выполняет Python-код в persistent sandbox.

    Args:
        sandbox: Sandbox с общими переменными и рабочими директориями.
        code: Python-код для проверки, компиляции и выполнения.
        description: Краткое описание цели кода для сообщения об успехе.

    Returns:
        ``PythonExecutionResult`` с результатом выполнения или подробной ошибкой.
    """

    generated_code = normalize_workspace_path_arguments(
        _normalize_code_text(str(code or "")),
        sandbox,
    )
    try:
        _validate_code_policy(generated_code)
        compiled = compile(generated_code, "<python>", "exec")
    except Exception as exc:
        return PythonExecutionResult(
            success=False,
            message=PYTHON_VALIDATION_FAILED_MESSAGE,
            generated_code=generated_code,
            error=f"{exc.__class__.__name__}: {exc}",
            traceback_text=_limit_text(traceback.format_exc(), max_chars=MAX_STDIO_CHARS),
            available_variables=_visible_variable_names(sandbox.globals),
            possible_causes=_python_error_possible_causes(exc),
            solution_options=_python_error_solution_options(exc),
            retry_guidance=_python_retry_guidance(),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    artifact_snapshot = _artifact_file_snapshot(sandbox.tool_outputs_dir)
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
            message=PYTHON_EXECUTION_FAILED_MESSAGE,
            generated_code=generated_code,
            execution_output=_combined_stdio(stdout, stderr),
            artifacts=_changed_artifacts(
                sandbox=sandbox,
                before=artifact_snapshot,
            ),
            error=f"{exc.__class__.__name__}: {exc}",
            traceback_text=_limit_text(traceback.format_exc(), max_chars=MAX_STDIO_CHARS),
            available_variables=_visible_variable_names(sandbox.globals),
            possible_causes=_python_error_possible_causes(exc),
            solution_options=_python_error_solution_options(exc),
            retry_guidance=_python_retry_guidance(),
        )

    execution_output = _combined_stdio(stdout, stderr)
    purpose = f" Цель: {description.strip()}" if description.strip() else ""
    return PythonExecutionResult(
        success=True,
        message=f"{PYTHON_EXECUTION_SUCCESS_MESSAGE}{purpose}",
        generated_code=generated_code,
        execution_output=execution_output,
        artifacts=_changed_artifacts(
            sandbox=sandbox,
            before=artifact_snapshot,
        ),
        available_variables=_visible_variable_names(sandbox.globals),
    )


def _artifact_file_snapshot(root: Path) -> dict[Path, tuple[int, int]]:
    """Снимает компактный снимок файлов в каталоге артефактов.

    Args:
        root: Каталог артефактов, внутри которого нужно отслеживать изменения.

    Returns:
        Словарь ``путь -> (размер, mtime_ns)`` для существующих файлов.
    """

    if not root.exists():
        return {}
    result: dict[Path, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        result[path.resolve()] = (stat.st_size, stat.st_mtime_ns)
    return result


def _changed_artifacts(
    *,
    sandbox: DeepAgentPythonSandbox,
    before: dict[Path, tuple[int, int]],
) -> list[dict[str, Any]]:
    """Возвращает файлы, созданные или изменённые в каталоге артефактов после выполнения кода.

    Args:
        sandbox: Sandbox с путями workspace и artifacts.
        before: Снимок файлов до выполнения кода.

    Returns:
        Список metadata с workspace-путём, типом файла и пустым описанием.
    """

    after = _artifact_file_snapshot(sandbox.tool_outputs_dir)
    artifacts: list[dict[str, Any]] = []
    for path, signature in sorted(after.items(), key=lambda item: item[0].as_posix()):
        if before.get(path) == signature:
            continue
        previous_signature = before.get(path)
        artifacts.append(
            {
                "path": _workspace_artifact_path(path, sandbox.working_directory),
                "absolute_path": str(path.resolve()),
                "type": _artifact_type(path),
                "change": "modified" if previous_signature is not None else "created",
                "size_bytes": signature[0],
                "previous_size_bytes": previous_signature[0] if previous_signature else None,
                "preview": artifact_preview(path),
            }
        )
    return artifacts


def _workspace_artifact_path(path: Path, workspace_root: Path) -> str:
    """Преобразует реальный путь артефакта в workspace-путь для ответа tool.

    Args:
        path: Реальный путь файла.
        workspace_root: Корень workspace.

    Returns:
        Путь вида ``/artifacts/file.ext`` или реальный путь, если файл вне workspace.
    """

    try:
        from deep_agent.agent_settings import workspace_tool_path

        return workspace_tool_path(path.resolve(), workspace_root.resolve())
    except ValueError:
        return str(path.resolve())


def _artifact_type(path: Path) -> str:
    """Определяет тип артефакта по расширению файла.

    Args:
        path: Путь файла.

    Returns:
        Короткий тип файла для JSON-ответа инструмента.
    """

    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"csv", "json", "pkl", "pickle", "md", "txt", "xlsx", "html", "png", "jpg", "jpeg"}:
        return "pickle" if suffix == "pkl" else suffix
    return "file"


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
    if isinstance(exc, FileNotFoundError):
        return [
            "Python-код обратился к несуществующему пути или передал workspace-путь вида `/file` как обычный OS-путь."
        ]
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
        "Исправь generated_code с учетом traceback и повтори python.",
        "Выведи важные результаты через print().",
        "Для результатов выгрузки данных и промежуточных преобразований создай файл обычным Python-кодом внутри Path(ARTIFACTS_DIR).",
    ]
    if isinstance(exc, SyntaxError):
        options.insert(0, "Исправь синтаксис Python-кода перед повторным запуском.")
    if isinstance(exc, NameError):
        options.insert(0, "Замени отсутствующую переменную на существующую из available_variables или создай ее явно.")
    if isinstance(exc, KeyError):
        options.insert(0, "Проверь реальные названия колонок через preview/schema перед обращением к ним.")
    if isinstance(exc, ImportError):
        options.insert(0, "Используй доступную библиотеку, установи зависимость другим tool или примени pandas/numpy helpers.")
    if isinstance(exc, FileNotFoundError):
        options.insert(
            0,
            "Если путь начинается с `/`, преобразуй его через `resolve_workspace_path(r\"/path\")` или собери путь через `Path(WORKSPACE_ROOT)`/`Path(ARTIFACTS_DIR)`.",
        )
    return options


def _python_retry_guidance() -> str:
    """Возвращает инструкцию по повторному вызову после ошибки.

    Returns:
        Текст с правилом исправления кода перед retry.
    """

    return (
        "Не повторяй тот же код без изменений. Используй generated_code, error, "
        "traceback и available_variables из этого ответа, исправь причину и повтори python."
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
    exc: Exception,
    *,
    sandbox: DeepAgentPythonSandbox,
) -> str:
    """Формирует компактный JSON-ответ при провале статической проверки кода.

    Args:
        generated_code: Нормализованный код, который не прошёл проверку.
        exc: Исключение валидации политики.
        sandbox: Sandbox для перечисления доступных переменных и путей.

    Returns:
        Краткая строка с причиной ошибки.
    """
    del generated_code, sandbox
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
        result: Результат ``_execute_python_repl`` (успех или ошибка выполнения).
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
    "PYTHON_TOOL_DESCRIPTION",
    "PYTHON_TOOL_NAME",
    "PythonTool",
]
