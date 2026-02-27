# Keyword Pre-Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `TermVectorStore.resolve()` içine keyword pre-resolution adımı ekleyerek, uzun sorgularda semantic threshold'u geçemeyen unambiguous term'lerin suppress mekanizmasını besleyememesi sorununu ortadan kaldırmak.

**Architecture:** `resolve()` içinde semantic search'ten önce `_keyword_pre_resolve()` çağrılır; `term` + `aliases` substring match ile unambiguous/non-filter term'ler tespit edilir ve `resolved_columns` önceden doldurulur. Mevcut suppress mantığı (`if already_resolved: SUPPRESS`) değişmez, sadece güvenilir biçimde beslenmiş olur.

**Tech Stack:** Python, dataclasses — tek dosya değişikliği, yeni bağımlılık yok.

**Design doc:** `docs/plans/2026-02-27-keyword-pre-resolution-design.md`

---

### Task 1: `_keyword_pre_resolve()` metodu + `resolve()` entegrasyonu

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py:206-217` (`resolve()` ve `_apply_conflict_resolution()`)

**Bağlam:**
- `resolve()` şu an: `candidates = _semantic_search(...)` → `_apply_conflict_resolution(candidates, user_query)`
- `_apply_conflict_resolution()` line 285: `resolved_columns: Dict[str, TermCandidate] = {}`  — boş başlıyor
- Keyword pre-resolution bu dict'i semantic search'ten önce doldurur

**Adım 1: `_keyword_pre_resolve()` metodunu ekle**

`rebuild_index()` metodunun hemen altına (line 217, `# Internal: search` bloğunun üstüne) ekle:

```python
# ------------------------------------------------------------------
# Internal: keyword pre-resolution
# ------------------------------------------------------------------

def _keyword_pre_resolve(self, user_query: str) -> Dict[str, "TermCandidate"]:
    """
    Threshold'dan bağımsız keyword/alias match ile unambiguous non-filter
    term'leri önceden çözer.

    Dahil: metric + dimension term'ler (filter_structured=None, ambiguous_columns=[])
    Hariç: filter term'ler (filter_structured var) → semantic + term_validator LLM gate yeter
    Hariç: ambiguous term'ler (ambiguous_columns var) → zaten belirsiz

    Returns: {column: TermCandidate} — resolved_columns için başlangıç değeri
    """
    if not self._terms_data:
        return {}

    query_lower = user_query.lower()
    pre_resolved: Dict[str, TermCandidate] = {}

    for entry in self._terms_data:
        # filter term'leri atla — semantic + LLM validator yeterli
        if entry.get("filter_structured"):
            continue
        # ambiguous term'leri atla — zaten belirsiz, pre-resolve edilemez
        if entry.get("ambiguous_columns"):
            continue

        column = entry.get("column", "")
        if not column:
            continue

        aliases_to_check = [entry["term"]] + entry.get("aliases", [])
        for alias in aliases_to_check:
            if alias.lower() in query_lower:
                if column not in pre_resolved:  # ilk eşleşen kazanır
                    pre_resolved[column] = TermCandidate(
                        term_id=entry["id"],
                        category=entry.get("category", ""),
                        term=entry["term"],
                        column=column,
                        specificity=float(entry.get("specificity", 1.0)),
                        hint=entry.get("hint", ""),
                        filter_structured=None,
                        ambiguous_columns=[],
                        similarity=1.0,  # keyword match = mükemmel eşleşme
                    )
                break  # ilk alias eşleşti, sonrakine geç

    if pre_resolved:
        logger.info(
            f"[TERM_VECTOR_STORE] Keyword pre-resolve: {len(pre_resolved)} column(s) → "
            + str({col: cand.term for col, cand in pre_resolved.items()})
        )
    return pre_resolved
```

**Adım 2: `resolve()` metodunu güncelle (line 206-212)**

Mevcut kodu:
```python
def resolve(self, user_query: str) -> TermResolverOutput:
    """
    Kullanıcı sorgusundaki terimleri semantik olarak tespit et.
    Conflict resolution algoritmasını uygula.
    """
    candidates = self._semantic_search(user_query)
    return self._apply_conflict_resolution(candidates, user_query)
```

Şununla değiştir:
```python
def resolve(self, user_query: str) -> TermResolverOutput:
    """
    Kullanıcı sorgusundaki terimleri semantik olarak tespit et.
    Conflict resolution algoritmasını uygula.

    Pipeline:
      1. keyword_pre_resolve  — threshold'dan bağımsız alias match (unambiguous non-filter)
      2. semantic_search      — ChromaDB cosine similarity (threshold=0.75)
      3. conflict_resolution  — pre_resolved ile beslenmiş suppress zinciri
    """
    keyword_pre_resolved = self._keyword_pre_resolve(user_query)
    candidates = self._semantic_search(user_query)
    return self._apply_conflict_resolution(candidates, user_query, keyword_pre_resolved)
```

