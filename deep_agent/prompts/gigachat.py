"""Дополнительные prompt-практики для стабильной работы GigaChat.

Содержит:
- GIGACHAT_CORE_PRACTICES_PROMPT: общие правила выполнения задач без лишнего исследования.
- GIGACHAT_FILESYSTEM_PRACTICES_PROMPT: правила работы с filesystem tools в namespace workspace.
- GIGACHAT_SHELL_PRACTICES_PROMPT: правила безопасного использования shell ``execute``.
- GIGACHAT_PYTHON_PRACTICES_PROMPT: рецепты для Python, CSV, JSON и файловых расчетов.
- GIGACHAT_FORMAT_PRACTICES_PROMPT: правила точного формата результата.
- GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT: правила следования фактическому контракту tools.
- GIGACHAT_AGENT_PRACTICES_PROMPT: объединенный prompt-довесок для supervisor и subagents.
- build_gigachat_practices_prompt: сборка prompt-довеска с явным приоритетом проектных правил.
"""

from __future__ import annotations

GIGACHAT_CORE_PRACTICES_PROMPT = """
## GigaChat Execution Practices

These practices reduce tool-calling loops and formatting mistakes. They supplement the project, skill, role, and user
instructions above; they do not override them.

- Read the request literally and complete the requested deliverable without unrelated extras.
- Process every line, file, row, or item named by the task, not only the first matching item.
- Prefer direct completion over exploration for straightforward tasks.
- If a tool returns the same result or the same error twice in a row, change the approach instead of trying it again.
- If a script fails twice, rewrite the script from a simpler structure or switch to another verified method.
- If the task names exact output files, create those exact files with the requested content, not a helper script that
  would create them later.
- Do not leave requested output files empty or filled with placeholders unless the task explicitly asks for that.
- When writing JSON arrays or objects in Python, use ``json.dump(..., ensure_ascii=False, indent=2)`` and validate with
  ``json.load`` or ``json.loads``.
""".strip()

GIGACHAT_FILESYSTEM_PRACTICES_PROMPT = """
## Filesystem Tool Practices

- Filesystem tools use the canonical POSIX workspace namespace. The workspace root is ``/``.
- Use paths returned by tools or workspace paths such as ``/README.md``, ``/deep_agent/agent.py``, and
  ``/artifacts/report.md``. Do not use Windows paths or host absolute paths in filesystem tools.
- For each source file change, read the relevant fragment once, then make the smallest coherent ``edit_file`` change.
- ``read_file`` output can include display-only line numbers or pagination notices. Do not copy line-number prefixes
  into ``old_string``, ``new_string``, or new file content.
- Prefer ``edit_file`` for small changes to existing text files and ``write_file`` for new files or intentional full
  replacements.
- If ``edit_file`` says that the string was not found, inspect whether the copied fragment contains display-only line
  prefixes, wrong indentation, truncated context, or stale file content before retrying.
- For ``grep``, pass one search phrase per call and always scope the search with ``path`` and, when useful, ``glob``.
  If repeated ``grep`` calls return no useful matches, switch to a different search method or a small Python scan.
""".strip()

GIGACHAT_SHELL_PRACTICES_PROMPT = """
## Shell Tool Practices

- Use ``execute`` for tests, linters, builds, package commands, file moves/copies, and concise diagnostics.
- Do not use shell commands to read or edit ordinary text when filesystem tools are clearer.
- ``execute`` runs in the workspace shell. Use short non-interactive commands and quote paths with spaces.
- Workspace paths such as ``/artifacts/run.py`` are mapped by the backend when they point inside the workspace. Do not
  use host absolute paths outside the workspace or Windows paths.
- Never embed multi-line content in a double-quoted shell string. Use filesystem tools, a checked-in script, or a
  single-quoted heredoc when multi-line shell input is truly needed.
- If a shell command fails with the same error twice, stop retrying the same command shape and change the approach.
""".strip()

GIGACHAT_PYTHON_PRACTICES_PROMPT = """
## Python Practices

- For logic that needs loops, mutation, branching, functions, classes, file parsing, or multiple output writes, prefer a
  small script file over a complex ``python -c`` one-liner.
- ``python -c`` one-liners are acceptable only for simple expressions and generator expressions. A statement such as
  ``for``, ``if``, ``def``, ``class``, or ``with`` after a semicolon is a common ``SyntaxError`` source.
- For ad hoc helper scripts, write them under ``/artifacts`` unless the task explicitly requires a repository file.
  Example: write ``/artifacts/run.py`` and run ``execute(command="python /artifacts/run.py")``.
- Before writing parsing or aggregation code for CSV, JSONL, XML, logs, or spreadsheets, inspect a small sample and use
  the exact field names and value formats observed there.
- For multi-file processing, process all files in one script or one vectorized operation instead of one manual tool call
  per file.
- After generating a required artifact, verify that it exists and is non-empty. For JSON, verify that it parses.
""".strip()

GIGACHAT_FORMAT_PRACTICES_PROMPT = """
## Output Format Practices

- Follow the requested output format literally. Preserve required headers, separators, column order, file names,
  integer versus decimal representation, and path style.
- If the task asks for a Markdown table, use a real Markdown table with pipe separators.
- If the task asks for CSV or TSV, use the requested delimiter and include or omit the header exactly as requested.
- When reporting workspace files to the user, prefer canonical workspace paths such as ``/artifacts/result.csv`` or
  repository paths such as ``/deep_agent/prompts/supervisor.py``.
- If the result depends on a saved artifact, verify the artifact before reporting success.
""".strip()

GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT = """
## Runtime Tool Contract Practices

- Use only tools that are actually available in the current agent run.
- Treat tool descriptions, project prompts, loaded skills, and runtime context as the source of truth for tool
  arguments.
- Do not invent unavailable tool names, CLI flags, subcommands, fields, or files.
- If a tool reports an invalid argument, unknown command, or unsupported choice, re-read the available contract and
  switch to a valid operation.
""".strip()

GIGACHAT_AGENT_PRACTICES_PROMPT = "\n\n".join(
    [
        GIGACHAT_CORE_PRACTICES_PROMPT,
        GIGACHAT_FILESYSTEM_PRACTICES_PROMPT,
        GIGACHAT_SHELL_PRACTICES_PROMPT,
        GIGACHAT_PYTHON_PRACTICES_PROMPT,
        GIGACHAT_FORMAT_PRACTICES_PROMPT,
        GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT,
    ]
)


def build_gigachat_practices_prompt() -> str:
    """Возвращает prompt-довесок с практиками GigaChat.

    Returns:
        Строка с дополнительными правилами выполнения задач. Правила явно объявлены как
        низкоприоритетное дополнение к пользовательским, проектным и skill-инструкциям.
    """

    return GIGACHAT_AGENT_PRACTICES_PROMPT


__all__ = [
    "GIGACHAT_AGENT_PRACTICES_PROMPT",
    "GIGACHAT_CORE_PRACTICES_PROMPT",
    "GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT",
    "GIGACHAT_FILESYSTEM_PRACTICES_PROMPT",
    "GIGACHAT_FORMAT_PRACTICES_PROMPT",
    "GIGACHAT_PYTHON_PRACTICES_PROMPT",
    "GIGACHAT_SHELL_PRACTICES_PROMPT",
    "build_gigachat_practices_prompt",
]
