"""Офлайн-launcher локального Deep Agents UI.

Скрипт проверяет подготовленное окружение и запускает LangGraph Agent Server вместе
с уже распакованным frontend. Он не устанавливает и не скачивает зависимости.

Содержит функции:
- _eprint: печать сообщения в stderr;
- _resolve_python: выбор Python-интерпретатора;
- _resolve_argv: разрешение исполняемого файла команды;
- _popen: безопасный запуск дочернего процесса;
- _parse_env_value: очистка значения из env-файла;
- _read_env_file: чтение env-файла;
- _validate_env: проверка обязательных переменных;
- _child_env: сборка окружения дочерних процессов;
- _ensure_tool: проверка системного инструмента;
- _python_dependencies_ready: проверка LangGraph CLI;
- _validate_python_runtime: проверка Python-окружения;
- _validate_frontend: проверка frontend и SDK;
- _langgraph_command: построение команды LangGraph CLI;
- _frontend_dev_command: построение команды frontend;
- _wait_for_port: ожидание готовности TCP-порта;
- _write_frontend_env: запись runtime-настроек frontend;
- _stop_process: остановка дочернего процесса;
- _cleanup: остановка backend и frontend;
- _make_log_paths: создание путей логов;
- _start_services: запуск backend и frontend;
- _parse_args: разбор аргументов командной строки;
- main: основная точка входа.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ASSISTANT_ID = "analytics-agent"
COMMON_REQUIRED_ENV_KEYS = ("DEEP_AGENT_MODEL",)
PROVIDER_REQUIRED_ENV_KEYS = {
    "openai": ("OPENAI_API_KEY",),
    "kitai": (
        "KITAI_HOST_SDK",
        "KITAI_CERT_FILE_PATH",
        "KITAI_CERT_KEY_FILE_PATH",
    ),
}
REQUIRED_FRONTEND_SDK_VERSION = "1.9.21"

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_UI_ROOT = PROJECT_ROOT / "local_ui"
RUNTIME_ROOT = LOCAL_UI_ROOT / ".runtime"
DEFAULT_FRONTEND_ROOT = RUNTIME_ROOT / "deep-agents-ui"
RUNTIME_LOGS = RUNTIME_ROOT / "logs"
DEFAULT_LANGGRAPH_CONFIG = LOCAL_UI_ROOT / "langgraph.json"
DEFAULT_ENV_PATH = LOCAL_UI_ROOT / ".env"

_backend_process: subprocess.Popen[bytes] | None = None
_frontend_process: subprocess.Popen[bytes] | None = None


def _eprint(message: str) -> None:
    """Печатает сообщение в стандартный поток ошибок.

    Args:
        message: Текст диагностического сообщения.

    Returns:
        ``None``.
    """

    print(message, file=sys.stderr)


def _resolve_python() -> Path:
    """Выбирает Python из ``.venv`` или текущий интерпретатор.

    Returns:
        Путь к доступному Python-интерпретатору.
    """

    venv_python = (
        PROJECT_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    )
    if venv_python.with_suffix(".exe").exists():
        return venv_python.with_suffix(".exe")
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def _resolve_argv(command: list[str]) -> list[str]:
    """Разрешает путь исполняемого файла без ``shell=True``.

    Args:
        command: Команда и её аргументы.

    Returns:
        Команда с абсолютным путём к исполняемому файлу.

    Raises:
        RuntimeError: Исполняемый файл не найден.
    """

    if not command:
        return command

    program = command[0]
    program_path = Path(program)
    if os.path.isabs(program) or (program_path.exists() and program_path.suffix):
        resolved = program
    else:
        found = shutil.which(program)
        if found is None:
            raise RuntimeError(f"Не найден исполняемый файл `{program}` в PATH.")
        resolved = found

    argv = [resolved, *command[1:]]
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", *argv]
    return argv


def _popen(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    **kwargs: object,
) -> subprocess.Popen[bytes]:
    """Запускает дочерний процесс без ``shell=True``.

    Args:
        command: Команда и её аргументы.
        cwd: Рабочая директория процесса.
        env: Переменные окружения процесса.
        **kwargs: Дополнительные аргументы ``subprocess.Popen``.

    Returns:
        Запущенный объект ``subprocess.Popen``.
    """

    argv = _resolve_argv(command)
    return subprocess.Popen(argv, cwd=cwd, env=env, **kwargs)  # type: ignore[arg-type]


def _parse_env_value(value: str) -> str:
    """Удаляет пробелы и внешние кавычки из значения env-файла.

    Args:
        value: Сырое значение после знака ``=``.

    Returns:
        Очищенная строка.
    """

    return value.strip().strip('"').strip("'")


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Читает простой env-файл формата ``KEY=VALUE``.

    Args:
        env_path: Путь к env-файлу.

    Returns:
        Словарь переменных из файла.

    Raises:
        RuntimeError: Env-файл отсутствует.
    """

    if not env_path.exists():
        raise RuntimeError(
            f"Не найден env-файл: {env_path}\n"
            "Создайте local_ui/.env и заполните настройки запуска."
        )

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _parse_env_value(value)
    return values


