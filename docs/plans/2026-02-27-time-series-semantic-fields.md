# TIME_SERIES_COMPARISON Semantik Alan Mimarisi

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `QuerySchema`'ya `time_granularity` ve `comparison_dimension` semantik alanları ekleyerek LLM'in GROUP BY inşa sorumluluğunu kaldır; Python deterministik olarak doğru SQL expression'larını üretsin.

**Architecture:** LLM artık semantik seçim yapıyor ("daily", "ProductName"), Python bunu deterministik SQL'e çeviriyor. Ek savunma: LLM alanları boş bırakırsa Türkçe keyword root matching fallback devreye giriyor.

**Tech Stack:** Python, Pydantic BaseModel, LangGraph, T-SQL (SQL Server)

**Affected Files:**
- `src/graphs/report_agent/subagents/text2sql/prompts.py` — QuerySchema + SQL_ARCHITECT_PROMPT
- `src/graphs/report_agent/subagents/text2sql/nodes.py` — sql_generator_node safety net 3
- `src/graphs/generic_text2sql/prompts.py` — SQL_ARCHITECT_PROMPT senkronizasyon

---

## Mimari Sorun

`QuerySchema.group_by: List[str]` düz listesine LLM hem zaman ifadelerini
(`CAST(DocumentDate AS DATE)`) hem entity kolonlarını (`ProductName`) koymak zorunda.
LLM tutarsız davranıyor — özellikle "X kategorisindeki **ürünleri** karşılaştır"
kalıbında entity dimension sürekli atlıyor. 3+ prompt fix denendi, kök neden çözülmedi.

**Çözüm:** LLM'e basit semantik seçimler sor, Python deterministik çeviri yapsın.

```
Eski: LLM → group_by: ["CAST(DocumentDate AS DATE)"]   # ProductName unutuldu

Yeni: LLM → time_granularity: "daily"
             comparison_dimension: "ProductName"
     Python → group_by: ["ProductName", "CAST(DocumentDate AS DATE)"]  # deterministik
```

---

## Task 1: QuerySchema'ya Semantik Alanlar Ekle

**File:** `src/graphs/report_agent/subagents/text2sql/prompts.py`

**Mevcut durum (satır 96-99):**
```python
group_by:           List[str]
order_by_column:    Optional[str] = None
order_by_direction: Literal["ASC", "DESC"] = "DESC"
limit:              Optional[int] = None
```

**Step 1: `QuerySchema`'ya iki yeni alan ekle (group_by'dan SONRA)**

```python
group_by:             List[str]
time_granularity:     Optional[Literal["hourly", "daily", "weekly", "monthly", "yearly"]] = None
comparison_dimension: Optional[str] = None   # DB kolon adı: "ProductName", "BranchName" vb.
order_by_column:      Optional[str] = None
order_by_direction:   Literal["ASC", "DESC"] = "DESC"
limit:                Optional[int] = None
```

**Neden backward-compatible:** İki alan da `Optional` + default `None`. Mevcut LLM çağrıları / test verileri bozulmaz.

**Step 2: SQL_ARCHITECT_PROMPT'a yeni kural ekle**

`### KURAL 5 — Periyodik Gruplama` bölümünün HEMEN ÖNCESİNE (mevcut satır ~318) ekle:

