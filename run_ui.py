"""Локальный Deep Agents UI: установка зависимостей и запуск одной командой.

Пример:
    python run_ui.py
    python run_ui.py --agent-port 2124 --ui-port 3100
    python run_ui.py --skip-install
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

UI_COMMIT = "f6a4f34565b42688be06498031fc9351c152614e"
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
    print(message, file=sys.stderr)


def _resolve_python() -> Path:
    venv_python = (
        PROJECT_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    )
    if venv_python.with_suffix(".exe").exists():
        return venv_python.with_suffix(".exe")
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def _resolve_argv(command: list[str]) -> list[str]:
    """Собирает argv для subprocess без shell=True (Windows .cmd/.bat через cmd.exe)."""
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
    yarn_name = "yarn.cmd" if os.name == "nt" else "yarn"
    candidate = FRONTEND_ROOT / "node_modules" / ".bin" / yarn_name
    return candidate if candidate.exists() else None


def _yarn_argv(*args: str) -> list[str]:
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
    argv = _resolve_argv(command)
    return subprocess.Popen(argv, cwd=cwd, **kwargs)  # type: ignore[arg-type]


def _parse_env_value(lines: list[str], key: str) -> str:
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(prefix):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _ensure_tool(name: str, install_hint: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Не найден `{name}`. {install_hint}")


def _ensure_node_tooling() -> None:
    _ensure_tool("node", "Установите Node.js 20+ и повторите запуск.")
    if _local_yarn() is None and shutil.which("npx") is None:
        raise RuntimeError(
            "Не найден `npx`. Установите Node.js 20+ (вместе с npm/npx) и повторите запуск."
        )


def _python_dependencies_ready(python: Path) -> bool:
    probe = subprocess.run(
        [str(python), "-c", "import langgraph_cli, langchain_openai"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return probe.returncode == 0


def _ensure_python_dependencies(python: Path) -> None:
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


def _ensure_frontend() -> None:
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

    if not (FRONTEND_ROOT / "node_modules").exists():
        print("Устанавливаю npm-зависимости UI (первый запуск может занять несколько минут)...")
        _run(
            _yarn_argv("install", "--frozen-lockfile"),
            cwd=FRONTEND_ROOT,
        )


def _ensure_env_file() -> list[str]:
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
    if os.name == "nt":
        langgraph_exe = PROJECT_ROOT / ".venv" / "Scripts" / "langgraph.exe"
        if langgraph_exe.exists():
            return [str(langgraph_exe)]
    langgraph_bin = shutil.which("langgraph")
    if langgraph_bin:
        return [langgraph_bin]
    return [str(python), "-m", "langgraph_cli"]


def _wait_for_port(host: str, port: int, timeout_seconds: float) -> bool:
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
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _cleanup() -> None:
    global _backend_process, _frontend_process
    _stop_process(_frontend_process)
    _stop_process(_backend_process)
    _frontend_process = None
    _backend_process = None


def _install_everything(python: Path) -> None:
    _ensure_python_dependencies(python)
    _ensure_frontend()
    _ensure_env_file()


def _start_services(python: Path, agent_port: int, ui_port: int) -> int:
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