def _validate_env(env_path: Path) -> dict[str, str]:
    """Проверяет обязательные настройки выбранного модельного провайдера.

    Args:
        env_path: Путь к env-файлу.

    Returns:
        Словарь прочитанных переменных.

    Raises:
        RuntimeError: Провайдер неизвестен или обязательные переменные отсутствуют.
    """

    values = _read_env_file(env_path)
    provider = values.get("DEEP_AGENT_MODEL_PROVIDER", "openai").strip().lower()
    provider_keys = PROVIDER_REQUIRED_ENV_KEYS.get(provider)
    if provider_keys is None:
        supported = ", ".join(sorted(PROVIDER_REQUIRED_ENV_KEYS))
        raise RuntimeError(
            f"Неподдерживаемый DEEP_AGENT_MODEL_PROVIDER={provider!r}. "
            f"Доступные значения: {supported}."
        )
    required_keys = (*COMMON_REQUIRED_ENV_KEYS, *provider_keys)
    missing = [key for key in required_keys if not values.get(key)]
    if missing:
        raise RuntimeError(
            f"В {env_path} не заданы обязательные переменные: {', '.join(missing)}"
        )
    return values


def _child_env(env_values: dict[str, str]) -> dict[str, str]:
    """Собирает окружение backend и frontend без установки зависимостей.

    Args:
        env_values: Переменные из env-файла.

    Returns:
        Копия системного окружения с настройками проекта и ``PYTHONPATH``.
    """

    env = os.environ.copy()
    env.update(env_values)

    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not current_pythonpath
        else str(PROJECT_ROOT) + os.pathsep + current_pythonpath
    )
    return env


def _ensure_tool(name: str, install_hint: str) -> None:
    """Проверяет наличие исполняемого файла в ``PATH``.

    Args:
        name: Имя системного инструмента.
        install_hint: Подсказка по подготовке окружения.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Инструмент не найден.
    """

    if shutil.which(name) is None:
        raise RuntimeError(f"Не найден `{name}`. {install_hint}")


