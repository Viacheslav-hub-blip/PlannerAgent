"""Офлайн-launcher локального Deep Agents UI.

Скрипт проверяет подготовленное окружение и запускает LangGraph Agent Server вместе
с уже распакованным frontend. Он не устанавливает и не скачивает зависимости.

Содержит функции:
- _eprint: печать сообщения в stderr;
- _resolve_python: выбор Python-интерпретатора;
- _resolve_argv: разрешение исполняемого файла команды;
- _popen: безопасный запуск дочернего процесса;
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
from typing import TextIO

ASSISTANT_ID = "analytics-agent"
REQUIRED_FRONTEND_SDK_VERSION = "1.9.21"

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_UI_ROOT = PROJECT_ROOT / "local_ui"
RUNTIME_ROOT = LOCAL_UI_ROOT / ".runtime"
DEFAULT_FRONTEND_ROOT = RUNTIME_ROOT / "deep-agents-ui"
RUNTIME_LOGS = RUNTIME_ROOT / "logs"
DEFAULT_LANGGRAPH_CONFIG = LOCAL_UI_ROOT / "langgraph.json"

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


def _child_env() -> dict[str, str]:
    """Собирает окружение backend и frontend без установки зависимостей.

    Returns:
        Копия системного окружения с добавленным ``PYTHONPATH`` проекта.
    """

    env = os.environ.copy()

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
        "Пример: python -m pip install -e .[kitai,data,analytics,ui]"
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

    proxy_host = "127.0.0.1" if agent_host == "0.0.0.0" else agent_host
    deployment_url = "/api/langgraph"
    proxy_url = f"http://{proxy_host}:{agent_port}"
    frontend_env_path = frontend_root / ".env.local"
    frontend_env_path.write_text(
        "\n".join(
            [
                f"NEXT_PUBLIC_DEPLOYMENT_URL={deployment_url}",
                f"NEXT_PUBLIC_ASSISTANT_ID={assistant_id}",
                f"LANGGRAPH_PROXY_URL={proxy_url}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_startup_diagnostics(
    log_file: TextIO,
    *,
    args: argparse.Namespace,
    python: Path,
    frontend_root: Path,
    langgraph_config: Path,
    langgraph_command: list[str],
    child_env: dict[str, str],
) -> None:
    """Пишет краткую диагностику запуска backend в общий stdout-лог.

    Args:
        log_file: Открытый файл общего backend-лога.
        args: Аргументы запуска UI и Agent Server.
        python: Python-интерпретатор, выбранный launcher-ом.
        frontend_root: Директория frontend.
        langgraph_config: Путь к ``langgraph.json``.
        langgraph_command: Команда запуска LangGraph CLI.
        child_env: Окружение дочернего backend-процесса.

    Returns:
        ``None``.
    """

    sdk_package = frontend_root / "node_modules" / "@langchain" / "langgraph-sdk" / "package.json"
    sdk_version = "not-found"
    if sdk_package.exists():
        try:
            sdk_version = str(json.loads(sdk_package.read_text(encoding="utf-8")).get("version", "unknown"))
        except (OSError, json.JSONDecodeError):
            sdk_version = "read-error"

    proxy_host = "127.0.0.1" if args.agent_host == "0.0.0.0" else args.agent_host
    deployment_url = "/api/langgraph"
    proxy_url = f"http://{proxy_host}:{args.agent_port}"
    print("===== DEEPAGENT UI STARTUP DIAGNOSTICS =====", file=log_file)
    print(f"python={python}", file=log_file)
    print(f"project_root={PROJECT_ROOT}", file=log_file)
    print(f"frontend_root={frontend_root}", file=log_file)
    print(f"langgraph_config={langgraph_config} exists={langgraph_config.exists()}", file=log_file)
    print(f"langgraph_command={' '.join(langgraph_command)}", file=log_file)
    print(f"frontend_deployment_url={deployment_url}", file=log_file)
    print(f"langgraph_proxy_url={proxy_url}", file=log_file)
    print(f"assistant_id={args.assistant_id}", file=log_file)
    print(f"frontend_sdk_version={sdk_version}", file=log_file)
    print(f"PYTHONPATH={child_env.get('PYTHONPATH', '')}", file=log_file)
    print("python_packages:", file=log_file)
    print(_collect_python_package_report(python, child_env), file=log_file)
    print("============================================", file=log_file, flush=True)


def _collect_python_package_report(python: Path, child_env: dict[str, str]) -> str:
    """Собирает версии и пути ключевых Python-пакетов выбранным интерпретатором.

    Args:
        python: Python-интерпретатор backend.
        child_env: Окружение backend-процесса.

    Returns:
        Многострочный отчёт для startup-лога.
    """

    script = r'''
import importlib.metadata
import importlib.util
import sys

print(f"  executable={sys.executable}")
print(f"  version={sys.version.replace(chr(10), ' ')}")
packages = {
    "deepagents": "deepagents",
    "langchain": "langchain",
    "langchain_core": "langchain-core",
    "langgraph": "langgraph",
    "langgraph_cli": "langgraph-cli",
    "pydantic": "pydantic",
    "openai": "openai",
    "sber_kitai_sdk_langchain": "sber-kitai-sdk-langchain",
    "sber_kitai_sdk_py": "sber-kitai-sdk-py",
}
for module_name, package_name in packages.items():
    try:
        version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        version = "not-installed"
    try:
        spec = importlib.util.find_spec(module_name)
        origin = spec.origin if spec is not None else "not-found"
    except Exception as error:
        origin = f"ERROR={type(error).__name__}: {error}"
    print(f"  {module_name} version={version} file={origin}")
'''
    try:
        result = subprocess.run(
            [str(python), "-c", script],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as error:
        return f"  package-report-failed={type(error).__name__}: {error}"

    output = result.stdout.strip()
    if result.stderr.strip():
        output = f"{output}\n  stderr={result.stderr.strip()}" if output else f"  stderr={result.stderr.strip()}"
    return output or f"  package-report-empty returncode={result.returncode}"


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
    stdout_log_path = RUNTIME_LOGS / f"agent-server-{suffix}.out.log"
    stderr_log_path = RUNTIME_LOGS / f"agent-server-{suffix}.err.log"
    return stdout_log_path, stderr_log_path


def _start_services(args: argparse.Namespace, python: Path) -> int:
    """Запускает Agent Server и frontend после локальных проверок.

    Args:
        args: Аргументы командной строки.
        python: Путь к Python-интерпретатору.
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

    child_env = _child_env()
    backend_out, backend_err = _make_log_paths()
    langgraph = _langgraph_command(python)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    with (
        backend_out.open("w", encoding="utf-8") as stdout_file,
        backend_err.open("w", encoding="utf-8") as stderr_file,
    ):
        _write_startup_diagnostics(
            stdout_file,
            args=args,
            python=python,
            frontend_root=frontend_root,
            langgraph_config=langgraph_config,
            langgraph_command=langgraph,
            child_env=child_env,
        )
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

    backend_probe_host = "127.0.0.1" if args.agent_host == "0.0.0.0" else args.agent_host
    if not _wait_for_port(backend_probe_host, args.agent_port, args.backend_timeout):
        tail = backend_out.read_text(encoding="utf-8", errors="replace")[-4000:]
        err_tail = backend_err.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(
            f"Agent Server не открыл порт {args.agent_port} за {args.backend_timeout} секунд.\n"
            f"backend stdout log: {backend_out}\n"
            f"backend stderr log: {backend_err}\n"
            f"Последние строки backend stdout log:\n{tail}\n"
            f"Последние строки backend stderr log:\n{err_tail}"
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
    print(f"Backend stdout log: {backend_out}")
    print(f"Backend stderr log: {backend_err}")
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
        _validate_frontend(args.frontend_dir.resolve(), strict_sdk=args.strict_frontend_sdk)
        return _start_services(args, python)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as error:
        _eprint(f"Ошибка: {error}")
        return 1
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
