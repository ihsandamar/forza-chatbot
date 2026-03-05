# Longest-Match Alias Fix - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix alias collision in `_keyword_pre_resolve` where short aliases (e.g., "satış") falsely match inside longer aliases (e.g., "satış adedi"), causing wrong column resolution.

**Architecture:** Replace the current entry-order iteration with a longest-match-first approach using consumed-span tracking. All aliases are sorted by length (longest first), matched against the query, and matched spans are marked as consumed. Shorter aliases that overlap consumed spans are skipped.

**Tech Stack:** Python, regex, term_vector_store.py

---

### Task 1: Refactor _keyword_pre_resolve with longest-match-first

**Files:**
- Modify: `src/graphs/report_agent/subagents/text2sql/term_vector_store.py:242-294`

**Step 1: Build sorted alias list at resolve time**

Inside `_keyword_pre_resolve`, before the main loop, collect all eligible aliases with their metadata and sort by alias length descending:

```python
def _keyword_pre_resolve(self, user_query: str) -> Dict[str, "TermCandidate"]:
    if not self._terms_data:
        return {}

    query_lower = user_query.lower()
    pre_resolved: Dict[str, TermCandidate] = {}
    consumed_spans: list[tuple[int, int]] = []

    # Tüm eligible alias'ları topla ve uzunluk sırasına göre sırala
    alias_entries: list[tuple[str, dict]] = []
    for entry in self._terms_data:
        if entry.get("filter_structured") or entry.get("ambiguous_columns"):
            continue
        if not entry.get("column"):
            continue
        for alias in [entry["term"]] + entry.get("aliases", []):
            alias_entries.append((alias.lower(), entry))

    # Uzundan kısaya sırala — longest match first
    alias_entries.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, entry in alias_entries:
        column = entry["column"]
        if column in pre_resolved:
            continue  # bu kolon zaten resolve edildi

        pat = self._keyword_patterns.get(alias)
        if not pat:
            continue

        match = pat.search(query_lower)
        if not match:
            continue

        # Match edilen span consumed mı?
        m_start, m_end = match.start(), match.end()
        if any(cs <= m_start < ce or cs < m_end <= ce for cs, ce in consumed_spans):
            continue  # bu span zaten daha uzun bir alias tarafından tüketildi

        # Pre-resolve et ve span'ı consumed olarak işaretle
        consumed_spans.append((m_start, m_end))
        pre_resolved[column] = TermCandidate(
            term_id=entry["id"],
            category=entry.get("category", ""),
            term=entry["term"],
            column=column,
            specificity=float(entry.get("specificity", 1.0)),
            hint=entry.get("hint", ""),
            filter_structured=None,
            ambiguous_columns=[],
            similarity=1.0,
        )

    if pre_resolved:
        logger.info(
            f"[TERM_VECTOR_STORE] Keyword pre-resolve: {len(pre_resolved)} column(s) → "
            + str({col: cand.term for col, cand in pre_resolved.items()})
        )
    return pre_resolved
```

**Step 2: Verify no other code depends on iteration order**

The return type (`Dict[str, TermCandidate]`) and its consumers remain unchanged. `_apply_conflict_resolution` reads `pre_resolved` by column key, not by insertion order. No other changes needed.

**Step 3: Run diagnostics and verify**

Check for zero errors in the modified file.
