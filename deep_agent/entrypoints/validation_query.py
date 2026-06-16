"""Печать запроса из локальной тестовой корзины.

Содержит функции:
- load_basket_query: поиск запроса по идентификатору кейса.
- main: обработка аргументов командной строки и печать запроса.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASKET_PATH = PROJECT_ROOT / "tests" / "evaluation" / "validation_cases.json"


def load_basket_query(case_id: str, basket_path: Path = DEFAULT_BASKET_PATH) -> str:
    """Возвращает текст запроса из тестовой корзины.

    Args:
        case_id: Строковый идентификатор тестового кейса.
        basket_path: Путь к JSON-файлу тестовой корзины.

    Returns:
        Текст пользовательского запроса.

    Raises:
        ValueError: Кейс с указанным идентификатором не найден.
    """

    payload = json.loads(basket_path.read_text(encoding="utf-8"))
    for case in payload.get("cases", []):
        if str(case.get("id")) == case_id:
            return str(case["query"])
    raise ValueError(f"Кейс {case_id} не найден в {basket_path}.")


def main() -> int:
    """Печатает выбранный запрос тестовой корзины.

    Returns:
        Код завершения процесса: ``0`` после успешной печати.
    """

    parser = argparse.ArgumentParser(description="Печать запроса из validation_cases.json.")
    parser.add_argument("--case-id", default="1", help="Идентификатор кейса.")
    args = parser.parse_args()
    print(load_basket_query(args.case_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
