"""Описания и контракт использования инструментов DeepAgent.

Содержит текстовые описания встроенных LangChain tools и таблицу переопределений.
"""

from __future__ import annotations

BUILTIN_TOOLS_PROMPT_APPEND = """
<tool_contract_overrides>
## Tool Contract Notes

This block clarifies how to use the available tools in this agent environment.

- Do not copy demonstration `<commentary>` or `<example>` fragments from tool descriptions into answers, plans,
  subagent tasks, or tool arguments.
- Treat context as a limited working budget. Load the smallest useful context for the next decision, not every
  possibly related artifact.
- Avoid duplicate tool calls with the same goal and the same inputs.
- Parallel tool calls are useful only when the tasks are independent.
- Use one `task(data-retrieval-agent)` call for one coherent data retrieval objective. If a result has already been
  returned for that objective, do not delegate the same request again.
- Use `write_todos` only when the task has multiple meaningful steps. After writing a plan, continue with the next
  concrete action instead of restating the plan.
- Inside `data-retrieval-agent`, use `load_data` for table reads.
- Use `execute_python_code` for Python processing of saved `.pkl` artifacts. Do not call generic `execute` for Python
  snippets.
- When using `execute_python_code` with `target_variable`, the Python code must assign a variable with exactly that
  name. Otherwise omit `target_variable` and rely on printed output or persisted artifacts.
- Do not present computed counts or summaries after a failed tool call. Fix the failed call or state that the result is
  incomplete.
- Treat an empty `task` result as a failed delegation. Do not infer rows, counts, calculations, or artifact paths from
  the task description. Retry only the missing part or report that no evidence was returned.
- Never finish with an empty assistant message. If the task cannot continue, return a concise failure statement with
  the failed condition, available evidence, and the next required correction.
- When reporting tool checks or validation results, compress success to one line and include detailed output only for
  failures: command or tool call, failing condition, expected/observed values, and relevant rows or error fragments.
</tool_contract_overrides>
""".strip()

SUPERVISOR_TOOLS_PROMPT_APPEND = BUILTIN_TOOLS_PROMPT_APPEND + """

<supervisor_tool_scope>
The supervisor always has `write_todos`, `task`, `execute_python_code`, and `load_skills`.
When the `code-workspace` skill is loaded, it additionally receives `ls`, `read_file`, `write_file`, `edit_file`,
`glob`, `grep`, and `execute`.

- Never call `load_data` directly; delegate table reads to `data-retrieval-agent`.
- Do not call workspace tools unless they are present in the current tool list.
- Use workspace tools directly for focused code work. Delegate to `general-purpose` only for a bounded independent
  coding objective that would otherwise expand the supervisor context.
- `load_skills` loads only `SKILL.md` files. Do not use it for `fields.md`, `joins.md`, or other auxiliary files.
</supervisor_tool_scope>
""".strip()

DATA_RETRIEVAL_TOOLS_PROMPT_APPEND = """
<data_retrieval_tool_scope>
The data-retrieval agent has only these tools: `load_data`, `load_skills`, `execute_python_code`, `ls`, `read_file`,
`glob`, and `grep`.

- Do not call or mention `task`, `write_todos`, `write_file`, `edit_file`, or generic `execute`.
- Use `load_skills` only for an exact skill name or path known from verified context. Do not reload skills already
  present in Preloaded Skills.
- For `grep`, use `pattern` for searched text. `path` may be a directory or a known file path; use `glob` only to
  restrict files when searching a directory.
- For `read_file`, use `file_path`; continue with the next `offset` when the result is paginated.
</data_retrieval_tool_scope>
""".strip()

WRITE_TODOS_TOOL_DESCRIPTION = """
write_todos
---
Description:
Maintains the working plan for the current agent run.

Use when:
- the task requires several tool or subagent steps;
- the order of data reads, calculations, and checks should be explicit;
- a previous tool result changes the plan.

How to use:
- call it at most once per model turn;
- make each item a concrete action with a tool/subagent, source, artifact, expected result, and validation when
  applicable;
- mark an item as completed only after a real tool result supports it;
- keep only genuinely parallel and independent items in progress at the same time.

Do not use:
- for a simple one-step answer;
- as the final answer to the user;
- to recreate the same plan without new facts.
""".strip()

