"""Локальный Deep Agents UI: установка зависимостей и запуск одной командой.

Содержит функции:
- _eprint: печать диагностики в stderr;
- _resolve_python: выбор интерпретатора Python;
- _resolve_argv: подготовка команды subprocess;
- _local_yarn: поиск локального Yarn;
- _yarn_argv: подготовка команды Yarn;
- _run: синхронный запуск команды;
- _popen: запуск фонового процесса;
- _parse_env_value: чтение значения из env-файла;
- _ensure_tool: проверка системной команды;
- _ensure_node_tooling: проверка Node.js;
- _python_dependencies_ready: проверка Python-зависимостей;
- _ensure_python_dependencies: установка Python-зависимостей;
- _apply_frontend_patch: применение frontend patch;
- _frontend_dependencies_ready: проверка frontend SDK;
- _ensure_frontend: подготовка frontend;
- _ensure_env_file: подготовка env-файла;
- _langgraph_command: выбор команды LangGraph CLI;
- _wait_for_port: ожидание TCP-порта;
- _write_frontend_env: запись конфигурации frontend;
- _stop_process: остановка процесса;
- _cleanup: остановка сервисов;
- _install_everything: установка зависимостей;
- _start_services: запуск backend и frontend;
- _parse_args: разбор аргументов CLI;
- main: точка входа.

Пример:
    python run_ui.py
    python run_ui.py --agent-port 2124 --ui-port 3100
    python run_ui.py --skip-install
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
from pathlib import Path

UI_COMMIT = "f6a4f34565b42688be06498031fc9351c152614e"
REQUIRED_FRONTEND_SDK_VERSION = "1.9.21"
ASSISTANT_ID = "analytics-agent"
REQUIRED_ENV_KEYS = ("OPENAI_API_KEY", "DEEP_AGENT_MODEL")

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_UI_ROOT = PROJECT_ROOT / "local_ui"
RUNTIME_ROOT = LOCAL_UI_ROOT / ".runtime"
FRONTEND_ROOT = RUNTIME_ROOT / "deep-agents-ui"
RUNTIME_LOGS = RUNTIME_ROOT / "logs"
PATCH_PATH = LOCAL_UI_ROOT / "deep-agents-ui.local.patch"
LANGGRAPH_CONFIG = LOCAL_UI_ROOT / "langgraph.json"
ENV_PATH = LOCAL_UI_ROOT / ".env"
ENV_EXAMPLE_PATH = LOCAL_UI_ROOT / ".env.example"
FRONTEND_ENV_PATH = FRONTEND_ROOT / ".env.local"

_backend_process: subprocess.Popen[bytes] | None = None
_frontend_process: subprocess.Popen[bytes] | None = None


def _eprint(message: str) -> None:
    """Печатает диагностическое сообщение в stderr.

    Args:
        message: Текст диагностического сообщения.

    Returns:
        ``None``.
    """

    print(message, file=sys.stderr)


def _resolve_python() -> Path:
    """Определяет интерпретатор Python для локального запуска.

    Returns:
        Путь к Python из ``.venv`` или к текущему интерпретатору.
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
    """Собирает argv для subprocess без ``shell=True``.

    Args:
        command: Команда и ее аргументы.

    Returns:
        Разрешенный argv; Windows-скрипты ``.cmd`` и ``.bat`` запускаются через cmd.

    Raises:
        RuntimeError: Исполняемый файл не найден.
    """
    if not command:
        return command

    program = command[0]
    if os.path.isabs(program) or (Path(program).exists() and Path(program).suffix):
        resolved = program
    else:
        resolved = shutil.which(program)
        if resolved is None:
            raise RuntimeError(f"Не найден `{program}` в PATH.")

    argv = [resolved, *command[1:]]
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", *argv]
    return argv


def _local_yarn() -> Path | None:
    """Ищет локальный исполняемый файл Yarn во frontend-зависимостях.

    Returns:
        Путь к Yarn или ``None``, если локальная установка отсутствует.
    """

    yarn_name = "yarn.cmd" if os.name == "nt" else "yarn"
    candidate = FRONTEND_ROOT / "node_modules" / ".bin" / yarn_name
    return candidate if candidate.exists() else None