```
### KURAL 4.8 — TIME_SERIES_COMPARISON: Semantik Alan Dolumu (KRİTİK)
query_type = "TIME_SERIES_COMPARISON" olduğunda MUTLAKA doldur:

**time_granularity** — Zaman granülaritesi (sadece bu değerlerden biri):
  "saatlik", "saat saat", "her saat"  → "hourly"
  "günlük", "her gün", "gün bazında" → "daily"
  "haftalık", "her hafta"             → "weekly"
  "aylık", "her ay", "ay bazında"    → "monthly"
  "yıllık", "her yıl", "yıl bazında" → "yearly"

**comparison_dimension** — Karşılaştırılan entity'nin DB kolon adı:
  "ürünleri", "ürünlere göre", "ürün bazında"         → "ProductName"
  "şubeleri", "şubelere göre", "şube bazında"          → "BranchName"
  "kategorileri", "kategorilere göre"                   → "CategoryName"
  "müşterileri", "carileri", "müşterilere göre"        → "CustomerName"
  "kasiyerleri", "kasiyerlere göre"                    → "CashierName"
  "şehirleri", "şehirlere göre", "şehir bazında"      → "BranchCityName"
  "kanalları", "kanallar bazında", "satış kanallarını" → "DocumentKindName"
  Eğer sadece zaman kırılımı istiyorsa (entity yok)   → null

**group_by** — Python bu alanları kullanarak inşa eder, SEN BOŞ BIRAKIP BIRAKMA FARK ETMEZ.
  Ancak doldurursan Python ile çelişme: zaman ifadeleri Python ekler, ham DocumentDate KOYMA.

ÖRNEK ✅:
  "dürümler kategorisindeki ürünleri günlük ciro olarak karşılaştır"
  → time_granularity: "daily"
  → comparison_dimension: "ProductName"
  → filters: [CategoryName = "dürümler"]
  → group_by: []  veya ["ProductName", "CAST(DocumentDate AS DATE)"]

ÖRNEK ✅:
  "son 1 yılda aylık satış trendi"
  → time_granularity: "monthly"
  → comparison_dimension: null  (entity yok, sadece zaman kırılımı)
  → group_by: []  veya ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]

ÖRNEK ✅:
  "Ankara şubesindeki kategorileri haftalık karşılaştır"
  → time_granularity: "weekly"
  → comparison_dimension: "CategoryName"
  → filters: [BranchName = "Ankara"]
```

**Step 3: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/prompts.py
git commit -m "feat(schema): add time_granularity + comparison_dimension to QuerySchema"
```

---

## Task 2: sql_generator_node Safety Net 3'ü Yeniden Yaz

**File:** `src/graphs/report_agent/subagents/text2sql/nodes.py`

Mevcut safety net 3 (`# --- TIME_SERIES_COMPARISON güvenlik ağı ---` bloğu, ~satır 754-789) tümüyle değiştirilecek.

**Step 1: Mevcut safety net 3 bloğunu sil ve yeni kodla değiştir**

Silinecek blok (mevcut):
```python
        # --- TIME_SERIES_COMPARISON güvenlik ağı: GROUP BY'da zaman granülaritesi olmalı ---
        # LLM granülariteyi (haftalık, günlük vb.) group_by'a eklemezse Python düzeltir.
        if state.get("query_type") == "TIME_SERIES_COMPARISON":
            _ts_group_by = raw_schema.get("group_by", [])
            _time_inds = ("YEAR(", "MONTH(", "CAST(", "DATEPART(", "HOUR")
            _has_time = any(
                any(_ind in _col.upper() for _ind in _time_inds)
                for _col in _ts_group_by
            )
            if not _has_time:
                _q = (state.get("user_query") or "").lower()
                if any(_k in _q for _k in ("saatlik", "her saat", "saat saat", "saate göre", "saat bazında")):
                    _t_cols = ["CAST(DocumentDate AS DATE)", "Hour"]
                elif any(_k in _q for _k in ("haftalık", "her hafta", "hafta hafta", "haftalara göre", "hafta bazında")):
                    _t_cols = ["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"]
                elif any(_k in _q for _k in ("aylık", "her ay", "ay ay", "aylara göre", "ay bazında")):
                    _t_cols = ["YEAR(DocumentDate)", "MONTH(DocumentDate)"]
                elif any(_k in _q for _k in ("yıllık", "her yıl", "yıl yıl", "yıllara göre", "yıl bazında")):
                    _t_cols = ["YEAR(DocumentDate)"]
                elif any(_k in _q for _k in ("günlük", "her gün", "gün gün", "günlere göre", "gün bazında")):
                    _t_cols = ["CAST(DocumentDate AS DATE)"]
                else:
                    _t_cols = []
                if _t_cols:
                    # Ham DocumentDate/Date kolonlarını çıkar — CAST(DocumentDate AS DATE)
                    # zaten onların yerine geçiyor; ikisi birden GROUP BY'da olursa
                    # her satır ayrı grup olur (per-transaction grouping hatası).
                    _raw_date_cols = {"DocumentDate", "Date"}
                    _ts_group_by_clean = [
                        _col for _col in _ts_group_by if _col not in _raw_date_cols
                    ]
                    raw_schema = {**raw_schema, "group_by": _t_cols + _ts_group_by_clean}
                    logger.warning(
                        f"[SQL_GENERATOR] TIME_SERIES: zaman granülaritesi eksik → eklendi: {_t_cols}, "
                        f"ham tarih kolonları çıkarıldı: {[c for c in _ts_group_by if c in _raw_date_cols]}"
                    )
```

