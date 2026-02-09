# 🎯 Multi-Agent Raporlama Sistemi - Refactoring & İyileştirme Planı

**Proje Tarihi:** 2026-01-09
**Amaç:** Sistemin performansını, doğruluğunu ve stabiliteyi artırmak
**Beklenen Sonuç:** Hızlı, güvenilir ve conversational rapor üretimi

---

## 📋 İçindekiler

1. [Fase 1: Mimari & Tasarım Değişiklikleri](#fase-1-mimari--tasarım-değişiklikleri)
2. [Fase 2: Kritik Hatalar & İstisnalar](#fase-2-kritik-hatalar--istisnalar)
3. [Fase 3: SQL, NLP & Bağlam Iyileştirmeleri](#fase-3-sql-nlp--bağlam-iyileştirmeleri)
4. [Fase 4: Görselleştirme & Sunum](#fase-4-görselleştirme--sunum)
5. [Fase 5: Performans & Optimizasyon](#fase-5-performans--optimizasyon)
6. [Test & Doğrulama](#test--doğrulama)

---

## 🏗️ FASE 1: Mimari & Tasarım Değişiklikleri

### 1.1 Multi-Agent Raporlama Yapısı
**Problem:** Raporlama tek bir graph'ta tüm işleri yapıyor → karmaşık, hata-prone, ölçeklenemiyor
**Çözüm:** Raporlama alt-orkestrasyonu ile Sub-Agent mimarisi

#### Adımlar:
- [ ] **1.1.1** - Sub-Agent yapısını tasarla
  - `ReportSupervisor`: Süreci yönet, aracıları koordine et
  - `IntentAnalyzer`: Query parametrelerini çıkar (tablo, grafik tipi, format)
  - `SQLExecutor`: SQL oluştur ve çalıştır
  - `Visualizer`: Sonuçları görselleştir
  - `OutputFormatter`: Çıktıyı hazırla

- [ ] **1.1.2** - Her agent için ayrı state definition yap
  ```python
  # Yeni dosyalar gerekli:
  - src/graphs/report_supervisor/state.py
  - src/graphs/report_supervisor/nodes/
    - intent_analyzer_node.py
    - orchestrator_node.py
  ```

- [ ] **1.1.3** - ReportSupervisor graph'ını oluştur
  ```
  START → intent_analyzer → sql_executor → decision_node
              ↓
         data_visualization? (Condition)
              ├─ YES → visualizer → output_formatter → END
              └─ NO  → text_formatter → output_formatter → END
  ```

#### Bağımlılıklar:
- Yapı değişince, mevcut report graph'a compatibility wrapper ekle
- Yeni state'lerde `retry_count`, `error_history` ekle

---

### 1.2 Konfigürasyon Yönetimi (Runtime Dynamic)
**Problem:** Tablo adı, kolonlar, kurallar hard-coded
**Çözüm:** `AssistantConfiguration` üzerinden dinamik yükleme

#### Adımlar:
- [ ] **1.2.1** - Configuration schema oluştur
  ```yaml
  # config.yaml yapısı
  report_config:
    default_table: "MasterReportDocumentTable"
    visualization_enabled: true
    cache_enabled: true
    max_rows: 10000
    timeout_seconds: 20
  ```

- [ ] **1.2.2** - Config loader implement et
  ```python
  class ReportConfiguration(AssistantConfiguration):
      table_name: str = "MasterReportDocumentTable"
      visualization_enabled: bool = True
      cache_enabled: bool = True
  ```

- [ ] **1.2.3** - Tüm hardcoded değerleri konfigürasyon'dan oku

#### Bağımlılıklar:
- SQL node'lardaki tablo adını config'den al
- Visualization decision'ı config'den kontrol et

---

### 1.3 Akış Kontrolü - Gereksiz Graph'ları Skip Et
**Problem:** Veri yoksa veya metin dönecekse, visualizasyon graph'ı yine de çalışıyor
**Çözüm:** Intent Analyzer'ın kararına göre rota değiştir

#### Adımlar:
- [ ] **1.3.1** - IntentAnalyzer'a format ve viz gereksinimi output ekle
  ```python
  class IntentAnalyzerOutput(TypedDict):
      query_type: Literal["text", "visualization", "hybrid"]
      table_name: str
      filters: List[Dict]
      needs_visualization: bool  # ← YENI
      output_format: Literal["text", "json", "html", "excel"]
  ```

- [ ] **1.3.2** - Conditional edge'leri güncelle
  ```python
  if output["needs_visualization"] == False:
      route → text_formatter
  else:
      route → visualizer
  ```

- [ ] **1.3.3** - Boş data kontrolü
  ```python
  if results is None or len(results) == 0:
      needs_visualization = False  # Skip viz
  ```

#### Bağımlılıklar:
- `check_results_node` bu kararı yönetsin

---

### 1.4 HTML Temizliği
**Problem:** Response'da HTML tag'ları kalıyor
**Çözüm:** Output formatter'da HTML strip'i implement et

#### Adımlar:
- [ ] **1.4.1** - OutputFormatter node'u oluştur
  ```python
  def strip_html(text: str) -> str:
      # BeautifulSoup veya regex ile HTML temizle
      pass
  ```

- [ ] **1.4.2** - Tüm message'larda HTML temizle
  ```python
  from html.parser import HTMLParser
  # veya
  import re
  response = re.sub(r'<[^>]+>', '', response)
  ```

#### Bağımlılıklar:
- `response_builder_node` bu işi yapsın

---

## 🐛 FASE 2: Kritik Hatalar & İstisnalar

### 2.1 Boş Data Yönetimi
**Problem:** `results = []` geldiğinde crash / hata
**Çözüm:** Graceful handling + user-friendly mesaj

#### Adımlar:
- [ ] **2.1.1** - State'lerde null checks ekle
  ```python
  if not results or len(results) == 0:
      state["no_records_message"] = "Sorguya uygun kayıt bulunamadı."
      state["results"] = []
      return state  # ← Crash değil
  ```

- [ ] **2.1.2** - Visualization graph'ında empty data handling
  ```python
  # state_transformer.py
  if not results:
      logger.info("Empty results - skipping visualization")
      return DataVisualizationState(
          raw_data=[],
          error=None  # ← NOT an error
      )
  ```

- [ ] **2.1.3** - Response builder'da mesaj göster
  ```python
  if no_records_message:
      return AIMessage(f"ℹ️ {no_records_message}")
  ```

#### Test Cases:
- Sorgu sonuç döndermediğinde graceful mesaj
- Pagination ile boş sayfa kontrolü
- Aggregate query'de 0 satır

#### Bağımlılıklar:
- `GenericText2SQLState` ve `ReportState`'de `no_records_message` field

---

### 2.2 SQL Hata Toleransı & Self-Correction
**Problem:** Yanlış SQL yazıldığında sistem pes ediyor
**Çözüm:** SQL error → LLM'e geri gönder → düzeltilmiş query

#### Adımlar:
- [ ] **2.2.1** - Retry mekanizması implement et
  ```python
  # sql_executor_node_with_retry
  MAX_RETRIES = 2

  try:
      results = execute_sql(query)
  except SQLError as e:
      if retry_count < MAX_RETRIES:
          state["sql_error"] = str(e)
          state["retry_count"] += 1
          return {"error": "SQL_RETRY_NEEDED"}  # ← Route back to generator
      else:
          state["error"] = f"SQL failed after {MAX_RETRIES} retries"
  ```

- [ ] **2.2.2** - SQL Generator'ı error handle etmeye yönet
  ```python
  # sql_query_builder_node
  if state.get("sql_error"):
      # Error context'i prompt'a ekle
      context = f"Önceki hata: {state['sql_error']}"
      response = await chain.ainvoke({
          "resolved_steps": steps_json,
          "previous_error": context  # ← YENI
      })
  ```

- [ ] **2.2.3** - Graph'a retry edge ekle
  ```python
  graph.add_conditional_edges(
      "sql_executor",
      lambda state: "sql_query_builder" if "SQL_RETRY_NEEDED" in state.get("error", "") else "end"
  )
  ```

#### Test Cases:
- Invalid column name → retry ile düzelt
- Syntax error → retry ile düzelt
- 2+ retry sonra fail → user mesajı

#### Bağımlılıklar:
- State'de `sql_error` ve `retry_count` field'ları

---

### 2.3 ColumnType Hatası (UNKNOWN attribute)
**Problem:** `AttributeError: type object 'ColumnType' has no attribute 'UNKNOWN'`
**Çözüm:** ColumnType enum'ını kontrol et ve eksik değerleri ekle

#### Adımlar:
- [ ] **2.3.1** - ColumnType enum'ını bul ve kontrol et
  ```bash
  grep -r "ColumnType" src/
  ```

- [ ] **2.3.2** - Eksik enum value'ları ekle
  ```python
  class ColumnType(Enum):
      STRING = "string"
      NUMBER = "number"
      DATE = "date"
      UNKNOWN = "unknown"  # ← EKLE
  ```

- [ ] **2.3.3** - Fallback kullan
  ```python
  column_type = ColumnType[col_type] if col_type in ColumnType.__members__ else ColumnType.UNKNOWN
  ```

#### Bağımlılıklar:
- Visualization node'larında kullanılan ColumnType

---

### 2.4 İlk Sorgu Hatası (Cannot visualize due to text2sql error)
**Problem:** İlk mesajda hata
**Çözüm:** Initial state validation ve fallback

#### Adımlar:
- [ ] **2.4.1** - Extract query node'u güçlendir
  ```python
  if not user_query:
      return {
          "error": "Lütfen bir soru yazın",
          "text2sql_output": None
      }
  ```

- [ ] **2.4.2** - Intent analyzer fallback ekle
  ```python
  if not parsed_intent:
      # Fallback simple query generator
      simple_query = generate_fallback_query(user_query)
  ```

- [ ] **2.4.3** - Visualizer error handling
  ```python
  if text2sql_output.get("error"):
      return {
          "error": None,  # ← Clear error
          "no_records_message": "SQL sorgusu başarısız oldu"
      }
  ```

#### Test Cases:
- Boş soru → hata mesajı
- Kapalı tablo sorgusu → fallback
- Unknown column → retry

#### Bağımlılıklar:
- `invoke_text2sql_node`, `invoke_visualization_node`

---

### 2.5 Null Değer Yönetimi
**Problem:**
- İlk WITH'te null sonuç
- Kategori bilgisi None
- PaymentAmount hatası

**Çözüm:** WHERE clause'lara IS NOT NULL ekle (already done) + data validation

#### Adımlar:
- [ ] **2.5.1** - SQL Generator'daki IS NOT NULL kuralını güçlendir
  ```python
  # prompts.py - Kural 3.5 zaten var, ama şunu ekle:
  # "Eğer Aggregation varsa (SUM, COUNT, AVG, etc.),
  # o kolonna IS NOT NULL zorunlu!"
  ```

- [ ] **2.5.2** - Value resolver'da null check
  ```python
  if resolved_value is None:
      logger.warning(f"Resolved value is None for {field_hint}")
      continue  # ← Skip null values
  ```

- [ ] **2.5.3** - Response builder'da None field'ları handle et
  ```python
  for row in data:
      if row.get("category") is None:
          row["category"] = "Kategorisiz"  # ← Default value
  ```

#### Test Cases:
- Kategori None geldiğinde "Diğer" yap
- Amount NULL ise 0 yap
- PaymentAmount için special handling

#### Bağımlılıklar:
- SQL Generator prompt'u
- Value Resolver logic
- Response Builder

---

## 🧠 FASE 3: SQL, NLP & Bağlam Iyileştirmeleri

### 3.1 Bağlamsal Takip (Conversation History)
**Problem:**
- History şişiyor, token limit hatası
- Konuşmayı devam ettirme yeteneği yok

**Çözüm:** Smart history management + context summarization

#### Adımlar:
- [ ] **3.1.1** - History management strategy oluştur
  ```python
  # Strategy seçenekleri:
  # 1. Sliding window (son N mesaj)
  # 2. Summarization (eski mesajları özetle)
  # 3. Importance filtering (önemli mesajları tut)
  ```

- [ ] **3.1.2** - Conversation state'i ekle
  ```python
  class ConversationState(TypedDict):
      messages: List[BaseMessage]
      summary: Optional[str]  # ← Özet
      context_window: int = 5  # ← Son N mesaj
      total_tokens: int = 0
  ```

- [ ] **3.1.3** - Token counter implement et
  ```python
  from tiktoken import encoding_for_model

  def count_tokens(text: str) -> int:
      enc = encoding_for_model("gpt-4o-mini")
      return len(enc.encode(text))
  ```

- [ ] **3.1.4** - History truncation/summarization
  ```python
  if total_tokens > TOKEN_LIMIT:
      # Option 1: Sliding window
      messages = messages[-5:]

      # Option 2: Summarize
      summary = await summarize_old_messages(messages[:-5])
      state["summary"] = summary
  ```

#### Test Cases:
- 10+ soru sonra token limit check
- Summarization'dan sonra conversational cevap
- Sliding window'da context kayıp etme

#### Bağımlılıklar:
- LLM token counting
- Message state management

---

### 3.2 Conversational Follow-up (Filtreleme Devamı)
**Problem:** "Son 10 gün" gibi filtreler, önceki sorguya eklenmeyip yeni query oluyor
**Çözüm:** Incremental query building + context awareness

#### Adımlar:
- [ ] **3.2.1** - Query context tracking
  ```python
  class QueryContext(TypedDict):
      last_query: str
      last_filters: List[Filter]
      last_table: str
      conversation_step: int
  ```

- [ ] **3.2.2** - Intent analyzer'da follow-up detection
  ```python
  def is_followup_query(new_query: str, last_query: str) -> bool:
      # "Son 10 gün", "bu ürün için", "da" gibi keywords kontrol et
      followup_keywords = ["da", "için", "da", "sonra", "o zaman"]
      return any(kw in new_query.lower() for kw in followup_keywords)
  ```

- [ ] **3.2.3** - Filter merging logic
  ```python
  if is_followup:
      merged_filters = merge_filters(last_filters, new_filters)
      state["filters"] = merged_filters
  ```

#### Test Cases:
- "En çok satan ürün" → "son 10 gün için" (merge filters)
- "Bu kategoride" → previous category filter ekle
- Multiple follow-ups in sequence

#### Bağımlılıklar:
- Intent analyzer
- Filter merging logic
- Query context tracking

---

### 3.3 Karmaşık Sorgu Analizi & Ambiguity Resolution
**Problem:**
- "En çok satan ürün" sorusuna sadece ürün adı, tarih yok
- Ambiguous sorular yanlış interpret ediliyor

**Çözüm:** Multi-step clarification + explicit parameter extraction

#### Adımlar:
- [ ] **3.3.1** - Ambiguity detector implement et
  ```python
  def detect_ambiguity(query: str) -> List[str]:
      # Hangi parametreler eksik?
      ambiguities = []
      if "tarih" not in query and "zaman" not in query:
          ambiguities.append("Zaman periyodu eksik")
      if "kategori" not in query and "ürün" not in query:
          ambiguities.append("Ürün/Kategori eksik")
      return ambiguities
  ```

- [ ] **3.3.2** - Clarification prompt implement et
  ```python
  if ambiguities:
      clarification = await llm.aask(
          f"Kullanıcı şunu sordu: {query}\n"
          f"Bu parametreleri de belirt: {ambiguities}"
      )
      state["clarification"] = clarification
  ```

- [ ] **3.3.3** - Response template'i güncelle
  ```python
  # Sorgu cevabına parametreleri ekle
  response = f"""
  **Sorgu:** {query}
  **Tablo:** {table}
  **Zaman Periyodu:** {time_period} ← Explicit
  **Sonuç:** {result}
  """
  ```

#### Test Cases:
- "En çok satan ürün" → time period defaultu, response'da explicit
- "Ciro" → Hangi kategori/ürün? clarify
- Ambiguous date range → suggestion ekle

#### Bağımlılıklar:
- LLM clarification
- Parameter extraction

---

### 3.4 Zaman Kırılımları (Temporal Dimensions)
**Problem:** "Son Gün", "Haftanın Günleri" gibi özel zaman ayrımları hatalı
**Çözüm:** Zaman mapping + custom date functions

#### Adımlar:
- [ ] **3.4.1** - Temporal mapping dictionary oluştur
  ```python
  TEMPORAL_MAPPING = {
      "son gün": "CAST(DocumentDate AS DATE) = CAST(GETDATE() AS DATE)",
      "son 7 gün": "DocumentDate >= DATEADD(DAY, -7, CAST(GETDATE() AS DATE))",
      "haftanın günü": "DATEPART(WEEKDAY, DocumentDate)",
      "ayın günü": "DATEPART(DAY, DocumentDate)",
      "ayın haftası": "DATEPART(WEEK, DocumentDate)"
  }
  ```

- [ ] **3.4.2** - Intent parser'da temporal extraction
  ```python
  def extract_temporal_expression(query: str) -> Optional[str]:
      for key, sql_expr in TEMPORAL_MAPPING.items():
          if key in query.lower():
              return sql_expr
      return None
  ```

- [ ] **3.4.3** - SQL generator'da temporal expression kullan
  ```python
  if temporal_expr:
      where_clause += f" AND {temporal_expr}"
  ```

#### Test Cases:
- "Son 10 gün" → Doğru date range
- "Haftanın günü" → DATEPART(WEEKDAY) kullan
- "Bu ay" → DATEPART(MONTH) = MONTH(GETDATE())
- "Geçen sene" → DATEPART(YEAR) = DATEPART(YEAR) - 1

#### Bağımlılıklar:
- TEMPORAL_MAPPING dictionary
- Intent parser
- SQL generator

---

## 📊 FASE 4: Görselleştirme & Sunum

### 4.1 Plotly Hesaplama & Uyumluluk
**Problem:**
- Pasta grafik (pie chart) için yanlış data
- Bazı chart type'ları uyumsuz veri alıyor

**Çözüm:** Chart-specific data validation + transformation

#### Adımlar:
- [ ] **4.1.1** - Chart validator implement et
  ```python
  class ChartValidator:
      def validate_pie_chart(data: List[Dict]) -> bool:
          # Pie chart için: 1 numeric column, 1+ categorical
          numeric_cols = [col for col, val in data[0].items() if isinstance(val, (int, float))]
          return len(numeric_cols) >= 1

      def validate_bar_chart(data: List[Dict]) -> bool:
          # Bar için: >=1 categorical, >=1 numeric
          return len(data) > 0
  ```

- [ ] **4.1.2** - Data transformation implement et
  ```python
  def prepare_pie_chart_data(raw_data: List[Dict], value_col: str, label_col: str):
      # Ensure data is in correct format
      return [{"label": row[label_col], "value": row[value_col]} for row in raw_data]
  ```

- [ ] **4.1.3** - Visualization decider'ı güçlendir
  ```python
  if not validator.validate(data, chart_type):
      # Fallback to compatible chart type
      chart_type = suggest_compatible_chart(data)
      logger.warning(f"Chart type changed to {chart_type}")
  ```

#### Test Cases:
- Pasta grafik (1 kategori, 1 value) ✓
- Bar chart (multiple categories) ✓
- Line chart (time series) ✓
- Incompatible data → fallback suggestion

#### Bağımlılıklar:
- Chart validator
- Data transformer
- Visualization decider

---

### 4.2 Türkçe Dil Desteği (i18n)
**Problem:** Grafik başlıkları, legend'lar İngilizce
**Çözüm:** i18n system + Turkish templates

#### Adımlar:
- [ ] **4.2.1** - i18n configuration
  ```python
  I18N_CONFIG = {
      "tr": {
          "title": "Başlık",
          "x_axis": "X Ekseni",
          "y_axis": "Y Ekseni",
          "legend": "Açıklama",
          "sum": "Toplam",
          "average": "Ortalama",
          "count": "Adet"
      }
  }
  ```

- [ ] **4.2.2** - Plotly template'ine Türkçe labels ekle
  ```python
  def build_plotly_figure(data, chart_config, lang="tr"):
      translations = I18N_CONFIG[lang]

      fig = go.Figure(data=traces, layout=go.Layout(
          title=translations["title"],
          xaxis_title=translations["x_axis"],
          yaxis_title=translations["y_axis"]
      ))
      return fig
  ```

- [ ] **4.2.3** - Column mapping (DB columns → Türkçe)
  ```python
  COLUMN_NAMES_TR = {
      "ProductName": "Ürün Adı",
      "CategoryName": "Kategori",
      "TotalQty": "Toplam Miktar",
      "SaleAmount": "Satış Tutarı"
  }
  ```

#### Test Cases:
- Tüm grafik başlıkları Türkçe
- Legend'lar çevrilen ürün/kategori adları
- Tooltip'ler Türkçe

#### Bağımlılıklar:
- i18n system
- Column translation mapping

---

## ⚡ FASE 5: Performans & Optimizasyon

### 5.1 Performans Hedefi: <20 Saniye
**Problem:** Toplam süre 20+ saniye
**Çözüm:** Profiling + bottleneck elimination

#### Adımlar:
- [ ] **5.1.1** - Timing instrumentation
  ```python
  import time
  from contextlib import contextmanager

  @contextmanager
  def timer(name: str):
      start = time.time()
      yield
      elapsed = time.time() - start
      logger.info(f"{name}: {elapsed:.2f}s")

  # Kullanım:
  with timer("Intent Analyzer"):
      intent = await intent_analyzer_node(state)
  ```

- [ ] **5.1.2** - Her node'u time
  ```
  START                    (0.0s)
  → intent_analyzer        (1-2s)  ← LLM call
  → sql_query_builder      (2-3s)  ← LLM call
  → sql_executor           (1-2s)  ← DB query
  → check_results          (0.1s)
  → visualizer             (3-5s)  ← Plotly calculation
  → output_formatter       (0.5s)
  END                      (8-13s total)
  ```

- [ ] **5.1.3** - Bottleneck'leri identify et
  ```python
  # Log her node'un süresi
  if elapsed > SLOW_THRESHOLD:
      logger.warning(f"SLOW: {name} took {elapsed:.2f}s")
  ```

- [ ] **5.1.4** - Optimizasyon planı (fase başına)
  - LLM call'larını parallelize et → 2-3s tasarruf
  - SQL execution'ı cache et → 1s tasarruf
  - Plotly calculation'ı async et → 1s tasarruf

#### Success Criteria:
- Intent Analyzer: <2s
- SQL Builder: <2s
- SQL Executor: <2s
- Visualizer: <3s
- **Total: <10s** (buffer ile 20s)

#### Bağımlılıklar:
- Timing instrumentation
- Parallel execution setup

---

### 5.2 Token Tasarrufu
**Problem:** Supervisor agent gereksiz token harcıyor
**Çözüm:** Prompt optimization + context reduction

#### Adımlar:
- [ ] **5.2.1** - Token counter implement et
  ```python
  def count_tokens_in_prompt(prompt: str) -> int:
      # Her node'un token kullanımını track et
      pass
  ```

- [ ] **5.2.2** - Unnecessary context'i kaldır
  ```python
  # BEFORE: Full business rules + schema + examples
  # AFTER: Only relevant parts

  # Eski: 5000+ tokens
  # Yeni: 2000-3000 tokens
  ```

- [ ] **5.2.3** - Compact prompt'lar oluştur
  ```python
  COMPACT_SQL_BUILDER_PROMPT = """
  Kısa prompt burada
  """
  ```

#### Success Criteria:
- Intent Analyzer prompt: <1000 tokens
- SQL Builder prompt: <2000 tokens
- Total per request: <5000 tokens

#### Bağımlılıklar:
- Token counter
- Prompt optimization

---

### 5.3 Cache Mekanizması
**Problem:** Tekrarlanan sorgular tekrar çalışıyor
**Çözüm:** Query result caching + smart invalidation

#### Adımları:
- [ ] **5.3.1** - Cache layer implement et
  ```python
  from functools import lru_cache

  @lru_cache(maxsize=100)
  async def cached_sql_executor(sql_hash: str, db_conn: str):
      return await _execute_sql(sql, db_conn)
  ```

- [ ] **5.3.2** - Cache key strategy
  ```python
  def get_cache_key(sql_query: str, db_conn: str) -> str:
      return hashlib.sha256(
          f"{sql_query}:{db_conn}".encode()
      ).hexdigest()
  ```

- [ ] **5.3.3** - Cache invalidation
  ```python
  # Invalidate cache when:
  # 1. Table schema changes
  # 2. Time period changes
  # 3. User explicitly requests fresh data
  ```

- [ ] **5.3.4** - Cache statistics
  ```python
  logger.info(f"Cache hit rate: {cache_hits / total_requests * 100}%")
  ```

#### Test Cases:
- Same query 2x → 2nd is cached
- Different time range → cache miss
- Manual refresh → cache clear

#### Bağımlılıklar:
- LRU cache implementation
- Cache key generation

---

### 5.4 Yük Testi (Load Testing)
**Problem:** Large dataset'lerde Value Resolver çöküyor
**Çözüm:** Batch processing + optimization

#### Adımlar:
- [ ] **5.4.1** - Load test setup
  ```python
  # Test scenarios:
  # 1. 1000 rows × 10 filters → batch resolve
  # 2. 100,000 rows → pagination
  # 3. Complex JOIN → performance measure
  ```

- [ ] **5.4.2** - Value resolver optimization
  ```python
  def resolve_values_batch(values: List[str], field: str):
      # Batch mode: resolve all at once
      # Instead of: for value in values: resolve(value)
      return batch_resolver.resolve_all(values, field)
  ```

- [ ] **5.4.3** - Pagination implement et
  ```python
  if len(results) > MAX_ROWS:
      results = results[:MAX_ROWS]
      state["warning"] = f"Results truncated to {MAX_ROWS} rows"
  ```

#### Success Criteria:
- 100K rows: <5s execution
- Batch resolve: <1s for 100 values
- Memory usage: <500MB

#### Bağımlılıklar:
- Batch resolver
- Pagination logic

---

## 🧪 Test & Doğrulama

### Test Senariyoları

#### T1: Boş Veri Yönetimi
```
Query: "2050 yılı satışları"
Expected: ℹ️ Sorguya uygun kayıt bulunamadı.
Status: PASS/FAIL
```

#### T2: SQL Error Tolerance
```
Query: "Yanlış kolonu sor"
Step 1: SQL Error
Step 2: LLM fixes query
Step 3: Results returned
Status: PASS/FAIL
```

#### T3: Conversational Follow-up
```
Query 1: "En çok satan ürün"
Query 2: "Son 10 gün için"
Expected: Filter merged, result updated
Status: PASS/FAIL
```

#### T4: Complex Query (Ambiguity)
```
Query: "En çok satan ürün en çok hangi gün satmıştır?"
Expected: Ürün Adı + Gün + Miktar
Status: PASS/FAIL
```

#### T5: Performance
```
Query: Any standard query
Expected: Execution <20s
Measurement:
  - Intent Analyzer: <2s
  - SQL Builder: <2s
  - SQL Executor: <2s
  - Visualizer: <3s
Status: PASS/FAIL
```

#### T6: Visualization
```
Query: "Kategorilere göre ciro"
Expected: Pie chart (Türkçe labels)
Status: PASS/FAIL
```

#### T7: HTML Cleaning
```
Query: Any query returning HTML
Expected: No <div>, <script> tags in response
Status: PASS/FAIL
```

---

## 📅 Uygulama Sırası

### Hafta 1: Foundation (Kritik Hatalar)
1. **Monday-Tuesday:** Fase 2.1-2.5 (Boş data, SQL retry, Null handling)
2. **Wednesday:** Fase 1.3 (Akış Kontrolü - Skip viz)
3. **Thursday-Friday:** Testing + T1-T2 scenarios

### Hafta 2: Mimari (Refactoring)
1. **Monday-Wednesday:** Fase 1.1 (Multi-Agent structure)
2. **Thursday:** Fase 1.2 (Configuration management)
3. **Friday:** Integration testing

### Hafta 3: Features (Improvements)
1. **Monday-Tuesday:** Fase 3.1-3.2 (Conversation history, follow-up)
2. **Wednesday:** Fase 3.3-3.4 (Ambiguity, temporal)
3. **Thursday-Friday:** Testing + T3-T4 scenarios

### Hafta 4: UX & Performance
1. **Monday-Tuesday:** Fase 4.1-4.2 (Visualization, i18n)
2. **Wednesday:** Fase 1.4 (HTML cleaning)
3. **Thursday:** Fase 5.1-5.2 (Performance profiling)
4. **Friday:** Fase 5.3-5.4 (Cache, load testing)

### Hafta 5: Final
1. **Monday-Thursday:** Full integration testing (T1-T7)
2. **Friday:** Documentation + Go-live checklist

---

## ✅ Go-Live Checklist

- [ ] Tüm kritik hatalar fixed
- [ ] Performance <20s
- [ ] T1-T7 tüm test'ler PASS
- [ ] No SQL injection vulnerabilities
- [ ] No memory leaks
- [ ] Conversation history working
- [ ] Cache enabled and tested
- [ ] Türkçe UI complete
- [ ] Documentation updated
- [ ] Team trained on new system

---

## 📝 Notes

- Her adım bağımsız olarak PR'lanabilir
- Test-first approach (test scenario'ları önce yazılır)
- Backward compatibility'yi koru (wrapper'lar kullan)
- Performance measurements her Cuma

---

**Prepared by:** System Architect
**Last Updated:** 2026-01-09
**Status:** 📋 Ready for Implementation
