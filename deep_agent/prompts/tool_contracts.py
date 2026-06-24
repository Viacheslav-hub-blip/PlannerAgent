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

Do not use when:
- the next action is one small direct tool call;
- the current agent already has enough verified evidence to answer;
- delegation would only restate known context.

Bad example:
```text
task(subagent_type="<subagent-name>", description="Fix paths")
```

Good example:
```text
task(
  subagent_type="<subagent-name>",
  description="
Objective: fix incorrect workspace path handling.
Scope: /deep_agent/runtime/python_sandbox.py and tests.
Constraints: no broad rewrite, preserve existing API except documented python tool contract.
Expected report: changed files, commands run, test results, limitations.
Stopping condition: focused tests pass or blocker with evidence.
"
)
```
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
- Use canonical POSIX workspace paths such as `/` or `/deep_agent/agent.py`; do not pass Windows paths.

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
- Use canonical POSIX workspace paths such as `/report.md`; do not pass Windows paths.

Output:
- the requested text fragment and metadata about the range that was read.
- content may be displayed with line numbers or service notices; those prefixes are not part of the file content.

Call format:
- pass the path through `file_path`;
- if the file was not read completely, request the next fragment with a new `offset`.

Example:
```text
read_file(file_path="/deep_agent/prompts/supervisor.py", offset=1, limit=120)
```

Use when:
- source code, configuration, documentation, or another text artifact is needed.

Limitations:
- the tool is not intended for binary files;
- when reusing text in `edit_file`, strip display-only line numbers, tabs, and pagination notices from the fragment.
""".strip(),
    "write_file": """
write_file
---
Description:
Writes a text file.

Input:
- the target file path;
- the complete new text content for the file.
- Use canonical POSIX workspace paths such as `/report.md`; do not pass Windows paths.

Output:
- the write result plus a verification notice, or an error message if the file cannot be read back after writing.

Use when:
- the result should be saved as a text file;
- the complete content of an existing text file should be intentionally replaced.
- the task names an exact output file and the final deliverable must be written to that exact file.

Example:
```text
write_file(file_path="/summary.md", content="<complete markdown report>")
```

Limitations:
- the tool works with text files;
- the tool overwrites an existing file at the same path; do not create duplicate filenames with suffixes like
  `_final`, `_final_final`, or `_new` after a successful write;
- do not write a helper script instead of the requested output file; scripts are only intermediate tools;
- do not leave requested output files empty or filled with placeholders unless the user explicitly asked for that;
- `/` is the configured user workspace root;
- `/artifacts` is reserved for data exports, offloaded table results, and intermediate transformation outputs; do not
  save every user-facing file there by default;
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
- `file_path`: the target file path;
- `old_string`: the exact text fragment to replace;
- `new_string`: the replacement text fragment;
- `replace_all`: whether to replace every occurrence instead of one unique occurrence.
- Use canonical POSIX workspace paths such as `/deep_agent/prompts/supervisor.py`; do not pass Windows paths.

Output:
- the replacement result plus a verification notice, or an error message if the file cannot be read back after editing.

Use when:
- an existing text file needs a local change.

Example:
```text
edit_file(
  file_path="/deep_agent/prompts/coding.py",
  old_string="exact existing fragment without line-number prefixes",
  new_string="replacement fragment"
)
```

Limitations:
- the fragment to replace must be found unambiguously in the file;
- strip display-only line-number prefixes copied from `read_file` before filling `old_string` or `new_string`;
- if the tool reports that the string was not found, change the fragment using verified file content instead of
  repeating the same failed edit;
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
- Use canonical POSIX workspace paths such as `/` or `/deep_agent/`; do not pass Windows paths.

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
- Use canonical POSIX workspace paths such as `/` or `/deep_agent/`; do not pass Windows paths.

Output:
- matching content, files with matches, or match counts depending on `output_mode`.

Call format:
- pass the search text through `pattern`;
- `path` points to a directory;
- a single file name can be passed through `glob`.
- pass one search phrase per call; if several alternatives are needed, make separate calls or use a Python scan.

Use when:
- a symbol, call, configuration key, text, or artifact mention should be found.

Limitations:
- `pattern` is treated as plain text unless the tool implementation declares another search mode;
- if repeated searches return no useful matches, change `path`/`glob` from verified context or switch strategy instead
  of retrying equivalent searches.
""".strip(),
    "execute": """
execute
---
Description:
Runs a non-interactive shell command in the tool working directory.

Input:
- the command to run;
- when supported by the runtime: timeout, working directory, and additional execution parameters.
- Workspace-absolute paths returned by filesystem tools, such as `/VLM PRES.ipynb`, are mapped to real shell paths.
  Quote paths that contain spaces.

Output:
- the command exit code, stdout, and stderr.

Use when:
- tests, a linter, formatter, type checker, build, generator, or diagnostic command should be run;
- command output is needed as a verifiable observation.
- filesystem operations such as copy, move, remove, or directory creation are needed.

Do not use when:
- you only need to read or edit a text file;
- `python` is better for a data calculation over an existing artifact;
- the command requires API keys, secrets, interactive input, or long-running services.

Example:
```text
execute(command="python -m pytest tests/test_filesystem_path_contract.py -q")
execute(command="jupyter nbconvert --to script \"/VLM PRES.ipynb\" --output \"/VLM_PRES.py\"")
```

Bad example:
```text
execute(command="type deep_agent\\agent.py")
```

Good example:
```text
read_file(file_path="/deep_agent/agent.py", offset=1, limit=120)
```

Limitations:
- the command must not require interactive input;
- the tool must not be used for commands that require secrets or API keys.
- use filesystem tools for ordinary text read/write/edit operations; use shell for tests, builds, diagnostics,
  package commands, and copy/move operations;
- do not embed multi-line content inside a double-quoted shell string;
- avoid complex `python -c` one-liners with loops, branches, functions, classes, or context managers after semicolons;
  for data/intermediate transformations write a small script under `/artifacts`, otherwise use an appropriate
  repository/workspace path or a single-quoted heredoc.
""".strip(),
}
