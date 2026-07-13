# Логическая жизнь запроса в DeepAgent

Документ описывает движение запроса, контекста и артефактов между ролями: полный путь запроса, видимость контекста ролями, выбор skills, tool-вызов и очистку контекста, а также передачу результата между агентами.

## 1. Полный путь запроса

```mermaid
flowchart TB
    Input["Сообщение пользователя"] --> State0["State: история + новый HumanMessage"]
    State0 --> Start["Старт supervisor turn"]
    Start --> Todo["TodoReset<br/>новый вопрос → очищает старый todos"]
    Todo --> Log["Request logging<br/>сохраняет запрос вне контекста модели"]
    Log --> Profile["User profile memory<br/>при первом turn создаёт профиль<br/>и подключает его к memory"]
    Profile --> Memory["MemoryMiddleware<br/>читает AGENTS.md и профиль"]
    Memory --> Select["Skills selector<br/>вопрос + index доступных SKILL.md"]
    Select --> Selected["State дополняется:<br/>preloaded_skill_paths<br/>preloaded_skills_context<br/>статус и причина выбора"]
    Selected --> Prompt["Сборка ModelRequest"]
    Prompt --> Model["Supervisor / KitAI"]
    Model --> Decision{"Решение модели"}
    Decision -- "Финальный ответ" --> Answer["Ответ пользователю"]
    Decision -- "Локальный tool" --> Tool["Проверка и выполнение tool"]
    Decision -- "task" --> Delegation["Делегирование подагенту"]
    Tool --> ToolResult["ToolMessage<br/>результат или ссылка на artifact"]
    Delegation --> SubagentResult["ToolMessage task<br/>compact report + пути artifacts"]
    ToolResult --> Prompt
    SubagentResult --> Prompt
    Answer --> Cleanup["TodoReset<br/>после final AIMessage очищает todos"]
```

Логгер не добавляет данные в prompt. Профиль пользователя не заменяет контекст: он создаёт memory-файл, который DeepAgents затем читает как системную память supervisor.

## 2. Что именно видит каждая роль

```mermaid
flowchart LR
    UserQuery["Вопрос пользователя"]

    subgraph Supervisor["Supervisor: планирует и синтезирует"]
        SPrompt["SYSTEM_PROMPT<br/>+ необязательный suffix"]
        SMemory["MemoryMiddleware:<br/>AGENTS.md + user_profile.md"]
        SSkills["Выбранные SKILL.md<br/>добавлены в system message"]
        SHistory["История supervisor<br/>вопросы, ответы, ToolMessage"]
        STools["Видимые tools:<br/>task, filesystem, execute,<br/>load_skills, python,<br/>get_project_structure и supervisor_tools"]
        SModel["Модель выбирает следующий шаг"]
        SPrompt --> SModel
        SMemory --> SModel
        SSkills --> SModel
        SHistory --> SModel
        STools --> SModel
    end

    subgraph Coding["coding-agent: выполняет изолированную coding-задачу"]
        CTask["Текст задачи от task"]
        CPrompt["CODING_AGENT_PROMPT"]
        CMemory["MemoryMiddleware:<br/>AGENTS.md"]
        CSkills["load_skills по запросу"]
        CTools["filesystem + execute,<br/>python, notebook, review,<br/>project structure"]
        CModel["Рабочая модель подагента"]
        CTask --> CModel
        CPrompt --> CModel
        CMemory --> CModel
        CSkills --> CModel
        CTools --> CModel
    end

    subgraph Data["data-retrieval-agent: подтверждает источник и выгружает"]
        DTask["Текст задачи от task"]
        DPrompt["DATA_RETRIEVAL_PROMPT"]
        DMemory["MemoryMiddleware:<br/>AGENTS.md"]
        DSkills["Те же предвыбранные SKILL.md<br/>из shared_selection"]
        DTools["load_data, load_skills, python,<br/>filesystem; без execute"]
        DModel["Рабочая модель подагента"]
        DTask --> DModel
        DPrompt --> DModel
        DMemory --> DModel
        DSkills --> DModel
        DTools --> DModel
    end

    UserQuery --> SHistory
    SModel -->|"task: отдельная атомарная задача"| CTask
    SModel -->|"task: отдельная атомарная задача"| DTask
    CModel -->|"отчёт и artifacts"| SHistory
    DModel -->|"compact evidence и artifacts"| SHistory
```

Подагенты не становятся копией supervisor: supervisor передаёт им формулировку атомарной задачи через task, а их рассуждение, tool history и лимиты остаются собственными. Общий канал для крупных результатов — файлы workspace/artifacts, а не полная история supervisor.

## 3. Как skills попадают в контекст

