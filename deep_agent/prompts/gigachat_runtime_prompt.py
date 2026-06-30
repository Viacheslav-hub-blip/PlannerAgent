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
- build_runtime_context_prompt: сборка runtime prompt с датой запуска и путями.
"""

from __future__ import annotations

GIGACHAT_CORE_PRACTICES_PROMPT = """
## Практики выполнения задач в GigaChat

Эти правила уменьшают циклы вызовов tools и ошибки формата. Они дополняют проектные, skill, role и пользовательские
инструкции выше; они не переопределяют их.

- Читай запрос буквально и выполняй нужный результат без несвязанных дополнений.
- Обрабатывай каждую строку, файл, строку таблицы или элемент, названный в задаче, а не только первое совпадение.
- Для простых задач предпочитай прямое выполнение лишнему исследованию.
- Если задача состоит из двух действий вроде переименовать, переместить, конвертировать, заменить или удалить,
  выполни обе части до ответа.
- Если tool два раза подряд возвращает тот же результат или ту же ошибку, измени подход.
- Если скрипт дважды падает, перепиши его проще или перейди к другому проверенному способу.
- Если задача называет точные выходные файлы, создай именно эти файлы с нужным содержимым, а не вспомогательный
  скрипт, который создал бы их позже.
- Не оставляй запрошенные файлы пустыми или с placeholders, если пользователь явно не попросил это.
- При записи JSON-массивов или объектов в Python используй ``json.dump(..., ensure_ascii=False, indent=2)`` и
  проверяй результат через ``json.load`` или ``json.loads``.
""".strip()

GIGACHAT_FILESYSTEM_PRACTICES_PROMPT = """
## Практики filesystem tools

- Filesystem tools используют канонический POSIX namespace workspace. Корень workspace — ``/``.
- Используй пути, которые вернули tools, или workspace-пути вроде ``/README.md``, ``/deep_agent/agent.py`` и
  ``/artifacts/load_data_result.pkl``. Не используй Windows-пути или абсолютные пути хоста в filesystem tools.
- Для кода агента и skills ориентируйся на Agent implementation directory и Skills directory из runtime context;
  не предполагай, что они всегда находятся в ``/deep_agent``.
- Если просят структуру файлов, сообщай только пути, увиденные через ``get_project_structure``, ``ls``, ``glob`` или
  другие успешные tools. Не выдумывай типовые директории вроде ``/work``, ``/home``, ``/logs`` и примеры из памяти модели.
- Перед изменением исходного файла прочитай релевантный контекст и сохрани несвязанный текст.
- Считай descriptions tools авторитетным контрактом для аргументов чтения, записи, редактирования и поиска файлов.
""".strip()

GIGACHAT_SHELL_PRACTICES_PROMPT = """
## Практики shell tool

- Используй ``execute`` для тестов, linters, сборок, package-команд, перемещения/копирования файлов и короткой диагностики.
- Не используй shell-команды для чтения или редактирования обычного текста, когда filesystem tools понятнее.
- ``execute`` работает в shell workspace. Используй короткие неинтерактивные команды и заключай пути с пробелами в кавычки.
- Workspace-пути вроде ``/artifacts/run.py`` отображаются backend, когда указывают внутрь workspace. Не используй
  абсолютные пути хоста вне workspace или Windows-пути.
- Не вставляй многострочный текст в shell-строку в двойных кавычках. Используй filesystem tools, файл-скрипт в
  репозитории или heredoc в одинарных кавычках, если многострочный shell input действительно нужен.
- Если shell-команда дважды падает с одной ошибкой, перестань повторять ту же форму команды и измени подход.
""".strip()

GIGACHAT_PYTHON_PRACTICES_PROMPT = """
## Практики Python

- Для логики с циклами, изменением состояния, ветвлениями, функциями, классами, парсингом файлов или несколькими
  выходными записями предпочитай небольшой script file сложному ``python -c`` one-liner.
- ``python -c`` one-liners допустимы только для простых выражений и generator expressions. Конструкции ``for``, ``if``,
  ``def``, ``class`` или ``with`` после точки с запятой часто приводят к ``SyntaxError``.
- Для обработки данных и промежуточных transformation scripts записывай их в ``/artifacts``, если задача явно не
  требует файл репозитория.
  Пример: запиши ``/artifacts/run.py`` и выполни ``execute(command="python /artifacts/run.py")``.
- Перед кодом парсинга или агрегации CSV, JSONL, XML, logs или spreadsheets посмотри небольшой sample и используй
  фактические имена полей и форматы значений.
- Для обработки нескольких файлов обрабатывай все файлы одним скриптом или одной векторной операцией, а не отдельным
  ручным tool call на каждый файл.
