"""Низкоуровневое выполнение команд, файловых операций и трассировки агента.

Содержит:
- filesystem_backend: backend файловой системы и локального shell.
- python_sandbox: persistent Python sandbox для инструмента ``python``.
- trace_logger: callback-трассировка запросов к модели.
- harness_profile: профиль DeepAgents harness.
"""