TASK_TOOL_DESCRIPTION = """
task
---
Description:
Runs a short-lived subagent for one isolated objective and returns one final report to the supervisor.

Available subagents:
{available_agents}

Parameters:
- `subagent_type`: exact subagent name from the list above.
- `description`: business objective, known inputs, relevant loaded skills, period, expected report format, and an
  explicit stopping condition.
  Если точный `event_id` используется для первичного lookup, явно укажи, что период пока
  неизвестен и должен быть получен из найденной строки.

Use when:
- table data must be read through `data-retrieval-agent`;
- a bounded code investigation or implementation can be delegated to `general-purpose` after `code-workspace`
  has been loaded;
- the objective can be completed in one isolated subagent run;
- a compact structured report is better than expanding the supervisor context.

Useful shortcut:
- If the loaded table skill already identifies the source and the user requests an aggregation or chart over table
  data, delegate the table read/calculation to `data-retrieval-agent`. Do not spend supervisor turns rediscovering a
  field description unless the user specifically asks for the field meaning or the field is ambiguous.
- Treat user phrases such as "age category" as likely `snake_case` field candidates (`age_category`) when that field
  is named in loaded context or can be validated by the data tool. Let the subagent validate the column through
  `load_data` instead of blocking the supervisor on auxiliary file search.

Constraints:
- pass a bounded data retrieval, search, or validation objective, not broad reasoning ownership;
- use `data-retrieval-agent` for tables and `general-purpose` for code; never ask one subagent to impersonate the
  other;
- keep final judgment in the supervisor unless the task explicitly asks the subagent for a final verdict;
- do not write SQL-like queries, `WHERE` clauses, keyword lists, or example filters in the task description unless
  the user explicitly provided them as mandatory criteria;
- when a loaded workflow skill defines an algorithm, tell the subagent to follow that workflow skill instead of
  rewriting the algorithm yourself;
- reference workflow skills by name/path, but do not copy their numbered steps into the task description unless the
  user explicitly asks to see the plan;
- do not run duplicate `task` calls with the same description;
- do not use parallel `task` calls for the same sample or same retrieval goal;
- after a successful report, do not delegate the same question again;
- require the subagent to return compact evidence: sources, tool calls made, result summary, limitations, and missing
  data. Do not ask it to return long logs or full raw tables;
- for calculations or charts, define the stopping condition as successful data retrieval, completed calculation, and
  a verified artifact path when an artifact was requested;
- an empty report, a report without factual tool evidence, or a claimed artifact without a confirmed path is not a
  successful result and must not be used for the final answer;
- examples from the default tool description are not instructions for the current task.
""".strip()