def _yarn_argv(*args: str) -> list[str]:
    """Формирует argv для запуска Yarn.

    Args:
        *args: Аргументы команды Yarn.

    Returns:
        Список аргументов subprocess с локальным Yarn или fallback через npx.
    """

    local_yarn = _local_yarn()
    if local_yarn is not None:
        return [str(local_yarn), *args]
    return ["npx", "--yes", "yarn@1.22.22", *args]


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Выполняет синхронную неинтерактивную команду.

    Args:
        command: Команда и ее аргументы.
        cwd: Рабочая директория процесса.
        check: Нужно ли считать ненулевой код ошибкой.
        env: Переменные окружения дочернего процесса.

    Returns:
        Завершенный объект subprocess.

    Raises:
        RuntimeError: Команда завершилась с ошибкой при ``check=True``.
    """

    argv = _resolve_argv(command)
    result = subprocess.run(argv, cwd=cwd, env=env, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Команда завершилась с кодом {result.returncode}: {' '.join(command)}"
        )
    return result


def _popen(
    command: list[str],
    *,
    cwd: Path | None = None,
    **kwargs: object,
) -> subprocess.Popen[bytes]:
    """Запускает фоновый процесс без shell.

    Args:
        command: Команда и ее аргументы.
        cwd: Рабочая директория процесса.
        **kwargs: Дополнительные параметры ``subprocess.Popen``.

    Returns:
        Объект запущенного процесса.
    """

    argv = _resolve_argv(command)
    return subprocess.Popen(argv, cwd=cwd, **kwargs)  # type: ignore[arg-type]


def _parse_env_value(lines: list[str], key: str) -> str:
    """Читает значение переменной из строк env-файла.

    Args:
        lines: Строки env-файла.
        key: Имя переменной.

    Returns:
        Очищенное значение или пустую строку.
    """

    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _ensure_tool(name: str, install_hint: str) -> None:
    """Проверяет доступность системной команды.

    Args:
        name: Имя исполняемого файла.
        install_hint: Подсказка по установке.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Команда отсутствует в PATH.
    """

    if shutil.which(name) is None:
        raise RuntimeError(f"Не найден `{name}`. {install_hint}")


def _ensure_node_tooling() -> None:
    """Проверяет Node.js и способ запуска Yarn.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Не найден Node.js или npx.
    """

    _ensure_tool("node", "Установите Node.js 20+ и повторите запуск.")
    if _local_yarn() is None and shutil.which("npx") is None:
        raise RuntimeError(
            "Не найден `npx`. Установите Node.js 20+ (вместе с npm/npx) и повторите запуск."
        )


def _python_dependencies_ready(python: Path) -> bool:
    """Проверяет импорт обязательных Python-зависимостей UI.

    Args:
        python: Путь к интерпретатору Python.

    Returns:
        ``True``, если контрольные импорты выполняются успешно.
    """

    probe = subprocess.run(
        [str(python), "-c", "import langgraph_cli, langchain_openai"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return probe.returncode == 0


def _ensure_python_dependencies(python: Path) -> None:
    """Устанавливает Python-зависимости UI при их отсутствии.

    Args:
        python: Путь к интерпретатору Python.

    Returns:
        ``None``.
    """

    if _python_dependencies_ready(python):
        return
    print("Устанавливаю Python-зависимости...")
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-e",
            f"{PROJECT_ROOT}[models,data,analytics,ui]",
        ],
        cwd=PROJECT_ROOT,
    )


def _apply_frontend_patch() -> None:
    """Применяет локальный patch к зафиксированной версии frontend.

    Returns:
        ``None``.

    Raises:
        RuntimeError: Patch не применим и не был применен ранее.
    """

    check = subprocess.run(
        ["git", "-C", str(FRONTEND_ROOT), "apply", "--check", str(PATCH_PATH)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode == 0:
        _run(["git", "-C", str(FRONTEND_ROOT), "apply", str(PATCH_PATH)])
        return

    reverse_check = subprocess.run(
        [
            "git",
            "-C",
            str(FRONTEND_ROOT),
            "apply",
            "--reverse",
            "--check",
            str(PATCH_PATH),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if reverse_check.returncode != 0:
        raise RuntimeError(
            "Локальный patch несовместим с текущим состоянием deep-agents-ui."
        )


def _frontend_dependencies_ready() -> bool:
    """Проверяет установленную версию frontend SDK для sub-agent streaming.

    Returns:
        ``True``, если ``node_modules`` содержит требуемую версию
        ``@langchain/langgraph-sdk``; иначе ``False``.
    """

    sdk_package = (
        FRONTEND_ROOT
        / "node_modules"
        / "@langchain"
        / "langgraph-sdk"
        / "package.json"
    )
    if not sdk_package.exists():
        return False
    try:
        package_data = json.loads(sdk_package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return package_data.get("version") == REQUIRED_FRONTEND_SDK_VERSION


def _ensure_frontend() -> None:
    """Подготавливает checkout и зависимости frontend.

    Returns:
        ``None``.
    """

    _ensure_tool("git", "Установите Git и повторите запуск.")
    _ensure_node_tooling()

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    if not FRONTEND_ROOT.exists():
        print("Клонирую deep-agents-ui...")
        _run(
            [
                "git",
                "clone",
                "https://github.com/langchain-ai/deep-agents-ui.git",
                str(FRONTEND_ROOT),
            ]
        )
        _run(["git", "-C", str(FRONTEND_ROOT), "checkout", "--detach", UI_COMMIT])

    _apply_frontend_patch()

    if not _frontend_dependencies_ready():
        print("Устанавливаю npm-зависимости UI (первый запуск может занять несколько минут)...")
        _run(
            _yarn_argv("install"),
            cwd=FRONTEND_ROOT,
        )


def _ensure_env_file() -> list[str]:
    """Создает и проверяет локальный env-файл UI.

    Returns:
        Строки проверенного env-файла.

    Raises:
        RuntimeError: Шаблон отсутствует или обязательные значения не заполнены.
    """

    if not ENV_PATH.exists():
        if not ENV_EXAMPLE_PATH.exists():
            raise RuntimeError(f"Не найден шаблон {ENV_EXAMPLE_PATH}")
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
        print(f"Создан {ENV_PATH}. Заполните OPENAI_API_KEY и DEEP_AGENT_MODEL.")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    missing = [key for key in REQUIRED_ENV_KEYS if not _parse_env_value(lines, key)]
    if missing:
        raise RuntimeError(
            f"В {ENV_PATH} не заданы переменные: {', '.join(missing)}"
        )
    return lines


def _langgraph_command(python: Path) -> list[str]:
    """Определяет команду запуска LangGraph CLI.

    Args:
        python: Путь к интерпретатору Python.

    Returns:
        Аргументы команды LangGraph CLI.
    """

    if os.name == "nt":
        langgraph_exe = PROJECT_ROOT / ".venv" / "Scripts" / "langgraph.exe"
        if langgraph_exe.exists():
            return [str(langgraph_exe)]
    langgraph_bin = shutil.which("langgraph")
    if langgraph_bin:
        return [langgraph_bin]
    return [str(python), "-m", "langgraph_cli"]


def _wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
    """Ожидает открытия TCP-порта.

    Args:
        host: Хост проверяемого сервиса.
        port: TCP-порт сервиса.
        timeout_seconds: Максимальное время ожидания.

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