```mermaid
flowchart TB
    NativeIndex["Нативный SkillsMiddleware:<br/>name + description всех skills"] --> SupervisorPrompt
    NativeIndex --> DataPrompt
    NativeIndex --> CodingPrompt
    Question["Последний пользовательский вопрос"] --> Index["PreloadedSkillsContext:<br/>сканирование SKILL.md → компактный index"]
    Index --> Selector["KitAI selector со structured output"]
    Question --> Selector
    Selector --> Check{"Пути валидны и находятся<br/>в skills root?"}
    Check -- "Да" --> Read["Чтение выбранных SKILL.md<br/>с ограничением размера"]
    Check -- "Нет / ошибка" --> Retry["Одна корректирующая попытка selector"]
    Retry --> Check2{"Успех?"}
    Check2 -- "Да" --> Read
    Check2 -- "Нет" --> Failed["State: selection_failed<br/>skills не добавляются,<br/>в system message — диагностика"]
    Read --> Rewrite["Пути в тексте skill<br/>переписываются в workspace namespace"]
    Rewrite --> Cache["shared_selection:<br/>paths + context + status"]
    Cache --> SupervisorPrompt["Supervisor: добавляет context<br/>к system message"]
    Cache --> DataPrompt["data-retrieval-agent: читает<br/>тот же context из кэша"]
    Cache -. "Не подключён к preloading middleware" .-> CodingPrompt["coding-agent:<br/>загружает skills через load_skills"]
```

Каждая основная модель видит нативный index skills с `name` и `description`.
Дополнительно supervisor и data-agent получают полный текст автоматически
выбранных `SKILL.md`, но не всю папку skills. Связанные markdown-файлы и другие
skills любая роль может запросить через `load_skills`.

## 4. Жизнь одного model/tool шага

```mermaid
flowchart TB
    Request["ModelRequest:<br/>system message + history + tools"] --> ToolMeta["PromptToolFilter<br/>убирает запрещённые tools из видимости"]
    ToolMeta --> ToolDesc["PromptToolDescriptions<br/>подменяет descriptions встроенных tools"]
    ToolDesc --> Model["KitAI model"]
    Model --> Choice{"Ответ или tool call?"}
    Choice -- "Текст" --> Final["AIMessage"]
    Choice -- "Tool call" --> Path["FilesystemPathContract<br/>канонизирует workspace-путь"]
    Path --> Safety["ShellSafety<br/>блокирует небезопасный execute"]
    Safety --> Run["Реальный tool / backend"]
    Run --> Raw["ToolMessage;<br/>load_data уже вернул JSONL path и preview"]
    Raw --> Notice["ToolContextNotice<br/>добавляет смысловую пометку"]
    Notice --> History["История следующего ModelRequest"]
    History --> Guard["LoopBreaker анализирует хвост истории"]
    Guard --> Nudge{"Есть повторяющийся сбой<br/>или исчерпание бюджета?"}
    Nudge -- "Да" --> Hint["Добавляет HumanMessage:<br/>сменить стратегию"]
    Nudge -- "Нет" --> Request
    Hint --> Request
    Model -. "временная/provider ошибка" .-> Retry["ModelRetry<br/>повторяет только retriable error"]
    Retry --> Model
```

MemoryMiddleware добавляет файлы памяти в system prompt до model call. ToolCallLimit ограничивает число вызовов tools в запуске. У подагентов дополнительно действует ModelCallLimit. ContextEditing при достижении token-порога очищает старые tool-результаты из истории, но не удаляет созданные artifacts и не отменяет результат уже выполненного tool.

## 5. Передача данных между агентами и очистка контекста

```mermaid
flowchart LR
    S0["Supervisor<br/>получил вопрос"] --> D["data-retrieval-agent"]
    D --> Load["load_data"]
    Load --> Jsonl["Полный набор:<br/>artifacts/*.jsonl"]
    Load --> Preview["В контекст data-agent:<br/>query code, counts, preview, path"]
    Preview --> Evidence["Compact evidence report"]
    Evidence --> S1["Supervisor ToolMessage<br/>отчёт + artifact path"]
    S1 --> Decision{"Нужен расчёт / файл / код?"}
    Decision -- "Нет" --> Final["Supervisor synthesizes answer"]
    Decision -- "Да" --> C["coding-agent"]
    Jsonl --> C
    C --> Output["Новый файл / расчёт / проверка"]
    Output --> S2["Supervisor ToolMessage<br/>итог и пути outputs"]
    S2 --> Final

    subgraph ContextCleanup["Что очищается и что сохраняется"]
        H1["Старые ToolMessage<br/>могут быть удалены ContextEditing"] --> H2["Освобождается окно контекста"]
        A1["JSONL / созданные файлы"] --> A2["Остаются в workspace/artifacts<br/>и доступны по пути"]
        T1["todos прошлого turn"] --> T2["TodoReset очищает их<br/>до нового turn и после final"]
    end
```

Главный принцип: через prompt и ToolMessage передаются краткие доказательства и пути; через workspace/artifacts передаются полные наборы данных. Это предотвращает повторную выгрузку и не перегружает контекст модели.