TOOL_DESCRIPTION_OVERRIDES = {
    "write_todos": WRITE_TODOS_TOOL_DESCRIPTION,
    "task": TASK_TOOL_DESCRIPTION,
    "ls": """
ls
---
Description:
Lists one workspace or virtual-backend directory.

Parameters:
- `path`: absolute virtual path starting with `/`.

Use when:
- you need a quick view of a known directory in the workspace, `/skills/`, or `/tool_outputs/`;
- you need to confirm that a directory exists before reading a file.

Do not use:
- for recursive discovery when `glob` can express the target;
- for searching text inside files;
- do not use it for tabular data that should be processed through pickle-aware tools;
- use `read_file` for a known text file.

Good: list `/src` before selecting a module.
Bad: repeatedly list every nested directory instead of one `glob` call.
""".strip(),
    "read_file": """
read_file
---
Description:
Reads a text file from the workspace or a routed virtual directory.

Parameters:
- `file_path`: absolute virtual path to the file;
- `offset`: first line to read when paging is needed;
- `limit`: maximum number of lines to read.

Correct call example:
`{"file_path": "/skills/hit-table/fields.md", "offset": 0, "limit": 100}`

Use when:
- you need to understand source code, configuration, `AGENTS.md`, or a referenced skill file;
- you need a small text artifact;
- you need to page through a large text file.

Do not use:
- for binary files or full `.pkl` processing;
- to reread unchanged content already present in the current context;
- use `file_path`, never `path`, for the file argument;
- a response limited to the first N lines is not proof that the file ends there;
- when the requested field is not in the returned page, continue with the next `offset` until the file ends, or use
  `grep` first and then read the relevant range;
- do not conclude that a field is absent from `fields.md` after reading only its first page;
- use `execute_python_code` and saved artifacts for `.pkl` processing;
- use virtual absolute paths such as `/src/app.py`; do not pass host Windows paths.

Good: read the exact module before editing it.
Bad: edit a source file based only on its name or a grep snippet.
""".strip(),
    "write_file": """
write_file
---
Description:
Creates a new text file or replaces a file when a complete rewrite is explicitly justified.

Use when:
- the requested file does not exist and must be created;
- generated content is naturally written as a complete new file;
- the user approved the pending write action.

Do not use:
- for a small change to an existing file; use `edit_file`;
- to rewrite a large existing source file when a targeted edit is possible;
- for temporary command output that can stay in stdout;
- outside the active workspace.

Good: create a new focused test module after reading neighbouring tests.
Bad: replace an existing implementation to change one function.

Policy:
- inspect surrounding project conventions first;
- preserve UTF-8 text and existing user changes;
- the call is subject to human approval.
""".strip(),
    "edit_file": """
edit_file
---
Description:
Applies an exact text replacement to an existing workspace file.

Use when:
- the file has already been read;
- the requested change is local and the old text can be matched exactly;
- preserving unrelated content is required.

Do not use:
- before reading the current file;
- when the match is ambiguous or appears multiple times unintentionally;
- for generated files that should be recreated by their generator;
- outside the active workspace.

Good: replace one validated function body and keep neighbouring code unchanged.
Bad: apply a guessed replacement without confirming the current text.

Policy:
- prefer the smallest coherent edit;
- preserve user changes and file style;
- the call is subject to human approval.
""".strip(),
    "glob": """
glob
---
Description:
Finds files by glob pattern in the virtual filesystem.

Parameters:
- `pattern`: glob pattern, for example `**/*.md`;
- `path`: base directory, `/` by default.

Use when:
- you need recursive discovery by name, extension, or directory pattern.

Do not use:
- when the exact path is already known;
- use `grep` for text search inside files;
- do not use it instead of reading tables.

Good: find `**/test_*.py` once.
Bad: use broad `**/*` when a narrower pattern is known.
""".strip(),
    "grep": """
grep
---
Description:
Searches for text in workspace or virtual-backend files.

Parameters:
- `pattern`: literal text to search for;
- `path`: search directory, not a file path;
- `glob`: file filter;
- `output_mode`: `files_with_matches`, `content`, or `count`.

Correct call example:
`{"pattern": "age_category", "path": "/skills/hit-table", "glob": "*.md", "output_mode": "content"}`

Single-file search example:
`{"pattern": "age_category", "path": "/skills/hit-table", "glob": "fields.md", "output_mode": "content"}`

Use when:
- you need to locate a symbol, configuration key, field, table, skill, or artifact mention.

Do not use:
- as proof of full behavior without reading the relevant surrounding code;
- with a broad root when a narrower directory is known;
- use `pattern`, never `query`, for the searched text;
- do not pass `/skills/.../fields.md` in `path`; use `path` as the parent directory and `glob` as the file name;
- `pattern` is ordinary text, not a regular expression;
- for a known field name, search it with `grep` before paging through a long `fields.md`;
- use `load_data` or `execute_python_code` for tabular analytics.

Good: locate a class name, then read the matching module.
Bad: infer implementation correctness from one matching line.
""".strip(),
    "execute": """
execute
---
Description:
Runs a non-interactive terminal command with the active workspace as its working directory.

Use when:
- running tests, linters, formatters, build commands, package inspection, or version-control diagnostics;
- a standard project command provides stronger verification than manual inspection;
- shell output is required to diagnose a failure.

Do not use:
- to edit source files through shell redirection, Python, PowerShell, Git, or another process; use `write_file` or
  `edit_file` so file changes pass through approval;
- for tabular analytics that belong in `execute_python_code`;
- for interactive commands, credential prompts, or commands that require API keys;
- to access paths outside the active workspace.

Good: `python -m unittest tests.test_module` after a focused edit.
Good: `git diff --check` to validate changed text.
Bad: `python -c "Path('app.py').write_text(...)"`.
Bad: commands that delete or overwrite project content unless the user explicitly requested that operation.

Policy:
- prefer deterministic, non-interactive commands;
- set a bounded timeout for long operations;
- report the relevant error fragment instead of dumping noisy logs;
- terminal commands are not approval-gated, so never use them to bypass file-edit approval.
""".strip(),
}
