"""Реестр доступных источников табличных данных.

Содержит:
- TABLE_ALIASES: соответствие публичных alias полным именам Spark-таблиц.
"""

from __future__ import annotations

TABLE_ALIASES: dict[str, str] = {
    "cards": "csp_afpc_sss_inc.cards_event",
    "uko": "csp_afpc_sss_inc.uko_event",
    "history_automarking": "csp_repo_features.history_automarking_big_148078_155487",
    "hits": "cspfs_repo_features3.hits_extra_info_129372427_view",
    "demo_client_timeline": "demo_client_timeline",
}
