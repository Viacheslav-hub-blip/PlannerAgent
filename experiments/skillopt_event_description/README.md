# Эксперимент SkillOpt для поиска сработок по описанию

Эта папка содержит одноразовую заготовку для проверки двух гипотез:

1. SkillOpt может улучшить preview/front matter skill так, чтобы агент начал выбирать нужный навык.
2. SkillOpt может улучшить содержимое skill так, чтобы агент после загрузки вызывал нужные инструменты и давал правильный ответ.

Код намеренно не подключается к основному агенту и не меняет production-skills. Он нужен как простой harness вокруг будущего SkillOpt rollout.

## Состав

- `broken_skill/SKILL.md` - намеренно плохой стартовый skill.
- `data/skill_selection_cases.jsonl` - корзина для теста выбора skill.
- `data/skill_content_cases.jsonl` - корзина для теста workflow после выбора skill.
- `scoring.py` - разбор trace, расчет метрик и заготовка LLM-as-a-judge.

## Источник эталонов

Эталоны посчитаны по таблице `hits`, локальный CSV:

`data/cspfs_repo_features3.hits_extra_info_129372427_view.csv`

Период данных: `20260124` - `20260309`.

## Как использовать

1. SkillOpt rollout запускает DeepAgent на `user_prompt` из item.
2. В тесте выбора skill нельзя принудительно загружать `event-description-search-skillopt`.
3. В тесте содержимого можно использовать уже выбранный skill или проверять весь путь целиком.
4. После запуска агента передайте в scorer финальный ответ и путь к trace:

```python
from experiments.skillopt_event_description.scoring import score_case

score = score_case(
    case=item,
    answer=agent_answer,
    trace_text=Path(trace_path).read_text(encoding="utf-8"),
)
```

`hard` равен `1` только если выполнены обязательные проверки. Если skill не выбран, тест сразу считается проваленным по hard.