Yerine yazılacak yeni blok:

```python
        # --- TIME_SERIES_COMPARISON güvenlik ağı: semantik alanlardan GROUP BY inşa et ---
        # LLM time_granularity + comparison_dimension doldurursa Python deterministik çevirir.
        # Doldurmadıysa fallback: kullanıcı query'sinden keyword matching ile tespit.
        if state.get("query_type") == "TIME_SERIES_COMPARISON":
            # Zaman granülaritesi → SQL ifadeleri tablosu
            _TIME_GRAN_MAP: dict = {
                "hourly":  ["CAST(DocumentDate AS DATE)", "Hour"],
                "daily":   ["CAST(DocumentDate AS DATE)"],
                "weekly":  ["YEAR(DocumentDate)", "DATEPART(WEEK, DocumentDate)"],
                "monthly": ["YEAR(DocumentDate)", "MONTH(DocumentDate)"],
                "yearly":  ["YEAR(DocumentDate)"],
            }
            # Entity keyword root → DB kolon adı (Türkçe kök eşleştirme — fallback için)
            _ENTITY_ROOTS: dict = {
                "ürün":     "ProductName",
                "şube":     "BranchName",
                "kategori": "CategoryName",
                "müşteri":  "CustomerName",
                "cari":     "CustomerName",
                "kasiyer":  "CashierName",
                "şehir":    "BranchCityName",
                "kanal":    "DocumentKindName",
                "kurye":    "DeliveryUserName",
                "masa":     "TableNo",
            }

            # --- Option A: Semantik alanlardan değerleri al ---
            _time_gran    = raw_schema.get("time_granularity")
            _comp_dim     = raw_schema.get("comparison_dimension")

            # --- Option B fallback: LLM alanları boş bıraktıysa query'den tespit ---
            _q_lower = (state.get("user_query") or "").lower()

            if not _time_gran:
                if any(_k in _q_lower for _k in ("saatlik", "her saat", "saat saat", "saat bazında")):
                    _time_gran = "hourly"
                elif any(_k in _q_lower for _k in ("haftalık", "her hafta", "hafta hafta", "hafta bazında")):
                    _time_gran = "weekly"
                elif any(_k in _q_lower for _k in ("aylık", "her ay", "ay ay", "ay bazında")):
                    _time_gran = "monthly"
                elif any(_k in _q_lower for _k in ("yıllık", "her yıl", "yıl yıl", "yıl bazında")):
                    _time_gran = "yearly"
                elif any(_k in _q_lower for _k in ("günlük", "her gün", "gün gün", "gün bazında")):
                    _time_gran = "daily"
                if _time_gran:
                    logger.warning(f"[SQL_GENERATOR] TIME_SERIES: time_granularity keyword fallback: {_time_gran}")

            if not _comp_dim:
                for _root, _col in _ENTITY_ROOTS.items():
                    if _root in _q_lower:
                        _comp_dim = _col
                        logger.warning(f"[SQL_GENERATOR] TIME_SERIES: comparison_dimension keyword fallback: {_root}→{_col}")
                        break

            # --- GROUP BY inşası ---
            if _time_gran or _comp_dim:
                _t_cols     = _TIME_GRAN_MAP.get(_time_gran, []) if _time_gran else []
                _raw_dates  = {"DocumentDate", "Date"}
                # Mevcut group_by'dan ham tarih kolonlarını çıkar, zaman ve entity ifadelerini ekle
                _existing   = [_c for _c in raw_schema.get("group_by", []) if _c not in _raw_dates]
                _time_set   = set(_t_cols)
                # entity: mevcut group_by'da zaten varsa çift ekleme
                _has_comp   = _comp_dim and _comp_dim in _existing
                _new_group_by: list = []
                if _comp_dim and not _has_comp:
                    _new_group_by.append(_comp_dim)
                _new_group_by.extend(_t_cols)
                # Mevcut group_by'dan zaman ifadeleri + entity dışındaki kolonları koru
                for _c in _existing:
                    if _c not in _time_set and _c != _comp_dim:
                        _new_group_by.append(_c)
                raw_schema = {**raw_schema, "group_by": _new_group_by}
                logger.info(
                    f"[SQL_GENERATOR] TIME_SERIES group_by inşa edildi: "
                    f"entity={_comp_dim}, gran={_time_gran}, result={_new_group_by}"
                )
```

