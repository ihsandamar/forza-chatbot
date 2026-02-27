# Keyword Pre-Resolution — Design

**Date:** 2026-02-27
**Status:** Approved

---

## Problem

`metric_ambiguous_how_much` interrupt tetikleniyordu; "ciro" açıkça sorguda bulunmasına rağmen.

**Kök neden:** Threshold=0.75 yükseltmesi, uzun karmaşık sorgularda `metric_revenue`'nun embedding'ini
diğer kelimelerle dilüe ediyor; threshold'u geçemiyor. `metric_ambiguous_how_much` ("ne kadar" paterni
nedeniyle) yine de geçiyor. `resolved_columns["RowAmount"]` hiç set edilmediği için suppress mantığı
körleşiyor ve interrupt zorunlu hale geliyor.

**Genel risk:** Aynı kırılma gelecekte eklenen herhangi bir metric/dimension term için de geçerli.

---

## Çözüm: Keyword Pre-Resolution

### Pipeline Değişikliği

```
# Önceki
resolve() → semantic_search(0.75) → conflict_resolution

# Sonraki
resolve() → keyword_pre_resolve()        ← YENİ
          → semantic_search(0.75)
          → conflict_resolution(pre_resolved)   ← resolved_columns önceden dolu
```

### Kural: Hangi Term'ler Pre-Resolve Edilir

**Dahil:** `filter_structured is None` AND `ambiguous_columns == []` — yani metric + dimension (unambiguous, non-filter) term'ler.

**Hariç:**
- `filter_structured` olan term'ler (`filter_return`, `filter_treat`) — semantic search + `term_validator_node` LLM gate'inden geçmeli; keyword bypass bu güvenlik katmanını atlatmamalı.
- `ambiguous_columns` olan term'ler (`metric_ambiguous_how_much`) — zaten ambiguous, pre-resolve edilemez.

### `_keyword_pre_resolve(user_query)` Algoritması

```python
def _keyword_pre_resolve(self, user_query: str) -> Dict[str, TermCandidate]:
    query_lower = user_query.lower()
    pre_resolved: Dict[str, TermCandidate] = {}

    for entry in self._terms_data:
        # Sadece unambiguous, non-filter term'ler
        if entry.get("filter_structured"):
            continue
        if entry.get("ambiguous_columns"):
            continue
        column = entry.get("column", "")
        if not column:
            continue

        for alias in [entry["term"]] + entry.get("aliases", []):
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
                break

    return pre_resolved
```

**Karmaşıklık:** O(N×M) — N=term sayısı (şu an 14), M=alias sayısı (~5). Çok hızlı.

**Türkçe suffix:** `alias.lower() in query_lower` substring check ile "ciroda", "cirosu" gibi ekli formlar da yakalanır.

### `_apply_conflict_resolution()` Değişikliği

```python
def _apply_conflict_resolution(
    self,
    candidates: List[TermCandidate],
    user_query: str,
    keyword_pre_resolved: Optional[Dict[str, TermCandidate]] = None,
) -> TermResolverOutput:
    resolved_columns = dict(keyword_pre_resolved or {})  # önceden dolu başlıyor

    # Pre-resolved term'lerin hint'lerini column_hint_lines'a ekle
    for col, cand in resolved_columns.items():
        column_hint_lines.append(
            f'- "{cand.term}" [keyword] [{col}] → {cand.hint}'
        )

    # Mevcut loop değişmez:
    # - Unambiguous semantic candidate → column zaten resolved_columns'daysa skip (line 296)
    # - Ambiguous candidate → already_resolved doluysa SUPPRESS ✅
```

### `resolve()` Değişikliği

```python
def resolve(self, user_query: str) -> TermResolverOutput:
    keyword_pre_resolved = self._keyword_pre_resolve(user_query)  # YENİ
    candidates = self._semantic_search(user_query)
    return self._apply_conflict_resolution(candidates, user_query, keyword_pre_resolved)
```

---

## Senaryo Tablosu

| Sorgu | Davranış |
|---|---|
| "ne kadar ciro yaptı" | "ciro" keyword → pre-resolve RowAmount → suppress ✅ |
| "kaç adet sattı" | "adet" keyword → pre-resolve Quantity → suppress ✅ |
| "ne kadar sattı" (explicit metric yok) | pre_resolved={} → interrupt doğru tetiklenir ✅ |
| "ne kadar ciro ve adet sattı" | her ikisi pre-resolve → ambiguous için both_resolved → suppress ✅ |
| "iade satışların toplamı" | "iade" filter_structured var → skip keyword, semantic+LLM ✅ |
| Yeni term eklenince | aliases'e girer → otomatik çalışır ✅ (genel mimari) |

---

## Etkilenen Dosyalar

**Sadece 1 dosya:** `term_vector_store.py`

1. `_keyword_pre_resolve()` — yeni metod (~30 satır)
2. `resolve()` — 2 satır değişiklik
3. `_apply_conflict_resolution()` — signature + başlangıç bölümü (~10 satır)

**Değişmeyen dosyalar:** `nodes.py`, `graph.py`, `state.py`, `prompts.py`, `term_dictionary.json`

---

## Logging

```
[TERM_VECTOR_STORE] Keyword pre-resolve: 1 column(s) → {'RowAmount': 'ciro'}
[TERM_VECTOR_STORE] SUPPRESS: 'ne kadar sattı' suppressed by ['ciro']
```
