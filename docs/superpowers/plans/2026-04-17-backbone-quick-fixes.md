# Backbone Quick Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** İki bağımsız omurga sorununu temizle: stale test (pytest collection'ı kırıyor) ve dead code (eski BaseGraph dosyası).

**Architecture:** Sadece silme işlemleri — hiçbir davranış değişmez, sadece karışıklık ortadan kalkar.

**Tech Stack:** Python, pytest

---

### Task 1: Stale Test Dosyasını Sil

**Files:**
- Delete: `tests/graphs/report/test_enhanced_hitl.py`

`test_enhanced_hitl.py` var olmayan modülleri import ediyor:
- `src.graphs.report.ambiguity_framework` → `src.graphs.report` modülü yok (doğrusu `src.graphs.report_agent`)
- `src.graphs.report.ambiguity_detectors`
- `src.graphs.report.hitl_question_builder`

Bu modüller projede hiçbir yerde mevcut değil — test tamamen stale.

- [ ] **Step 1: Doğrula — dosyanın gerçekten broken olduğunu teyit et**

```bash
python -m pytest tests/graphs/report/test_enhanced_hitl.py --collect-only 2>&1 | head -20
```

Beklenen çıktı:
```
ModuleNotFoundError: No module named 'src.graphs.report'
```

- [ ] **Step 2: Dosyayı sil**

```bash
rm tests/graphs/report/test_enhanced_hitl.py
```

- [ ] **Step 3: Pytest collection hatasız tamamlanıyor mu?**

```bash
python -m pytest --collect-only -q 2>&1 | tail -5
```

Beklenen çıktı (`ERROR` satırı yok):
```
368 tests collected in X.XXs
```

- [ ] **Step 4: Commit**

```bash
git add -u tests/graphs/report/test_enhanced_hitl.py
git commit -m "test: delete stale test_enhanced_hitl (references non-existent modules)"
```

---

### Task 2: Dead BaseGraph Dosyasını Sil

**Files:**
- Delete: `src/graphs/base_graph.py`

`src/graphs/base_graph.py` projenin ilk versiyonundan kalan basit bir `BaseGraph` implementasyonu. Hiçbir dosya tarafından import edilmiyor — tüm graph'lar `src/graphs/base/base_graph.py` kullanıyor.

- [ ] **Step 1: Import'ların gerçekten olmadığını doğrula**

```bash
grep -r "from src.graphs.base_graph" src/ tests/ --include="*.py"
grep -r "import src.graphs.base_graph" src/ tests/ --include="*.py"
```

Beklenen çıktı: boş (hiçbir match yok)

- [ ] **Step 2: Dosyayı sil**

```bash
rm src/graphs/base_graph.py
```

- [ ] **Step 3: Import hatası olmadığını doğrula**

```bash
python -m pytest --collect-only -q 2>&1 | tail -5
```

Beklenen: collection başarılı, hata yok.

- [ ] **Step 4: Commit**

```bash
git add -u src/graphs/base_graph.py
git commit -m "refactor: delete dead src/graphs/base_graph.py (unused, superseded by base/base_graph.py)"
```
