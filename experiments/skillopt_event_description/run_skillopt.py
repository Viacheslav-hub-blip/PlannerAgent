"""Запуск SkillOpt-эксперимента для улучшения skill поиска сработок.

Функции файла:
- main: запускает обучение SkillOpt на 5 эпох.
- run_agent_case: запускает DeepAgent на одном тестовом примере.
- build_agent_settings: создает настройки агента с временной папкой skills.
- extract_answer: достает финальный текст ответа агента.
- write_trainable_skill: записывает текущую версию обучаемого skill во временную папку.
"""

from __future__ import annotations

import builtins
import json
import random
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from langgraph.errors import GraphRecursionError
from skillopt.datasets.base import BaseDataLoader, BatchSpec
from skillopt.engine.trainer import ReflACTTrainer
from skillopt.envs.base import EnvAdapter
from skillopt.gradient.reflect import run_minibatch_reflect

from deep_agent.agent import build_analytics_deep_agent
from deep_agent.settings import load_deep_agent_settings
from deep_agent.runtime.tracing import FileTraceCallbackHandler, build_trace_file_path
from tests.support.fake_spark_data import build_fake_spark_data_tools
from experiments.skillopt_event_description.scoring import (
    judge_answer_with_llm,
    load_jsonl,
    score_case,
)
from model import model


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
TARGET_SKILL_ID = "event-description-search-skillopt"
INITIAL_SKILL_PATH = EXPERIMENT_ROOT / "broken_skill" / "SKILL.md"
OUT_ROOT = ROOT / "runs" / "skillopt_event_description"
NUM_EPOCHS = 6
TRAIN_CASES = 8
VALID_CASES = 2

SKILLOPT_DEFAULTS = {
    "model_backend": "openai_chat",
    "optimizer_backend": "openai_chat",
    "target_backend": "openai_chat",
    "optimizer_model": getattr(model, "model_name", None) or getattr(model, "model", "configured-model"),
    "target_model": getattr(model, "model_name", None) or getattr(model, "model", "configured-model"),
    "reasoning_effort": "medium",
    "accumulation": 1,
    "seed": 42,
    "minibatch_size": 2,
    "merge_batch_size": 2,
    "analyst_workers": 1,
    "failure_only": False,
    "max_analyst_rounds": 3,
    "skill_update_mode": "rewrite_from_suggestions",
    "lr_control_mode": "fixed",
    "longitudinal_pair_policy": "mixed",
    "rewrite_reasoning_effort": "high",
    "rewrite_max_completion_tokens": 64000,
    "edit_budget": 12,
    "min_edit_budget": 2,
    "lr_scheduler": "cosine",
    "eval_test": True,
    "use_gate": True,
    "gate_metric": "soft",
    "use_slow_update": False,
    "slow_update_samples": 0,
    "use_meta_skill": False,
}

_skillopt_rewrite_original: Any | None = None


class EventDescriptionDataLoader(BaseDataLoader):
    """Загружает маленькую тестовую корзину для SkillOpt.

    Args:
        cases: Список тестовых примеров для обучения, валидации и теста.

    Returns:
        Dataloader, который отдает batch-и в формате SkillOpt.
    """

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        """Сохраняет split-ы тестовой корзины.

        Args:
            cases: Список тестовых примеров.

        Returns:
            ``None``. Split-ы сохраняются в состоянии объекта.
        """

        self.train_items = cases[:TRAIN_CASES]
        self.val_items = cases[TRAIN_CASES : TRAIN_CASES + VALID_CASES]
        self.test_items = list(cases)

    def get_train_size(self) -> int:
        """Возвращает размер обучающей выборки.

        Args:
            Отсутствуют.

        Returns:
            Количество train-примеров.
        """

        return len(self.train_items)

    def build_train_batch(self, batch_size: int, seed: int, **kwargs: Any) -> BatchSpec:
        """Строит train batch для одной итерации SkillOpt.

        Args:
            batch_size: Максимальное число примеров в batch.
            seed: Seed для перемешивания.
            **kwargs: Дополнительные параметры SkillOpt, не используемые здесь.

        Returns:
            ``BatchSpec`` со списком train-примеров.
        """

        del kwargs
        items = list(self.train_items)
        random.Random(seed).shuffle(items)
        items = items[:batch_size]
        return BatchSpec(phase="train", split="train", seed=seed, batch_size=len(items), payload=items)

    def build_eval_batch(self, env_num: int, split: str, seed: int, **kwargs: Any) -> BatchSpec:
        """Строит eval batch для validation или test.

        Args:
            env_num: Максимальное число примеров.
            split: Имя split из SkillOpt.
            seed: Seed запуска.
            **kwargs: Дополнительные параметры SkillOpt, не используемые здесь.

        Returns:
            ``BatchSpec`` со списком eval-примеров.
        """

        del seed, kwargs
        items = self.val_items if split in {"valid_seen", "val"} else self.test_items
        if env_num:
            items = items[:env_num]
        return BatchSpec(phase="eval", split=split, seed=0, batch_size=len(items), payload=items)


