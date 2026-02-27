"""
Term Vector Store
=================
Kullanıcı sorgusundaki Türkçe iş terimlerini semantik olarak tespit eder.

BusinessRulesVectorStore ile aynı pattern:
  - JSON → ChromaDB (sentence-transformers embedding)
  - Graph startup'ta initialize edilir
  - resolve(user_query) → TermResolverOutput

Conflict resolution algoritması:
  - Candidates sıralanır: similarity * specificity (desc)
  - Unambiguous term bir kolonu resolve ederse → resolved_columns'a eklenir
  - Ambiguous term geldiğinde: tüm kolonları zaten resolved_columns'da mı?
      Evet (tümü veya kısmen) → SUPPRESS, resolved term'e hint eklenir
      Hiçbiri                 → interrupt listesine ekle

SOLID:
  S — resolve() conflict resolution, _semantic_search() ChromaDB ayrı
  O — Yeni category/term → JSON + rebuild, kod değişmez
  D — Node TermVectorStore'a depend eder, keyword logic'e değil
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "term_dictionary"
_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_SIMILARITY_THRESHOLD = 0.60
_TOP_K = 15


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class AmbiguousMatch:
    """Kullanıcıya sorulması gereken belirsiz terim."""
    term: str
    user_query: str
    options: List[Dict[str, Any]]


@dataclass
class TermResolverOutput:
    """
    TermVectorStore.resolve() dönüş tipi.

    term_filters : Python katmanı tarafından QuerySchema'ya merge edilir.
    hints_text   : LLM prompt'una inject edilir.
    ambiguous    : interrupt() ile kullanıcıya sorulacak terimler.
    """
    term_filters: List[Dict[str, Any]] = field(default_factory=list)
    hints_text: str = "Özel terim eşleşmesi bulunamadı."
    ambiguous: List[AmbiguousMatch] = field(default_factory=list)


@dataclass
class TermCandidate:
    """
    Semantic search sonucu — tek bir term entry.
    resolve() bu nesneler üzerinde çalışır.
    """
    term_id: str
    category: str
    term: str
    column: str               # "" if ambiguous
    specificity: float
    hint: str
    filter_structured: Optional[Dict[str, Any]]
    ambiguous_columns: List[Dict[str, Any]]  # [] if unambiguous
    similarity: float

    @property
    def is_ambiguous(self) -> bool:
        return bool(self.ambiguous_columns)

    @property
    def sort_key(self) -> float:
        return self.similarity * self.specificity


# =============================================================================
# TermVectorStore
# =============================================================================

class TermVectorStore:
    """
    term_dictionary.json → ChromaDB semantic index.

    Kullanım:
        store = TermVectorStore(dict_path=..., persist_directory=...)
        store.initialize()          # graph startup'ta bir kez
        output = store.resolve(user_query)   # her sorguda
    """

    def __init__(
        self,
        dict_path: str | Path,
        persist_directory: str,
        embedding_model: str = _DEFAULT_MODEL,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self.dict_path = Path(dict_path)
        self.similarity_threshold = similarity_threshold

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False,
        ))

        import os
        try:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from chromadb.utils import embedding_functions
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )
            if os.environ.get("HF_HUB_OFFLINE") == "1":
                del os.environ["HF_HUB_OFFLINE"]
        except Exception:
            os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "300"
            from chromadb.utils import embedding_functions
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=embedding_model
            )

        self._collection = None
        self._terms_data: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(self, force_recreate: bool = False) -> None:
        """
        Graph startup'ta çağrılır.
        Collection yoksa veya boşsa index_terms() tetikler.
        """
        if force_recreate:
            try:
                self._client.delete_collection(_DEFAULT_COLLECTION)
            except Exception:
                pass

        self._collection = self._client.get_or_create_collection(
            name=_DEFAULT_COLLECTION,
            embedding_function=self._embedding_fn,
            metadata={"description": "Turkish business term dictionary for Text-to-SQL"},
        )

        self._terms_data = self._load_dict()

        if self._collection.count() == 0:
            logger.info("[TERM_VECTOR_STORE] Collection empty, building index...")
            self.index_terms()
        else:
            logger.info(
                f"[TERM_VECTOR_STORE] Collection ready ({self._collection.count()} terms)"
            )

    def index_terms(self) -> None:
        """JSON → embed → ChromaDB. initialize() tarafından çağrılır."""
        if not self._terms_data:
            self._terms_data = self._load_dict()

        ids, documents, metadatas = [], [], []

        for entry in self._terms_data:
            term_id = entry["id"]
            embedding_text = entry.get("embedding_text") or self._build_embedding_text(entry)

            metadata = {
                "term_id":                 term_id,
                "category":                entry.get("category", ""),
                "term":                    entry["term"],
                "column":                  entry.get("column", ""),
                "specificity":             str(entry.get("specificity", 1.0)),
                "hint":                    entry.get("hint", ""),
                "filter_structured_json":  json.dumps(entry.get("filter_structured") or {}, ensure_ascii=False),
                "ambiguous_columns_json":  json.dumps(entry.get("ambiguous_columns") or [], ensure_ascii=False),
            }

            ids.append(term_id)
            documents.append(embedding_text)
            metadatas.append(metadata)

        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"[TERM_VECTOR_STORE] Indexed {len(ids)} terms")

    def resolve(self, user_query: str) -> TermResolverOutput:
        """
        Kullanıcı sorgusundaki terimleri semantik olarak tespit et.
        Conflict resolution algoritmasını uygula.
        """
        candidates = self._semantic_search(user_query)
        return self._apply_conflict_resolution(candidates, user_query)

    def rebuild_index(self) -> None:
        """Index'i sıfırdan oluştur (dict güncellenince çağır)."""
        self.initialize(force_recreate=True)

    # ------------------------------------------------------------------
    # Internal: search
    # ------------------------------------------------------------------

    def _semantic_search(self, user_query: str) -> List[TermCandidate]:
        """
        ChromaDB semantic query → List[TermCandidate].
        Ayrı metod — testlerde mock'lanabilir.
        """
        if self._collection is None:
            logger.warning("[TERM_VECTOR_STORE] Not initialized, returning empty")
            return []

        results = self._collection.query(
            query_texts=[user_query],
            n_results=min(_TOP_K, self._collection.count() or 1),
        )

        candidates: List[TermCandidate] = []
        for i, term_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            similarity = 1 - distance          # cosine distance → similarity
            if similarity < self.similarity_threshold:
                continue

            meta = results["metadatas"][0][i]
            candidates.append(TermCandidate(
                term_id=term_id,
                category=meta.get("category", ""),
                term=meta.get("term", term_id),
                column=meta.get("column", ""),
                specificity=float(meta.get("specificity", "1.0")),
                hint=meta.get("hint", ""),
                filter_structured=json.loads(meta.get("filter_structured_json", "{}")) or None,
                ambiguous_columns=json.loads(meta.get("ambiguous_columns_json", "[]")),
                similarity=similarity,
            ))

        logger.debug(
            f"[TERM_VECTOR_STORE] Semantic search: {len(candidates)} candidates "
            f"(threshold={self.similarity_threshold})"
        )
        return candidates

    # ------------------------------------------------------------------
    # Internal: conflict resolution
    # ------------------------------------------------------------------

    def _apply_conflict_resolution(
        self,
        candidates: List[TermCandidate],
        user_query: str,
    ) -> TermResolverOutput:
        """
        Conflict resolution algoritması:

        1. Sort by similarity * specificity (desc) — spesifik term'ler önce işlenir
        2. Unambiguous term → resolved_columns'a ekle
        3. Ambiguous term → tüm / kısmen resolved_columns'da mı?
             Tümü veya kısmen → SUPPRESS
             Hiçbiri          → interrupt listesine ekle
        """
        sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)

        resolved_columns: Dict[str, TermCandidate] = {}  # column → winning candidate
        term_filters: List[Dict[str, Any]] = []
        hint_lines: List[str] = []
        ambiguous: List[AmbiguousMatch] = []

        for candidate in sorted_candidates:

            # --- Unambiguous term ---
            if not candidate.is_ambiguous and candidate.column:
                if candidate.column not in resolved_columns:
                    resolved_columns[candidate.column] = candidate
                    hint_lines.append(f'- "{candidate.term}" [{candidate.column}] → {candidate.hint}')
                    if candidate.filter_structured:
                        fs = dict(candidate.filter_structured)
                        fs.setdefault("logical_operator", "AND")
                        term_filters.append(fs)
                    logger.debug(
                        f"[TERM_VECTOR_STORE] Resolved: '{candidate.term}' → "
                        f"'{candidate.column}' (sim={candidate.similarity:.2f}, "
                        f"spec={candidate.specificity})"
                    )
                # else: same column already resolved by higher-priority term → skip
                continue

            # --- Ambiguous term ---
            if candidate.is_ambiguous:
                amb_cols = [c["column"] for c in candidate.ambiguous_columns]
                already_resolved = [c for c in amb_cols if c in resolved_columns]

                if already_resolved:
                    # SUPPRESS: at least one ambiguous column is already resolved
                    for col in already_resolved:
                        winner = resolved_columns[col]
                        hint_lines.append(
                            f'- "{candidate.term}" → "{winner.term}" terimi ile '
                            f'[{col}] olarak çözüldü (interrupt suppressed)'
                        )
                    logger.info(
                        f"[TERM_VECTOR_STORE] SUPPRESS: '{candidate.term}' ambiguity suppressed "
                        f"by {[resolved_columns[c].term for c in already_resolved]}"
                    )
                else:
                    # No column resolved → genuine ambiguity → interrupt needed
                    ambiguous.append(AmbiguousMatch(
                        term=candidate.term,
                        user_query=user_query,
                        options=candidate.ambiguous_columns,
                    ))
                    hint_lines.append(f'- "{candidate.term}" → belirsiz kolon, kullanıcıya sorulacak')
                    logger.info(
                        f"[TERM_VECTOR_STORE] AMBIGUOUS: '{candidate.term}' → "
                        f"interrupt required ({amb_cols})"
                    )

        hints_text = "\n".join(hint_lines) if hint_lines else "Özel terim eşleşmesi bulunamadı."

        logger.info(
            f"[TERM_VECTOR_STORE] resolve() done: "
            f"{len(term_filters)} filter(s), "
            f"{len([l for l in hint_lines if 'belirsiz' not in l])} hint(s), "
            f"{len(ambiguous)} interrupt(s)"
        )
        return TermResolverOutput(
            term_filters=term_filters,
            hints_text=hints_text,
            ambiguous=ambiguous,
        )

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _load_dict(self) -> List[Dict[str, Any]]:
        try:
            with open(self.dict_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("terms", [])
        except Exception as e:
            logger.error(f"[TERM_VECTOR_STORE] Failed to load dict: {e}")
            return []

    @staticmethod
    def _build_embedding_text(entry: Dict[str, Any]) -> str:
        """embedding_text yoksa term + aliases birleştir."""
        parts = [entry["term"]] + entry.get("aliases", [])
        return ", ".join(parts)
