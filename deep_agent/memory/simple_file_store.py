"""Файловое хранилище долговременной памяти агента.

Содержит:
- SimpleFileStore: минимальная реализация LangGraph BaseStore на JSON-файлах.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from langgraph.store.base import BaseStore, GetOp, Item, ListNamespacesOp, PutOp, SearchItem, SearchOp


class SimpleFileStore(BaseStore):
    """Хранит элементы LangGraph Store в JSON-файлах на локальном диске.

    Args:
        root_dir: Директория, в которой будут храниться JSON-файлы памяти.

    Returns:
        Экземпляр файлового хранилища для ``StoreBackend``.
    """

    def __init__(self, root_dir: str | Path = "./agent_data") -> None:
        """Создает файловое хранилище и базовую директорию.

        Args:
            root_dir: Директория для JSON-файлов памяти.

        Returns:
            ``None``.
        """

        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, namespace: tuple[str, ...], key: str) -> Path:
        """Строит путь к JSON-файлу для namespace и ключа.

        Args:
            namespace: Пространство имен LangGraph Store.
            key: Ключ элемента внутри namespace.

        Returns:
            Абсолютный путь к JSON-файлу.
        """

        safe_namespace = "_".join(namespace) if namespace else "_default"
        clean_key = key.lstrip("/")
        return self.root_dir / safe_namespace / f"{clean_key}.json"

    def _load_item(self, namespace: tuple[str, ...], key: str) -> Item | None:
        """Загружает один элемент из JSON-файла.

        Args:
            namespace: Пространство имен LangGraph Store.
            key: Ключ элемента внутри namespace.

        Returns:
            Элемент Store или ``None``, если файл отсутствует или поврежден.
        """

        path = self._get_path(namespace, key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            now = datetime.now(timezone.utc)
            created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else now
            updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else now
            return Item(
                namespace=namespace,
                key=key,
                value=data.get("value", data),
                created_at=created_at,
                updated_at=updated_at,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _save_item(self, item: Item) -> None:
        """Сохраняет один элемент Store в JSON-файл.

        Args:
            item: Элемент LangGraph Store для сохранения.

        Returns:
            ``None``.
        """

        path = self._get_path(item.namespace, item.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "value": item.value,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _search_items(
        self,
        namespace_prefix: tuple[str, ...],
        query: str | None,
        limit: int,
        offset: int,
    ) -> list[SearchItem]:
        """Ищет элементы по простому текстовому совпадению в JSON-значении.

        Args:
            namespace_prefix: Namespace, внутри которого нужно искать элементы.
            query: Текст для поиска или ``None``.
            limit: Максимальное число элементов результата.
            offset: Число найденных элементов, которое нужно пропустить.

        Returns:
            Список найденных элементов Store.
        """

        safe_namespace = "_".join(namespace_prefix) if namespace_prefix else "_default"
        namespace_dir = self.root_dir / safe_namespace
        if not namespace_dir.exists():
            return []

        items: list[SearchItem] = []
        query_text = query.lower() if query else None
        for file_path in namespace_dir.rglob("*.json"):
            key = file_path.relative_to(namespace_dir).as_posix()[:-5]
            item = self._load_item(namespace_prefix, key)
            if item is None:
                continue
            value_text = json.dumps(item.value, ensure_ascii=False).lower()
            if query_text and query_text not in value_text:
                continue
            items.append(
                SearchItem(
                    namespace=item.namespace,
                    key=item.key,
                    value=item.value,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )

        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[offset : offset + limit]

    def batch(self, ops: Sequence[Any]) -> list[Any]:
        """Синхронно выполняет операции LangGraph Store.

        Args:
            ops: Список операций ``PutOp``, ``GetOp``, ``SearchOp`` или ``ListNamespacesOp``.

        Returns:
            Список результатов в порядке входных операций.
        """

        results: list[Any] = []
        for op in ops:
            if isinstance(op, PutOp):
                if op.value is None:
                    path = self._get_path(op.namespace, op.key)
                    if path.exists():
                        path.unlink()
                else:
                    now = datetime.now(timezone.utc)
                    old_item = self._load_item(op.namespace, op.key)
                    self._save_item(
                        Item(
                            namespace=op.namespace,
                            key=op.key,
                            value=op.value,
                            created_at=old_item.created_at if old_item else now,
                            updated_at=now,
                        )
                    )
                results.append(None)
            elif isinstance(op, GetOp):
                results.append(self._load_item(op.namespace, op.key))
            elif isinstance(op, SearchOp):
                results.append(
                    self._search_items(
                        namespace_prefix=op.namespace_prefix,
                        query=op.query,
                        limit=op.limit,
                        offset=op.offset,
                    )
                )
            elif isinstance(op, ListNamespacesOp):
                namespaces = [(path.name,) for path in self.root_dir.iterdir() if path.is_dir()]
                results.append(namespaces)
            else:
                results.append(None)
        return results

    async def abatch(self, ops: Sequence[Any]) -> list[Any]:
        """Асинхронно выполняет операции LangGraph Store.

        Args:
            ops: Список операций Store.

        Returns:
            Список результатов в порядке входных операций.
        """

        return self.batch(ops)