def _python_dependencies_ready(python: Path) -> bool:
    """Проверяет импорт LangGraph CLI без установки зависимостей.

    Args:
        python: Путь к Python-интерпретатору.

    Returns:
        ``True``, если ``langgraph_cli`` импортируется успешно.
    """

    probe = subprocess.run(
        [str(python), "-c", "import langgraph_cli"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def _validate_python_runtime(python: Path) -> None:
    """Проверяет готовность Python-окружения к запуску LangGraph CLI.

    Args:
        python: Путь к Python-интерпретатору.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Runtime-зависимости не установлены.
    """

    if _python_dependencies_ready(python):
        return
    raise RuntimeError(
        "Python-зависимости для запуска LangGraph CLI не установлены.\n"
        "Установите их отдельной командой в вашей закрытой среде, затем повторите запуск.\n"
        "Пример: python -m pip install -e .[models,data,analytics,ui]"
    )


def _validate_frontend(frontend_root: Path, *, strict_sdk: bool) -> None:
    """Проверяет структуру frontend, зависимости и версию SDK.

    Args:
        frontend_root: Корень подготовленного frontend.
        strict_sdk: Считать несовпадение версии SDK ошибкой.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Frontend не готов к запуску.
    """

    if not frontend_root.exists():
        raise RuntimeError(
            f"Не найдена директория frontend: {frontend_root}\n"
            "Распакуйте архив deep-agents-ui заранее в эту папку или передайте путь через --frontend-dir."
        )

    package_json = frontend_root / "package.json"
    if not package_json.exists():
        raise RuntimeError(f"В frontend-директории нет package.json: {package_json}")

    node_modules = frontend_root / "node_modules"
    if not node_modules.exists():
        raise RuntimeError(
            f"Не найдены frontend-зависимости: {node_modules}\n"
            "Выполните yarn install / npm ci отдельной командой до запуска run_ui.py."
        )

    sdk_package = node_modules / "@langchain" / "langgraph-sdk" / "package.json"
    if not sdk_package.exists():
        message = (
            f"Не найден @langchain/langgraph-sdk в {node_modules}. "
            "Переустановите frontend-зависимости отдельной командой."
        )
        if strict_sdk:
            raise RuntimeError(message)
        _eprint(f"Предупреждение: {message}")
        return

    try:
        sdk_data = json.loads(sdk_package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        if strict_sdk:
            raise RuntimeError(f"Не удалось прочитать {sdk_package}")
        _eprint(f"Предупреждение: не удалось прочитать {sdk_package}")
        return

    sdk_version = str(sdk_data.get("version", ""))
    if sdk_version != REQUIRED_FRONTEND_SDK_VERSION:
        message = (
            f"Версия @langchain/langgraph-sdk: {sdk_version or 'unknown'}, "
            f"ожидалась {REQUIRED_FRONTEND_SDK_VERSION}."
        )
        if strict_sdk:
            raise RuntimeError(message)
        _eprint(f"Предупреждение: {message}")


def _langgraph_command(python: Path) -> list[str]:
    """Строит команду запуска LangGraph CLI.

    Args:
        python: Путь к Python-интерпретатору.

    Returns:
        Команда с найденным CLI или fallback через Python-модуль.
    """

    if os.name == "nt":
        langgraph_exe = PROJECT_ROOT / ".venv" / "Scripts" / "langgraph.exe"
        if langgraph_exe.exists():
            return [str(langgraph_exe)]

    langgraph_bin = shutil.which("langgraph")
    if langgraph_bin:
        return [langgraph_bin]

    return [str(python), "-m", "langgraph_cli"]


def _frontend_dev_command(
    frontend_root: Path,
    *,
    ui_host: str,
    ui_port: int,
    package_manager: str,
) -> list[str]:
    """Строит команду frontend без скачивающих fallback-механизмов.

    Args:
        frontend_root: Корень frontend.
        ui_host: Хост UI.
        ui_port: Порт UI.
        package_manager: Выбранный package manager или ``auto``.

    Returns:
        Команда запуска frontend dev server.
    """

    frontend_args = ["--port", str(ui_port), "--hostname", ui_host]

    yarn_name = "yarn.cmd" if os.name == "nt" else "yarn"
    local_yarn = frontend_root / "node_modules" / ".bin" / yarn_name

    if package_manager == "yarn" or (
        package_manager == "auto"
        and (local_yarn.exists() or (frontend_root / "yarn.lock").exists())
    ):
        if local_yarn.exists():
            return [str(local_yarn), "dev", *frontend_args]
        _ensure_tool("yarn", "Установите Yarn заранее или используйте --package-manager npm/pnpm.")
        return ["yarn", "dev", *frontend_args]

    if package_manager == "pnpm" or (
        package_manager == "auto" and (frontend_root / "pnpm-lock.yaml").exists()
    ):
        _ensure_tool("pnpm", "Установите pnpm заранее или используйте --package-manager npm/yarn.")
        return ["pnpm", "dev", "--", *frontend_args]

    _ensure_tool("npm", "Установите npm заранее или используйте --package-manager yarn/pnpm.")
    return ["npm", "run", "dev", "--", *frontend_args]


def _wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    """Ожидает открытия TCP-порта в пределах таймаута.

    Args:
        host: Хост проверяемого сервиса.
        port: TCP-порт сервиса.
        timeout_seconds: Максимальное время ожидания в секундах.

    Returns:
        ``True`` при успешном подключении, иначе ``False``.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.5)
    return False


def _write_frontend_env(frontend_root: Path, *, agent_host: str, agent_port: int, assistant_id: str) -> None:
    """Записывает runtime-конфигурацию подключения UI к Agent Server.

    Args:
        frontend_root: Корень frontend.
        agent_host: Хост Agent Server.
        agent_port: Порт Agent Server.
        assistant_id: Идентификатор LangGraph assistant.

    Returns:
        ``None``.
    """

    deployment_url = f"http://{agent_host}:{agent_port}"
    frontend_env_path = frontend_root / ".env.local"
    frontend_env_path.write_text(
        "\n".join(
            [
                f"NEXT_PUBLIC_DEPLOYMENT_URL={deployment_url}",
                f"NEXT_PUBLIC_ASSISTANT_ID={assistant_id}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    """Останавливает дочерний процесс с принудительным fallback.

    Args:
        process: Процесс для остановки или ``None``.

    Returns:
        ``None``.
    """

    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _cleanup() -> None:
    """Останавливает frontend и backend и очищает ссылки на процессы.

    Returns:
        ``None``.
    """

    global _backend_process, _frontend_process
    _stop_process(_frontend_process)
    _stop_process(_backend_process)
    _frontend_process = None
    _backend_process = None


def _make_log_paths() -> tuple[Path, Path]:
    """Создаёт уникальные пути stdout/stderr логов backend.

    Returns:
        Пара путей для stdout и stderr.
    """

    RUNTIME_LOGS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"{stamp}-{os.getpid()}"
    return (
        RUNTIME_LOGS / f"agent-server-{suffix}.out.log",
        RUNTIME_LOGS / f"agent-server-{suffix}.err.log",
    )


def _start_services(args: argparse.Namespace, python: Path, env_values: dict[str, str]) -> int:
    """Запускает Agent Server и frontend после локальных проверок.

    Args:
        args: Аргументы командной строки.
        python: Путь к Python-интерпретатору.
        env_values: Проверенные переменные из env-файла.

    Returns:
        Код завершения frontend-процесса.

    Raises:
        RuntimeError: Backend не запустился или конфигурация отсутствует.
    """

    global _backend_process, _frontend_process

    frontend_root = args.frontend_dir.resolve()
    langgraph_config = args.langgraph_config.resolve()
    if not langgraph_config.exists():
        raise RuntimeError(f"Не найден LangGraph config: {langgraph_config}")

    child_env = _child_env(env_values)
    backend_out, backend_err = _make_log_paths()
    langgraph = _langgraph_command(python)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with backend_out.open("w", encoding="utf-8") as stdout_file, backend_err.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        _backend_process = _popen(
            [
                *langgraph,
                "dev",
                "--config",
                str(langgraph_config),
                "--host",
                args.agent_host,
                "--port",
                str(args.agent_port),
                "--no-browser",
                "--no-reload",
                "--allow-blocking",
            ],
            cwd=PROJECT_ROOT,
            env=child_env,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creationflags,
        )

    if not _wait_for_port(args.agent_host, args.agent_port, args.backend_timeout):
        tail = backend_err.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(
            f"Agent Server не открыл порт {args.agent_port} за {args.backend_timeout} секунд.\n"
            f"stdout: {backend_out}\n"
            f"stderr: {backend_err}\n"
            f"Последние строки stderr:\n{tail}"
        )

    _write_frontend_env(
        frontend_root,
        agent_host=args.agent_host,
        agent_port=args.agent_port,
        assistant_id=args.assistant_id,
    )

    deployment_url = f"http://{args.agent_host}:{args.agent_port}"
    ui_url = f"http://{args.ui_host}:{args.ui_port}"

    print(f"Agent Server: {deployment_url}")
    print(f"Assistant ID: {args.assistant_id}")
    print(f"UI: {ui_url}")
    print(f"Backend stdout: {backend_out}")
    print(f"Backend stderr: {backend_err}")
    print("Остановка обоих процессов: Ctrl+C")

    frontend_command = _frontend_dev_command(
        frontend_root,
        ui_host=args.ui_host,
        ui_port=args.ui_port,
        package_manager=args.package_manager,
    )
    _frontend_process = _popen(
        frontend_command,
        cwd=frontend_root,
        env=child_env,
    )
    return _frontend_process.wait()


def _parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки launcher-а.

    Returns:
        Пространство имён с параметрами backend и frontend.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Запустить локальный Deep Agents UI без установки, скачивания, "
            "клонирования, patch/update и npx fallback."
        )
    )
    parser.add_argument("--agent-host", default="127.0.0.1")
    parser.add_argument("--agent-port", type=int, default=2024)
    parser.add_argument("--ui-host", default="127.0.0.1")
    parser.add_argument("--ui-port", type=int, default=3000)
    parser.add_argument("--assistant-id", default=ASSISTANT_ID)
    parser.add_argument("--frontend-dir", type=Path, default=DEFAULT_FRONTEND_ROOT)
    parser.add_argument("--langgraph-config", type=Path, default=DEFAULT_LANGGRAPH_CONFIG)
    parser.add_argument("--backend-timeout", type=float, default=30.0)
    parser.add_argument(
        "--package-manager",
        choices=("auto", "npm", "yarn", "pnpm"),
        default="auto",
        help="Чем запускать frontend dev script. Режим auto ничего не скачивает.",
    )
    parser.add_argument(
        "--strict-frontend-sdk",
        action="store_true",
        help=(
            "Считать ошибкой версию @langchain/langgraph-sdk, отличную от "
            f"{REQUIRED_FRONTEND_SDK_VERSION}. По умолчанию это только предупреждение."
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Проверяет окружение, запускает сервисы и обрабатывает ошибки launcher-а.

    Returns:
        ``0`` или код frontend при штатном завершении, ``1`` при ошибке, ``130`` при прерывании.
    """

    args = _parse_args()
    python = _resolve_python()

    if os.name == "nt":
        signal.signal(signal.SIGBREAK, lambda *_: (_cleanup(), sys.exit(130)))
    signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(143)))
    atexit.register(_cleanup)

    try:
        _validate_python_runtime(python)
        env_values = _validate_env(DEFAULT_ENV_PATH.resolve())
        _validate_frontend(args.frontend_dir.resolve(), strict_sdk=args.strict_frontend_sdk)
        return _start_services(args, python, env_values)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as error:
        _eprint(f"Ошибка: {error}")
        return 1
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