def _write_frontend_env(agent_port: int) -> None:
    """Записывает адрес Agent Server в env-файл frontend.

    Args:
        agent_port: Локальный порт Agent Server.

    Returns:
        ``None``.
    """

    deployment_url = f"http://127.0.0.1:{agent_port}"
    FRONTEND_ENV_PATH.write_text(
        "\n".join(
            [
                f"NEXT_PUBLIC_DEPLOYMENT_URL={deployment_url}",
                f"NEXT_PUBLIC_ASSISTANT_ID={ASSISTANT_ID}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    """Завершает фоновый процесс с ограниченным ожиданием.

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
    """Останавливает backend и frontend текущего запуска.

    Returns:
        ``None``.
    """

    global _backend_process, _frontend_process
    _stop_process(_frontend_process)
    _stop_process(_backend_process)
    _frontend_process = None
    _backend_process = None


def _install_everything(python: Path) -> None:
    """Подготавливает Python, frontend и env-файл.

    Args:
        python: Путь к интерпретатору Python.

    Returns:
        ``None``.
    """

    _ensure_python_dependencies(python)
    _ensure_frontend()
    _ensure_env_file()


def _start_services(python: Path, agent_port: int, ui_port: int) -> int:
    """Запускает Agent Server и frontend UI.

    Args:
        python: Путь к интерпретатору Python.
        agent_port: Порт Agent Server.
        ui_port: Порт frontend.

    Returns:
        Код завершения frontend-процесса.
    """

    global _backend_process, _frontend_process

    RUNTIME_LOGS.mkdir(parents=True, exist_ok=True)
    backend_out = RUNTIME_LOGS / "agent-server.out.log"
    backend_err = RUNTIME_LOGS / "agent-server.err.log"
    backend_out.unlink(missing_ok=True)
    backend_err.unlink(missing_ok=True)

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
                str(LANGGRAPH_CONFIG),
                "--host",
                "127.0.0.1",
                "--port",
                str(agent_port),
                "--no-browser",
                "--no-reload",
                "--allow-blocking",
            ],
            cwd=PROJECT_ROOT,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creationflags,
        )

    if not _wait_for_port("127.0.0.1", agent_port, timeout_seconds=30):
        tail = backend_err.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(
            f"Agent Server не открыл порт {agent_port} за 30 секунд. "
            f"Лог: {backend_err}\n{tail}"
        )

    _write_frontend_env(agent_port)
    deployment_url = f"http://127.0.0.1:{agent_port}"
    ui_url = f"http://127.0.0.1:{ui_port}"

    print(f"Agent Server: {deployment_url}")
    print(f"Assistant ID: {ASSISTANT_ID}")
    print(f"UI: {ui_url}")
    print("Остановка обоих процессов: Ctrl+C")

    _frontend_process = _popen(
        _yarn_argv(
            "dev",
            "--port",
            str(ui_port),
            "--hostname",
            "127.0.0.1",
        ),
        cwd=FRONTEND_ROOT,
    )
    return _frontend_process.wait()


def _parse_args() -> argparse.Namespace:
    """Разбирает аргументы командной строки UI.

    Returns:
        Пространство имен с параметрами запуска.
    """

    parser = argparse.ArgumentParser(
        description="Установить (при необходимости) и запустить локальный Deep Agents UI."
    )
    parser.add_argument("--agent-port", type=int, default=2024)
    parser.add_argument("--ui-port", type=int, default=3000)
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Не проверять pip/yarn/git-зависимости перед запуском.",
    )
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="Только установить зависимости, без запуска серверов.",
    )
    return parser.parse_args()


def main() -> int:
    """Подготавливает окружение и запускает локальный UI.

    Returns:
        Код завершения процесса.
    """

    args = _parse_args()
    python = _resolve_python()

    if os.name == "nt":
        signal.signal(signal.SIGBREAK, lambda *_: (_cleanup(), sys.exit(130)))
    signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(143)))
    atexit.register(_cleanup)

    try:
        if args.skip_install:
            if not FRONTEND_ROOT.exists():
                raise RuntimeError(
                    "Frontend не установлен. Запустите без --skip-install."
                )
            _ensure_env_file()
        else:
            _install_everything(python)

        if args.install_only:
            print("Установка завершена.")
            print(f"Запуск: {python.name} run_ui.py")
            return 0

        return _start_services(python, args.agent_port, args.ui_port)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as error:
        _eprint(f"Ошибка: {error}")
        return 1
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