**Adım 3: `_apply_conflict_resolution()` signature'ını ve başlangıcını güncelle (line 266-290)**

Mevcut signature:
```python
def _apply_conflict_resolution(
    self,
    candidates: List[TermCandidate],
    user_query: str,
) -> TermResolverOutput:
    """
    Conflict resolution algoritması:

    1. Sort by similarity * specificity (desc) — spesifik term'ler önce işlenir
    2. Unambiguous term → resolved_columns'a ekle
       - filter_structured varsa → term_filters + candidate_filter_terms (filter_hint_lines)
       - yoksa → column_hint_lines (LLM hint)
    3. Ambiguous term → tüm / kısmen resolved_columns'da mı?
         Tümü veya kısmen → SUPPRESS
         Hiçbiri          → interrupt listesine ekle
    4. hints_text iki bölümlü: PYTHON-YÖNETİMLİ FİLTRELER + KOLON İPUÇLARI
    """
    sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)

    resolved_columns: Dict[str, TermCandidate] = {}  # column → winning candidate
    term_filters: List[Dict[str, Any]] = []
    candidate_filter_terms: List[Dict[str, Any]] = []
    filter_hint_lines: List[str] = []    # Python-managed filter hints
    column_hint_lines: List[str] = []    # Metric/dimension hints for LLM
    ambiguous: List[AmbiguousMatch] = []
```

Şununla değiştir:
```python
def _apply_conflict_resolution(
    self,
    candidates: List[TermCandidate],
    user_query: str,
    keyword_pre_resolved: Optional[Dict[str, "TermCandidate"]] = None,
) -> TermResolverOutput:
    """
    Conflict resolution algoritması:

    0. keyword_pre_resolved ile resolved_columns önceden doldurulur (YENİ)
    1. Sort by similarity * specificity (desc) — spesifik term'ler önce işlenir
    2. Unambiguous term → resolved_columns'a ekle
       - filter_structured varsa → term_filters + candidate_filter_terms (filter_hint_lines)
       - yoksa → column_hint_lines (LLM hint)
    3. Ambiguous term → tüm / kısmen resolved_columns'da mı?
         Tümü veya kısmen → SUPPRESS
         Hiçbiri          → interrupt listesine ekle
    4. hints_text iki bölümlü: PYTHON-YÖNETİMLİ FİLTRELER + KOLON İPUÇLARI
    """
    sorted_candidates = sorted(candidates, key=lambda c: c.sort_key, reverse=True)

    # Keyword pre-resolved term'lerle başla — suppress zinciri için önceden beslenmiş
    resolved_columns: Dict[str, TermCandidate] = dict(keyword_pre_resolved or {})
    term_filters: List[Dict[str, Any]] = []
    candidate_filter_terms: List[Dict[str, Any]] = []
    filter_hint_lines: List[str] = []    # Python-managed filter hints
    # Pre-resolved keyword term'lerinin hint'lerini KOLON İPUÇLARI'na ekle
    column_hint_lines: List[str] = [
        f'- "{cand.term}" (keyword) [{col}] → {cand.hint}'
        for col, cand in resolved_columns.items()
    ]
    ambiguous: List[AmbiguousMatch] = []
```

**Adım 4: Syntax kontrolü**

```bash
python -m py_compile src/graphs/report_agent/subagents/text2sql/term_vector_store.py && echo "OK"
```

Beklenen: `OK`

**Adım 5: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/term_vector_store.py
git commit -m "feat(term-resolver): add keyword pre-resolution to fix suppress mechanism for long queries"
```

---

### Task 2: Manuel doğrulama

Sunucuyu başlat ve test et:

```bash
langgraph dev
```

**Test sorgusu:** "Son 1 senede ödemesi alınan masalarda en çok hangi ürün ne kadar ciro yaptı"

**Beklenen log satırları (sırayla):**
```
[TERM_VECTOR_STORE] Keyword pre-resolve: 1 column(s) → {'RowAmount': 'ciro'}
[TERM_VECTOR_STORE] SUPPRESS: 'ne kadar sattı' suppressed by ['ciro']
[TERM_RESOLVER] 0 term_filter(s), 0 metric choice(s)
```

**Beklenen davranış:** Kolon soru interrupt'ı ATILAMAZ.

**Kontrol test sorgusu (interrupt hâlâ çalışmalı):**
"Son 1 ayda ne kadar sattı?" (explicit metric yok)

**Beklenen:** Interrupt tetiklenir ✅ (doğru davranış)
