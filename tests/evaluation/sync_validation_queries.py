"""Синхронизация тестовых запросов из ``run.py`` с тестовыми артефактами.

Содержит функции:
- load_run_queries: чтение констант ``USER_MESSAGE_N`` из ``run.py`` через AST.
- update_basket_queries: обновление текстов запросов в JSON-корзине.
- update_markdown_queries: обновление цитат с запросами в ``VALIDATION_CASES.md``.
- main: запуск синхронизации из командной строки.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_PATH = PROJECT_ROOT / "run.py"
DEFAULT_BASKET_PATH = Path(__file__).resolve().with_name("validation_cases.json")
DEFAULT_MARKDOWN_PATH = Path(__file__).resolve().with_name("VALIDATION_CASES.md")
QUERY_NAME_PATTERN = re.compile(r"USER_MESSAGE_(\d+)")
CASE_HEADING_PATTERN = re.compile(r"^###\s+(\d+)\.\s+", re.MULTILINE)


def load_run_queries(run_path: Path) -> dict[str, str]:
    """Читает тестовые запросы из констант ``USER_MESSAGE_N``.

    Args:
        run_path: Путь к Python-файлу с константами запросов.

    Returns:
        Словарь, где ключом является номер кейса, а значением - текст запроса.

    Raises:
        ValueError: Если выражение константы нельзя безопасно вычислить как строку.
    """

    module = ast.parse(run_path.read_text(encoding="utf-8"), filename=str(run_path))
    queries: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        match = QUERY_NAME_PATTERN.fullmatch(target.id)
        if match is None:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, str):
            raise ValueError(f"{target.id} должен содержать строку.")
        queries[match.group(1)] = value.strip()
    return queries


def update_basket_queries(basket_path: Path, queries: dict[str, str]) -> int:
    """Обновляет запросы существующих кейсов в JSON-корзине.

    Args:
        basket_path: Путь к JSON-файлу тестовой корзины.
        queries: Запросы из ``run.py``, индексированные номером кейса.

    Returns:
        Количество обновленных кейсов.

    Raises:
        ValueError: Если в корзине отсутствует кейс из ``run.py``.
    """

    payload = json.loads(basket_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("В тестовой корзине ожидается список cases.")

    cases_by_id = {str(case["id"]): case for case in cases}
    missing = sorted(set(queries) - set(cases_by_id), key=int)
    if missing:
        raise ValueError(f"В корзине отсутствуют кейсы: {', '.join(missing)}.")

    for case_id, query in queries.items():
        cases_by_id[case_id]["query"] = query
    basket_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(queries)


def update_markdown_queries(markdown_path: Path, queries: dict[str, str]) -> int:
    """Заменяет цитаты с запросами в разделах ``### N.`` Markdown-файла.

    Args:
        markdown_path: Путь к файлу с описанием тестовых кейсов.
        queries: Запросы из ``run.py``, индексированные номером кейса.

    Returns:
        Количество обновленных цитат.
    """

    text = markdown_path.read_text(encoding="utf-8")
    matches = list(CASE_HEADING_PATTERN.finditer(text))
    updated = 0
    chunks: list[str] = []
    cursor = 0

    for index, match in enumerate(matches):
        case_id = match.group(1)
        if case_id not in queries:
            continue
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.start():section_end]
        quote_match = re.search(r"(?m)^> .+(?:\n> .+)*", section)
        if quote_match is None:
            continue
        wrapped_query = "\n".join(f"> {line}" for line in queries[case_id].splitlines())
        absolute_start = match.start() + quote_match.start()
        absolute_end = match.start() + quote_match.end()
        chunks.extend([text[cursor:absolute_start], wrapped_query])
        cursor = absolute_end
        updated += 1

    chunks.append(text[cursor:])
    markdown_path.write_text("".join(chunks), encoding="utf-8")
    return updated


def main() -> int:
    """Синхронизирует запросы и печатает краткий результат.

    Returns:
        Код завершения процесса: ``0`` при успешной синхронизации.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN_PATH)
    parser.add_argument("--basket", type=Path, default=DEFAULT_BASKET_PATH)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_PATH)
    args = parser.parse_args()

    queries = load_run_queries(args.run)
    basket_count = update_basket_queries(args.basket, queries)
    markdown_count = update_markdown_queries(args.markdown, queries)
    print(f"Синхронизировано запросов: basket={basket_count}, markdown={markdown_count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
