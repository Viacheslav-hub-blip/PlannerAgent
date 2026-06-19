"""Описания публичных контрактов инструментов DeepAgent.

Содержит:
- WRITE_TODOS_TOOL_DESCRIPTION: описание инструмента ведения списка задач.
- TASK_TOOL_DESCRIPTION: описание инструмента запуска subagent.
- TOOL_DESCRIPTION_OVERRIDES: таблица переопределений описаний встроенных tools.
"""

from __future__ import annotations

WRITE_TODOS_TOOL_DESCRIPTION = """
write_todos
---
Description:
Keeps the current task checklist up to date.

Input:
- a list of tasks with a short title, status, and optional expected result.

Output:
- the updated plan available to the agent during later execution steps.

Use when:
- the task should be split into several verifiable steps;
- the status of already planned steps has changed.
""".strip()

TASK_TOOL_DESCRIPTION = """
task
---
Description:
Runs one subagent and returns its final report.

Available subagents:
{available_agents}

Input:
- `subagent_type`: the subagent name from the list of available subagents.
- `description`: the subagent task with inputs, constraints, expected result, and stopping condition.

Output:
- a text report from the subagent covering completed work, facts found, artifacts created, checks, and limitations.

Use when:
- an isolated task should be executed in a separate context;
- the subagent result should be returned as a compact report.
""".strip()

TOOL_DESCRIPTION_OVERRIDES = {
    "write_todos": WRITE_TODOS_TOOL_DESCRIPTION,
    "task": TASK_TOOL_DESCRIPTION,
    "ls": """
ls
---
Description:
Lists the contents of one directory.

Input:
- `path`: an absolute directory path in the tools file namespace.

Output:
- a list of files and subdirectories, or an error message for inaccessible or missing paths.

Use when:
- the contents of a known directory should be inspected;
- a directory existence check is needed.
""".strip(),
    "read_file": """
read_file
---
Description:
Reads a text file.

Input:
- `file_path`: an absolute file path in the tools file namespace.
- `offset`: the first line to read when paginating.
- `limit`: the maximum number of lines to read.

Output:
- the requested text fragment and metadata about the range that was read.

Call format:
- pass the path through `file_path`;
- if the file was not read completely, request the next fragment with a new `offset`.

Use when:
- source code, configuration, documentation, or another text artifact is needed.

Limitations:
- the tool is not intended for binary files.
""".strip(),
    "write_file": """
write_file
---
Description:
Creates a text file or fully replaces the contents of an existing file.

Input:
- the target file path;
- the complete new text content for the file.

Output:
- the write result or an error message.

Use when:
- the result should be saved as a new file;
- an existing file should be replaced as a whole.

Limitations:
- the tool works with text files;
- `/` is the configured user workspace root and is the default place for user artifacts;
- `/deep_agent/` is the agent implementation directory, not an output folder;
- do not write under `/deep_agent/` unless the task explicitly changes agent code, prompts, tests, or skills;
- partial changes to an existing file are usually handled through `edit_file`.
""".strip(),
    "edit_file": """
edit_file
---
Description:
Edits an existing text file by replacing an exact text fragment.

Input:
- the target file path;
- the original text fragment;
- the replacement text fragment.

Output:
- the replacement result or an error message.

Use when:
- an existing text file needs a local change.

Limitations:
- the fragment to replace must be found unambiguously in the file;
- `/deep_agent/` is the agent implementation directory and should be edited only for explicit agent code, prompt,
  test, or skill changes;
- the tool is not intended for binary files or generated files that should be updated by a generator.
""".strip(),
    "glob": """
glob
---
Description:
Finds files by a glob pattern.

Input:
- `pattern`: a glob pattern, for example `**/*.md`;
- `path`: the base search directory.

Output:
- a list of paths matching the pattern.

Use when:
- files should be found by name, extension, or directory structure.
""".strip(),
    "grep": """
grep
---
Description:
Searches for text in files.

Input:
- `pattern`: the text to search for;
- `path`: the search directory;
- `glob`: the file filter;
- `output_mode`: the output mode, such as `files_with_matches`, `content`, or `count`.

Output:
- matching content, files with matches, or match counts depending on `output_mode`.

Call format:
- pass the search text through `pattern`;
- `path` points to a directory;
- a single file name can be passed through `glob`.

Use when:
- a symbol, call, configuration key, text, or artifact mention should be found.

Limitations:
- `pattern` is treated as plain text unless the tool implementation declares another search mode.
""".strip(),
    "execute": """
execute
---
Description:
Runs a non-interactive shell command in the tool working directory.

Input:
- the command to run;
- when supported by the runtime: timeout, working directory, and additional execution parameters.

Output:
- the command exit code, stdout, and stderr.

Use when:
- tests, a linter, formatter, type checker, build, generator, or diagnostic command should be run;
- command output is needed as a verifiable observation.

Limitations:
- the command must not require interactive input;
- the tool must not be used for commands that require secrets or API keys.
""".strip(),
}