**Step 2: Commit**

```bash
git add src/graphs/report_agent/subagents/text2sql/nodes.py
git commit -m "feat(nodes): rebuild TIME_SERIES safety net with semantic fields + keyword fallback"
```

---

## Task 3: generic_text2sql/prompts.py Senkronizasyonu

**File:** `src/graphs/generic_text2sql/prompts.py`

Bu dosya `report_agent` tarafından doğrudan kullanılmıyor (report_agent kendi `subagents/text2sql/prompts.py`'sini kullanıyor), ancak generic_text2sql pipeline'ı kullanan başka agent'lar için tutarlılık sağlanmalı.

**Step 1:** `src/graphs/generic_text2sql/prompts.py` içinde `COMPARISON ILE KOMBINE OLURSA` bölümünü bul (satır ~891), aynı TIME_SERIES semantik alan açıklamasını ekle:

```
**TIME_SERIES_COMPARISON için time_granularity + comparison_dimension alanları:**
Bunlar QuerySchema'nın opsiyonel alanlarıdır — doldurmak GROUP BY kalitesini artırır.
  time_granularity: "hourly" | "daily" | "weekly" | "monthly" | "yearly"
  comparison_dimension: karşılaştırılan entity'nin DB kolon adı (ProductName, BranchName vb.)
```

**Step 2: Commit**

```bash
git add src/graphs/generic_text2sql/prompts.py
git commit -m "docs(prompts): sync time_granularity/comparison_dimension docs to generic_text2sql"
```

---

## Task 4: Push

```bash
git push
```

---

## Doğrulama: Beklenen Davranış

### Test 1 — "dürümler kategorisindeki ürünleri günlük ciro olarak karşılaştır"

**LLM çıktısı (ideal):**
```json
{
  "time_granularity": "daily",
  "comparison_dimension": "ProductName",
  "group_by": [],
  "filters": [{"column": "CategoryName", "value_hint": "dürümler"}]
}
```

**Python sonrası group_by:** `["ProductName", "CAST(DocumentDate AS DATE)"]`

**Beklenen SQL:**
```sql
SELECT [ProductName],
       CAST(DocumentDate AS DATE),
       SUM(CASE WHEN [DocumentTypeIsReturn] = 1 THEN -[RowAmount] ELSE [RowAmount] END) AS [ToplamCiro]
FROM [MasterReportDocumentTable]
WHERE [CategoryName] = 'DURUMLER'
  AND [DocumentDate] >= DATEADD(YEAR, -1, '2026-02-27')
GROUP BY [ProductName], CAST(DocumentDate AS DATE)
ORDER BY CAST(DocumentDate AS DATE) ASC
```

### Test 2 — Fallback: LLM alanları boş bırakırsa

**LLM çıktısı (alanlar boş):**
```json
{"time_granularity": null, "comparison_dimension": null, "group_by": []}
```

**Keyword fallback:** "günlük" → `daily`, "ürün" kökü → `ProductName`
**Python sonrası group_by:** `["ProductName", "CAST(DocumentDate AS DATE)"]` — aynı sonuç ✓

### Test 3 — Haftalık, entity yok: "son 1 yılda aylık satış trendi"

**LLM çıktısı:**
```json
{"time_granularity": "monthly", "comparison_dimension": null}
```

**Python sonrası group_by:** `["YEAR(DocumentDate)", "MONTH(DocumentDate)"]` ✓

---

## Değişmeyenler

- `sql_builder.py` — değişmez; `_build_select_parts` zaten `group_by`'ı SELECT'e ekliyor
- `state.py` — değişmez; `query_schema` dict olarak taşınıyor, yeni Pydantic alanlar otomatik geçer
- Diğer query type'lar (COMPARISON, LISTING, RANKING, SINGLE) — hiç etkilenmez
- Mevcut COMPARISON safety net'leri — korunur