- После генерации нужного artifact проверь, что он существует и не пустой. Для JSON проверь, что он парсится.
""".strip()

GIGACHAT_FORMAT_PRACTICES_PROMPT = """
## Практики формата результата

- Соблюдай запрошенный формат буквально. Сохраняй нужные заголовки, разделители, порядок колонок, имена файлов,
  целочисленное или десятичное представление и стиль путей.
- Если задача просит Markdown-таблицу, используй настоящую Markdown-таблицу с разделителями pipe.
- Если задача просит CSV или TSV, используй нужный разделитель и добавляй или не добавляй header точно по запросу.
- Когда сообщаешь пользователю о workspace-файлах, используй их фактические канонические workspace-пути, например
  ``/artifacts/result.csv`` для data artifacts или ``/deep_agent/prompts/supervisor.py`` для файлов репозитория.
- Если результат зависит от сохраненного artifact, проверь artifact перед сообщением об успехе.
- Перед финальным ответом проверь, что точные выходные файлы существуют, JSON парсится если он был запрошен,
  старые пути/символы исчезли после rename/remove/replace, а сохраненные пути совпадают с фактическими workspace-путями.
""".strip()

GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT = """
## Практики runtime-контрактов tools

- Используй только tools, которые реально доступны в текущем запуске агента.
- Считай descriptions tools, проектные prompts, загруженные skills и runtime context источником истины для аргументов tools.
- Не выдумывай недоступные имена tools, CLI flags, subcommands, поля или файлы.
- Если tool сообщает о неверном аргументе, неизвестной команде или неподдерживаемом варианте, перечитай доступный
  контракт и перейди к валидной операции.
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


def build_runtime_context_prompt(
    *,
    current_date: str,
    workspace_tool_root_path: str,
    workspace_real_path: str,
    data_artifacts_tool_path: str,
    data_artifacts_real_path: str,
    agent_root_line: str = "",
    skills_root_line: str = "",
    memory_path_line: str = "",
) -> str:
    """Собирает runtime prompt с датой запуска и фактическими путями.

    Args:
        current_date: Текущая дата запуска в ISO-формате.
        workspace_tool_root_path: Корень workspace в namespace tools.
        workspace_real_path: Реальный путь корня workspace.
        data_artifacts_tool_path: Путь artifacts в namespace tools.
        data_artifacts_real_path: Реальный путь artifacts.
        agent_root_line: Опциональная строка о директории реализации агента.
        skills_root_line: Опциональная строка о директории skills.
        memory_path_line: Опциональная строка о project memory.

    Returns:
        XML-подобный русскоязычный prompt-блок runtime context.
    """

    return f"""
<runtime_context>
## Контекст запуска

Текущая дата: {current_date}.
Корень workspace: {workspace_tool_root_path} соответствует реальному пути {workspace_real_path}.
Директория data artifacts: {data_artifacts_tool_path} соответствует реальному пути {data_artifacts_real_path}.
{agent_root_line}{skills_root_line}{memory_path_line}

Для относительных дат в запросах пользователя рассчитывай период от текущей даты. Например, "последние 2 дня"
означает два календарных дня, заканчивающихся текущей датой, если пользователь явно не указал другую
бизнес-конвенцию. Никогда не бери относительные даты из примеров, validation cases, demo data или видимых партиций.

Используй `/artifacts` только для offload-файлов `load_data`, data exports и промежуточных результатов обработки.
Не перемещай обычные пользовательские файлы, исходный код, документацию, отчеты, notebooks или запрошенные файлы
репозитория в `/artifacts`, если пользователь явно не назвал этот путь. Для обычного создания файлов используй путь,
который запросил пользователь, или подходящий workspace-путь под `/`. Когда сообщаешь о сохраненных data artifacts,
указывай их workspace-путь.

Используй директорию реализации агента и директорию skills из этого runtime context. Не предполагай, что код агента
или skills находятся в `/deep_agent/`, если runtime context показывает другой путь.
</runtime_context>
""".strip()


__all__ = [
    "GIGACHAT_AGENT_PRACTICES_PROMPT",
    "GIGACHAT_CORE_PRACTICES_PROMPT",
    "GIGACHAT_EXTERNAL_RUNTIME_PRACTICES_PROMPT",
    "GIGACHAT_FILESYSTEM_PRACTICES_PROMPT",
    "GIGACHAT_FORMAT_PRACTICES_PROMPT",
    "GIGACHAT_PYTHON_PRACTICES_PROMPT",
    "GIGACHAT_SHELL_PRACTICES_PROMPT",
    "build_gigachat_practices_prompt",
    "build_runtime_context_prompt",
]