class EventDescriptionAdapter(EnvAdapter):
    """Адаптер SkillOpt для запуска DeepAgent на задачах поиска сработок.

    Args:
        cases: Тестовые примеры эксперимента.

    Returns:
        Adapter, совместимый с ``ReflACTTrainer``.
    """

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        """Инициализирует adapter.

        Args:
            cases: Список тестовых примеров.

        Returns:
            ``None``. Dataloader сохраняется в состоянии объекта.
        """

        self.dataloader = EventDescriptionDataLoader(cases)

    def get_dataloader(self) -> EventDescriptionDataLoader:
        """Возвращает dataloader эксперимента.

        Args:
            Отсутствуют.

        Returns:
            Объект ``EventDescriptionDataLoader``.
        """

        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs: Any) -> list[dict[str, Any]]:
        """Преобразует batch SkillOpt в список тестовых примеров.

        Args:
            batch: Batch, созданный dataloader-ом.
            **kwargs: Дополнительные параметры SkillOpt, не используемые здесь.

        Returns:
            Список тестовых примеров.
        """

        del kwargs
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Строит train environment.

        Args:
            batch_size: Размер batch.
            seed: Seed batch.
            **kwargs: Дополнительные параметры SkillOpt.

        Returns:
            Список train-примеров.
        """

        return self.build_env_from_batch(self.dataloader.build_train_batch(batch_size, seed), **kwargs)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs: Any) -> list[dict[str, Any]]:
        """Строит eval environment.

        Args:
            env_num: Размер eval batch.
            split: Имя split.
            seed: Seed batch.
            **kwargs: Дополнительные параметры SkillOpt.

        Returns:
            Список eval-примеров.
        """

        return self.build_env_from_batch(self.dataloader.build_eval_batch(env_num, split, seed), **kwargs)

    def rollout(self, env_manager: list[dict[str, Any]], skill_content: str, out_dir: str, **kwargs: Any) -> list[dict]:
        """Запускает DeepAgent на batch-е примеров и возвращает оценки SkillOpt.

        Args:
            env_manager: Список тестовых примеров.
            skill_content: Текущая версия обучаемого skill.
            out_dir: Папка артефактов текущего rollout.
            **kwargs: Дополнительные параметры SkillOpt, не используемые здесь.

        Returns:
            Список результатов с обязательными полями ``id``, ``hard`` и ``soft``.
        """

        del kwargs
        rollout_dir = Path(out_dir)
        skills_root = write_trainable_skill(skill_content, rollout_dir)
        results: list[dict] = []
        for item in env_manager:
            answer, trace_path = run_agent_case(item, skills_root)
            trace_text = trace_path.read_text(encoding="utf-8")
            score = score_case(item, answer, trace_text)
            save_prediction_artifacts(
                prediction_dir=rollout_dir / "predictions",
                item=item,
                answer=answer,
                trace_text=trace_text,
                score=score,
            )
            score["fail_reason"] = score["failure_type"]
            score["task_description"] = item["user_prompt"]
            score["target_user_prompt"] = item["user_prompt"]
            score["answer"] = answer
            score["predicted_answer"] = answer
            score["trace_path"] = str(trace_path)
            score["llm_judge"] = judge_answer_with_llm(model, item, answer)
            score["task_type"] = item.get("test_type", "event_description_search")
            results.append(score)
        return results

    def reflect(self, results: list[dict], skill_content: str, out_dir: str, **kwargs: Any) -> list[dict | None]:
        """Запускает стандартную reflection-фазу SkillOpt.

        Args:
            results: Результаты rollout.
            skill_content: Текущая версия skill.
            out_dir: Папка артефактов reflection.
            **kwargs: Параметры, которые передает SkillOpt.

        Returns:
            Список patch-предложений SkillOpt.
        """

        cfg = getattr(self, "_cfg", {})
        return run_minibatch_reflect(
            results=results,
            skill_content=skill_content,
            prediction_dir=kwargs.get("prediction_dir", str(Path(out_dir) / "predictions")),
            patches_dir=kwargs.get("patches_dir", str(Path(out_dir) / "patches")),
            workers=cfg.get("analyst_workers", 1),
            failure_only=cfg.get("failure_only", False),
            minibatch_size=cfg.get("minibatch_size", 2),
            edit_budget=cfg.get("edit_budget", 4),
            random_seed=kwargs.get("random_seed"),
            error_system=self.get_error_minibatch_prompt(),
            success_system=self.get_success_minibatch_prompt(),
            step_buffer_context=kwargs.get("step_buffer_context", ""),
            meta_skill_context=kwargs.get("meta_skill_context", ""),
            update_mode=cfg.get("skill_update_mode", "patch"),
        )

    def get_task_types(self) -> list[str]:
        """Возвращает типы задач эксперимента.

        Args:
            Отсутствуют.

        Returns:
            Список типов задач.
        """

        return ["skill_selection", "skill_content"]


def main() -> int:
    """Запускает обучение SkillOpt на 5 эпох.

    Args:
        Отсутствуют.

    Returns:
        Код завершения процесса.
    """

    cases = load_jsonl(EXPERIMENT_ROOT / "data" / "skill_selection_cases.jsonl")
    cases += load_jsonl(EXPERIMENT_ROOT / "data" / "skill_content_cases.jsonl")
    train_size = min(TRAIN_CASES, len(cases))
    valid_size = min(VALID_CASES, max(0, len(cases) - train_size))
    test_size = len(cases)
    install_skillopt_model_bridge()
    cfg = build_skillopt_config(
        out_root=str(OUT_ROOT),
        skill_init=str(INITIAL_SKILL_PATH),
        num_epochs=NUM_EPOCHS,
        train_size=train_size,
        batch_size=2,
        sel_env_num=valid_size,
        test_env_num=test_size,
    )
    summary = ReflACTTrainer(cfg, EventDescriptionAdapter(cases)).train()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def install_skillopt_model_bridge() -> None:
    """Направляет optimizer-вызовы SkillOpt в модель из ``model.py``.

    Args:
        Отсутствуют.

    Returns:
        ``None``. Функция подменяет runtime-функции SkillOpt в памяти текущего процесса.
    """

    import skillopt.gradient.aggregate as aggregate_module
    import skillopt.gradient.reflect as reflect_module
    import skillopt.engine.trainer as trainer_module
    import skillopt.model as skillopt_model_module
    import skillopt.optimizer.clip as clip_module
    import skillopt.optimizer.lr_autonomous as lr_module
    import skillopt.optimizer.meta_skill as meta_module
    import skillopt.optimizer.rewrite as rewrite_module
    import skillopt.optimizer.slow_update as slow_module

    modules = [
        trainer_module,
        skillopt_model_module,
        reflect_module,
        aggregate_module,
        clip_module,
        lr_module,
        meta_module,
        rewrite_module,
        slow_module,
    ]
    for module in modules:
        if hasattr(module, "chat_optimizer"):
            module.chat_optimizer = _chat_optimizer_via_project_model
    _install_utf8_open_for_skillopt_modules(modules)

    global _skillopt_rewrite_original
    if _skillopt_rewrite_original is None:
        _skillopt_rewrite_original = rewrite_module.rewrite_skill_from_suggestions
    rewrite_module.rewrite_skill_from_suggestions = _rewrite_skill_with_skill_format_guard
    trainer_module.rewrite_skill_from_suggestions = _rewrite_skill_with_skill_format_guard


def _install_utf8_open_for_skillopt_modules(modules: list[Any]) -> None:
    """Устанавливает UTF-8 чтение и запись для текстовых файлов SkillOpt.

    Args:
        modules: Список импортированных Python-модулей SkillOpt, в которых нужно переопределить имя ``open``.

    Returns:
        ``None``. Модули получают локальную функцию ``open``, которая добавляет ``encoding="utf-8"`` только для
        текстовых режимов без явно указанной кодировки.
    """

    def open_utf8_default(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        """Открывает файл с UTF-8 по умолчанию для текстового режима.

        Args:
            file: Путь или файловый дескриптор, переданный в ``open``.
            mode: Режим открытия файла.
            *args: Позиционные аргументы стандартного ``open``.
            **kwargs: Именованные аргументы стандартного ``open``.

        Returns:
            Файловый объект, возвращенный стандартным ``open``.
        """

        if "b" not in mode and "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
        return builtins.open(file, mode, *args, **kwargs)

    for module in modules:
        module.open = open_utf8_default


def _rewrite_skill_with_skill_format_guard(skill_content: str, patch: dict, **kwargs: Any) -> dict | None:
    """Переписывает skill через SkillOpt и сохраняет обязательную структуру ``SKILL.md``.

    Args:
        skill_content: Текущий текст skill с валидным YAML frontmatter.
        patch: Выбранные SkillOpt suggestions для rewrite.
        **kwargs: Параметры, которые передает SkillOpt в ``rewrite_skill_from_suggestions``.

    Returns:
        Словарь результата rewrite с нормализованным ``new_skill`` или ``None``, если rewrite не удался.
    """

    if _skillopt_rewrite_original is None:
        return None
    result = _skillopt_rewrite_original(skill_content, patch, **kwargs)
    if not result or not str(result.get("new_skill", "")).strip():
        return result
    result["new_skill"] = normalize_rewritten_skill(skill_content, str(result["new_skill"]))
    change_summary = result.get("change_summary")
    if isinstance(change_summary, list):
        change_summary.append("Preserved original YAML frontmatter and removed wrapper text from rewritten skill.")
    else:
        result["change_summary"] = ["Preserved original YAML frontmatter and removed wrapper text from rewritten skill."]
    return result


def normalize_rewritten_skill(current_skill: str, rewritten_skill: str) -> str:
    """Нормализует результат полного rewrite, не давая модели сломать metadata skill.

    Args:
        current_skill: Текущий валидный skill, из которого берется YAML frontmatter.
        rewritten_skill: Новый текст skill, возвращенный optimizer-моделью.

    Returns:
        Полный текст skill с исходным YAML frontmatter и очищенным body из rewrite-результата.
    """

    frontmatter, current_body = _split_skill_frontmatter(current_skill)
    body = _extract_rewritten_body(rewritten_skill)
    if not body.strip():
        body = current_body
    return f"{frontmatter.rstrip()}\n\n{body.strip()}\n"


def _split_skill_frontmatter(skill_content: str) -> tuple[str, str]:
    """Разделяет skill на YAML frontmatter и body.

    Args:
        skill_content: Текст skill.

    Returns:
        Кортеж ``(frontmatter, body)``. Если frontmatter не найден, возвращается стандартный блок для тестового skill.
    """

    lines = skill_content.replace("\r\n", "\n").splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[: index + 1]), "\n".join(lines[index + 1 :])
    frontmatter = (
        "---\n"
        f"name: {TARGET_SKILL_ID}\n"
        'description: "Internal notes for generic reference questions, text fields, and helper descriptions."\n'
        'keywords: "reference, notes, text, description, generic information"\n'
        "---"
    )
    return frontmatter, skill_content


def _extract_rewritten_body(rewritten_skill: str) -> str:
    """Извлекает содержательную часть skill из ответа rewrite-модели.

    Args:
        rewritten_skill: Сырой текст ``new_skill`` из SkillOpt rewrite.

    Returns:
        Body skill без YAML frontmatter, markdown code fences и служебных префиксов.
    """

    text = rewritten_skill.replace("\r\n", "\n").strip()
    text = _strip_markdown_fence(text)
    lines = text.splitlines()
    if lines and lines[0].strip().lower() == "## current skill":
        lines = lines[1:]
        text = "\n".join(lines).strip()
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :])
    for index, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def _strip_markdown_fence(text: str) -> str:
    """Удаляет внешний markdown code fence из текста.

    Args:
        text: Сырой текст ответа модели.

    Returns:
        Текст без внешнего блока ``````, если весь ответ был завернут в него.
    """

    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def _chat_optimizer_via_project_model(
    system: str,
    user: str,
    max_completion_tokens: int = 16384,
    retries: int = 5,
    stage: str = "optimizer",
    **kwargs: Any,
) -> tuple[str, dict[str, int]]:
    """Выполняет optimizer-запрос SkillOpt через LangChain-модель проекта.

    Args:
        system: System prompt из SkillOpt.
        user: User prompt из SkillOpt.
        max_completion_tokens: Лимит ответа, переданный SkillOpt.
        retries: Число повторов, переданное SkillOpt.
        stage: Название стадии SkillOpt.
        **kwargs: Дополнительные параметры SkillOpt, не используемые здесь.

    Returns:
        Кортеж из текста ответа и пустой статистики токенов.
    """

    del max_completion_tokens, kwargs
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_error: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            response = model.invoke(messages)
            content = getattr(response, "content", response)
            if isinstance(content, list):
                content = "\n".join(str(item) for item in content)
            return str(content), {"calls": 1}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    return "", {"calls": 0, "stage": stage}


def build_skillopt_config(**overrides: Any) -> dict[str, Any]:
    """Собирает минимальный config запуска SkillOpt поверх дефолтов.

    Args:
        **overrides: Параметры, которые относятся именно к текущему эксперименту.

    Returns:
        Flat-config для ``ReflACTTrainer``.
    """

    return {**SKILLOPT_DEFAULTS, **overrides}


def run_agent_case(item: dict[str, Any], skills_root: Path) -> tuple[str, Path]:
    """Запускает основной DeepAgent на одном тестовом примере.

    Args:
        item: Тестовый пример с пользовательским запросом.
        skills_root: Временная папка skills с текущей версией обучаемого skill.

    Returns:
        Кортеж из финального ответа и пути к trace-файлу.
    """

    settings = build_agent_settings(skills_root)
    data_tools = build_fake_spark_data_tools(query_parser_model=model)
    agent = build_analytics_deep_agent(model=model, settings=settings, data_tools=data_tools)
    trace_file_path = build_trace_file_path(settings.trace_log_dir)
    trace_handler = FileTraceCallbackHandler(trace_file_path)
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": item["user_prompt"]}]},
            config={
                "callbacks": [trace_handler],
                "configurable": {"thread_id": f"skillopt-{item['id']}"},
                "recursion_limit": settings.graph_recursion_limit,
            },
        )
    except GraphRecursionError as exc:
        error_message = (
            "ROLL ОUT FAILED: агент превысил graph_recursion_limit и не завершил задачу. "
            f"case_id={item['id']}; error={exc}"
        )
        _append_rollout_error(trace_file_path, error_message)
        return error_message, Path(trace_file_path)
    return extract_answer(result), Path(trace_file_path)


def _append_rollout_error(trace_file_path: str | Path, message: str) -> None:
    """Добавляет диагностическое сообщение об ошибке rollout в trace-файл.

    Args:
        trace_file_path: Путь к trace-файлу текущего запуска агента.
        message: Краткое описание ошибки, которое нужно сохранить для scorer и reflection.

    Returns:
        ``None``. Сообщение дописывается в конец trace-файла.
    """

    path = Path(trace_file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write("\n\n===== ROLLOUT ERROR =====\n")
        file.write(message)
        file.write("\n")


def build_agent_settings(skills_root: Path):
    """Создает настройки агента с временной папкой skills.

    Args:
        skills_root: Папка skills для текущего rollout.

    Returns:
        Настройки DeepAgent с переопределенным ``skills_root``.
    """

    settings = load_deep_agent_settings()
    return replace(settings, skills_root=skills_root)


def extract_answer(result: Any) -> str:
    """Извлекает финальный ответ из результата ``agent.invoke``.

    Args:
        result: Результат запуска DeepAgent.

    Returns:
        Текст финального ответа агента.
    """

    messages = result.get("messages", []) if isinstance(result, dict) else []
    if not messages:
        return str(result)
    content = getattr(messages[-1], "content", "")
    return content if isinstance(content, str) else str(content)


def save_prediction_artifacts(
    prediction_dir: Path,
    item: dict[str, Any],
    answer: str,
    trace_text: str,
    score: dict[str, Any],
) -> None:
    """Сохраняет trajectory-файлы в формате, который читает SkillOpt reflect.

    Args:
        prediction_dir: Папка ``predictions`` текущего rollout.
        item: Тестовый пример.
        answer: Финальный ответ агента.
        trace_text: Полный trace запуска агента.
        score: Результат расчета метрик.

    Returns:
        ``None``. Функция пишет файлы на диск.
    """

    case_dir = prediction_dir / str(item["id"])
    case_dir.mkdir(parents=True, exist_ok=True)
    conversation = [
        {"role": "user", "content": item["user_prompt"]},
        {"role": "assistant", "content": answer},
        {
            "role": "system",
            "content": json.dumps(
                {
                    "score": score,
                    "expected_result": item.get("expected_result", {}),
                    "required_tools": item.get("required_tools", []),
                    "trace_excerpt": _compact_trace_for_reflection(trace_text),
                },
                ensure_ascii=False,
                indent=2,
            ),
        },
    ]
    (case_dir / "conversation.json").write_text(
        json.dumps(conversation, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    (case_dir / "target_user_prompt.txt").write_text(item["user_prompt"], encoding="utf-8")
    (case_dir / "target_system_prompt.txt").write_text(
        f"Target skill id: {item['target_skill_id']}",
        encoding="utf-8",
    )


def _compact_trace_for_reflection(trace_text: str, max_chars: int = 6000) -> str:
    """Сжимает trace для передачи optimizer-аналитику SkillOpt.

    Args:
        trace_text: Полный trace запуска.
        max_chars: Максимальная длина возвращаемого текста.

    Returns:
        Начало и конец trace, если он слишком длинный.
    """

    if len(trace_text) <= max_chars:
        return trace_text
    half = max_chars // 2
    return f"{trace_text[:half]}\n...[middle truncated]...\n{trace_text[-half:]}"


def write_trainable_skill(skill_content: str, rollout_dir: Path) -> Path:
    """Записывает текущий trainable skill во временную копию skills.

    Args:
        skill_content: Текущий текст skill, который оптимизирует SkillOpt.
        rollout_dir: Папка текущего rollout.

    Returns:
        Путь к временной папке skills.
    """

    source_root = ROOT / "deep_agent" / "resources" / "skills"
    skills_root = rollout_dir / "skills"
    if skills_root.exists():
        shutil.rmtree(skills_root)
    shutil.copytree(source_root, skills_root)
    target_dir = skills_root / TARGET_SKILL_ID
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
    return skills_root


if __name__ == "__main__":
    raise SystemExit(main())
