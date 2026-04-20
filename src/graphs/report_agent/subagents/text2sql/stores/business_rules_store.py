"""
Business Rules Vector Store
============================
Text-to-SQL sistemleri için iş kurallarını semantic olarak arayan sınıf.

- description + modules embed edilir (SQL değil)
- SQL bileşenleri metadata'da saklanır
- Default kurallar ayrı collection'da (default_business_rules)
- Hybrid search (semantic + keyword)
- Similarity threshold (>0.7)
- Table-aware filtering
- LRU search cache (256 entry, dosya mtime ile invalidate)
"""
import json
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.factories.embedding_factory import EmbeddingFactory
from src.graphs.report_agent.subagents.text2sql.stores.base import BaseVectorStore

logger = logging.getLogger(__name__)


class BusinessRulesStore(BaseVectorStore):
    """
    İş kurallarını ChromaDB'de tutan ve semantic + keyword hybrid search yapan store.
    İki collection: 'business_rules' (normal) + 'default_business_rules' (her sorguya eklenir).
    """

    def __init__(
        self,
        rules_file_path: str,
        similarity_threshold: float = 0.7,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        embedding_fn = EmbeddingFactory.create_sentence_transformer(embedding_model)
        super().__init__(embedding_fn)

        self.rules_file_path = Path(rules_file_path)
        self.similarity_threshold = similarity_threshold

        self.rules_collection = None
        self.default_rules_collection = None
        self.rules_data = self._load_rules()

        self._search_cache: OrderedDict = OrderedDict()
        self._max_cache_size = 256
        self._cache_lock = threading.Lock()
        stat = os.stat(self.rules_file_path)
        self._rules_file_stat = (stat.st_mtime_ns, stat.st_size)

    # ------------------------------------------------------------------
    # BaseVectorStore interface
    # ------------------------------------------------------------------

    def initialize(self, force_recreate: bool = False) -> None:
        """Two collections: business_rules + default_business_rules."""
        logger.info("Initializing BusinessRulesStore collections...")

        if force_recreate:
            for name in ("business_rules", "default_business_rules"):
                try:
                    self._client.delete_collection(name)
                except Exception:
                    pass

        self.rules_collection = self._client.get_or_create_collection(
            name="business_rules",
            embedding_function=self._embedding_fn,
            metadata={"description": "Business logic rules for Text-to-SQL"},
        )
        self.default_rules_collection = self._client.get_or_create_collection(
            name="default_business_rules",
            embedding_function=self._embedding_fn,
            metadata={"description": "Default rules applied to all queries"},
        )

        if self.rules_collection.count() == 0:
            logger.info("[BUSINESS_RULES] Collections empty, building index...")
            self._build_index()

    def _build_index(self) -> None:
        """JSON -> embed -> iki collection'a yukle."""
        rules = self.rules_data["business_logic_rules"]
        normal_rules, default_rules = [], []

        for rule in rules:
            text = self._prepare_embedding_text(rule)
            meta = self._prepare_metadata(rule)
            entry = {"id": rule["id"], "text": text, "metadata": meta}
            (default_rules if rule["is_default"] else normal_rules).append(entry)

        if normal_rules:
            self.rules_collection.add(
                ids=[r["id"] for r in normal_rules],
                documents=[r["text"] for r in normal_rules],
                metadatas=[r["metadata"] for r in normal_rules],
            )
            logger.info(f"[BUSINESS_RULES] Indexed {len(normal_rules)} normal rules")

        if default_rules:
            self.default_rules_collection.add(
                ids=[r["id"] for r in default_rules],
                documents=[r["text"] for r in default_rules],
                metadatas=[r["metadata"] for r in default_rules],
            )
            logger.info(f"[BUSINESS_RULES] Indexed {len(default_rules)} default rules")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_rules(self) -> Dict[str, Any]:
        with open(self.rules_file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _file_has_changed(self) -> bool:
        stat = os.stat(self.rules_file_path)
        key = (stat.st_mtime_ns, stat.st_size)
        if key != self._rules_file_stat:
            self._rules_file_stat = key
            return True
        return False

    def _cache_key(self, user_query: str, n_results: int, use_hybrid: bool,
                   detected_tables=None) -> str:
        tables_part = ",".join(sorted(detected_tables)) if detected_tables else ""
        return f"{user_query}|{n_results}|{use_hybrid}|{tables_part}"

    def clear_cache(self):
        self._search_cache.clear()
        logger.info("[BUSINESS_RULES] Search cache cleared")

    def _prepare_embedding_text(self, rule: Dict[str, Any]) -> str:
        modules = ", ".join(rule["modules"])
        return f"{rule['description']}. Anahtar kelimeler: {modules}"

    def _prepare_metadata(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rule_id": rule["id"],
            "description": rule["description"],
            "modules": json.dumps(rule["modules"], ensure_ascii=False),
            "related_tables": json.dumps(rule.get("related_tables", []), ensure_ascii=False),
            "is_default": str(rule["is_default"]),
            "sql_aggregation": rule["sql"].get("aggregation") or "",
            "sql_filter": rule["sql"].get("filter") or "",
            "sql_group_by": rule["sql"].get("group_by") or "",
            "sql_select": rule["sql"].get("select") or "",
            "sql_join": rule["sql"].get("join") or "",
            "sql_having": rule["sql"].get("having") or "",
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_rules(
        self,
        query: str,
        n_results: int = 5,
        include_defaults: bool = True,
        table_filter: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        results = []

        if include_defaults:
            default_results = self.default_rules_collection.query(
                query_texts=[query], n_results=100
            )
            for i, rule_id in enumerate(default_results["ids"][0]):
                similarity = 1 - default_results["distances"][0][i]
                results.append({
                    "rule_id": rule_id,
                    "similarity": similarity,
                    "metadata": default_results["metadatas"][0][i],
                    "is_default": True,
                })

        search_results = self.rules_collection.query(
            query_texts=[query], n_results=n_results * 2, where=None
        )
        for i, rule_id in enumerate(search_results["ids"][0]):
            similarity = 1 - search_results["distances"][0][i]
            if similarity < self.similarity_threshold:
                continue
            metadata = search_results["metadatas"][0][i]
            if table_filter:
                related = json.loads(metadata["related_tables"])
                if "*" not in related and not any(t in related for t in table_filter):
                    continue
            results.append({
                "rule_id": rule_id,
                "similarity": similarity,
                "metadata": metadata,
                "is_default": False,
            })

        results = sorted(results, key=lambda x: x["similarity"], reverse=True)
        non_default = [r for r in results if not r["is_default"]][:n_results]
        defaults = [r for r in results if r["is_default"]]
        return defaults + non_default

    def keyword_search(self, keywords: List[str], n_results: int = 5) -> List[Dict[str, Any]]:
        results = []
        for keyword in keywords:
            sr = self.rules_collection.get(where_document={"$contains": keyword.lower()})
            for i, rule_id in enumerate(sr["ids"]):
                results.append({
                    "rule_id": rule_id,
                    "similarity": 0.9,
                    "metadata": sr["metadatas"][i],
                    "is_default": False,
                    "match_type": "keyword",
                })
        seen, unique = set(), []
        for r in results:
            if r["rule_id"] not in seen:
                seen.add(r["rule_id"])
                unique.append(r)
        return unique[:n_results]

    def merge_sql_components(
        self,
        rules: List[Dict[str, Any]],
        date_column: str = "created_at",
        amount_column: str = "amount",
    ) -> Dict[str, str]:
        merged = {k: [] for k in ("aggregation", "filter", "group_by", "select", "join", "having")}
        seen_components = {k: set() for k in ("filter", "join", "group_by", "select")}

        for rule in rules:
            meta = rule["metadata"]
            for comp in merged:
                value = meta.get(f"sql_{comp}", "").strip()
                if not value:
                    continue
                value = value.replace("{date_column}", date_column).replace("{amount_column}", amount_column)
                if comp in seen_components:
                    if value in seen_components[comp]:
                        continue
                    seen_components[comp].add(value)
                merged[comp].append(value)

        final: Dict[str, str] = {}
        if merged["aggregation"]:
            final["aggregation"] = merged["aggregation"][0]
        if merged["filter"]:
            final["filter"] = " AND ".join(f"({f})" for f in merged["filter"])
        if merged["group_by"]:
            final["group_by"] = ", ".join(merged["group_by"])
        if merged["select"]:
            final["select"] = ", ".join(merged["select"])
        if merged["join"]:
            final["join"] = " ".join(merged["join"])
        if merged["having"]:
            final["having"] = " AND ".join(f"({h})" for h in merged["having"])
        return final

    def get_relevant_rules_for_query(
        self,
        user_query: str,
        detected_tables: Optional[List[str]] = None,
        n_results: int = 5,
        use_hybrid: bool = True,
    ) -> Dict[str, Any]:
        with self._cache_lock:
            if self._file_has_changed():
                self._search_cache.clear()
                logger.info("[BUSINESS_RULES] Rules file changed, cache invalidated")
            cache_key = self._cache_key(user_query, n_results, use_hybrid, detected_tables)
            if cache_key in self._search_cache:
                logger.debug(f"[BUSINESS_RULES] Cache hit for: {user_query[:50]}")
                return self._search_cache[cache_key]

        semantic_results = self.search_rules(
            query=user_query, n_results=n_results,
            include_defaults=True, table_filter=detected_tables,
        )
        keyword_results = []
        if use_hybrid:
            keywords = [k for k in user_query.lower().split() if len(k) > 3]
            if keywords:
                keyword_results = self.keyword_search(keywords, n_results=3)

        seen_ids: set = set()
        unique_results = []
        for r in semantic_results + keyword_results:
            if r["rule_id"] not in seen_ids:
                seen_ids.add(r["rule_id"])
                unique_results.append(r)

        merged_sql = self.merge_sql_components(unique_results)
        default_count = sum(1 for r in unique_results if r["is_default"])

        individual_rules = []
        seen_individual: set = set()
        for r in unique_results:
            rid = r["rule_id"]
            if rid in seen_individual:
                continue
            seen_individual.add(rid)
            meta = r.get("metadata", {})
            individual_rules.append({
                "id": rid,
                "description": meta.get("description", ""),
                "sql": {
                    "aggregation": meta.get("sql_aggregation") or None,
                    "filter": meta.get("sql_filter") or None,
                    "group_by": meta.get("sql_group_by") or None,
                    "select": meta.get("sql_select") or None,
                    "join": meta.get("sql_join") or None,
                    "having": meta.get("sql_having") or None,
                },
                "is_default": r.get("is_default", False),
                "source": "default" if r.get("is_default") else "semantic",
            })

        result = {
            "individual_rules": individual_rules,
            "rules": unique_results,
            "merged_sql": merged_sql,
            "default_count": default_count,
            "semantic_count": len(unique_results) - default_count,
            "total_count": len(unique_results),
        }
        with self._cache_lock:
            if len(self._search_cache) >= self._max_cache_size:
                self._search_cache.popitem(last=False)
            self._search_cache[cache_key] = result
        return result
