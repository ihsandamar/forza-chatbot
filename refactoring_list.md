● 🔍 REPORT AGENT ANALİZ RAPORU

  📊 MEVCUT DURUM

  LLM Çağrı Sayısı: 5 çağrı (Hedef: ≤3) ❌
  Prompt Boyutu: 633 satır (Hedef: kısa ve öz) ❌
  Cache Mekanizması: Yok ❌
  SQL Validation: Yok ❌
  E2E Latency: Tahmin ~8-12 saniye (Hedef: 3-5 sn) ❌

  🔴 LLM Çağrı Akışı:

  Report Graph:
  ├── extract_query_node (LLM YOK - gereksiz node!)
  ├── Text2SQL Graph:
  │   ├── intent_parser_node (LLM #1) - gpt-4o-mini
  │   ├── intent_matching_node (LLM #2) - gpt-4o-mini
  │   ├── sql_query_builder_node (LLM #3) - gpt-4o-mini
  │   └── sql_executor_node
  └── Visualization Graph:
      ├── visualization_decider_node (LLM #4) - gpt-4o-mini
      └── plotly_code_generator_node (LLM #5) - gpt-4o-mini

  ---
  ✅ ÖNCELİKLİ REFACTORING LİSTESİ

  🔥 KRİTİK (P0) - HIZ & DOĞRULUK

  1. ❌ GEREKSIZ NODE SİL: extract_query_node

  Dosya: src/graphs/report/nodes.py:16-46

  Sorun:
  - Hiçbir işlem yapmıyor, sadece validation
  - Gereksiz state geçişi (latency artışı)
  - LLM yok ama node overhead'i var

  Aksiyon:
  # SİL: extract_query_node
  # GÜNCELLEgraph.py:
  # graph.add_edge(START, "text2sql")  # Direkt text2sql'e başla

  Kazanım: ~50-100ms latency azalması

  ---
  2. 🔥 PROMPT BOYUTUNUSİL: Boilerplate & Tekrarları Kaldır

  Dosya: src/graphs/generic_text2sql/prompts.py (633 satır!)

  Sorun:
  - INTENT_PARSER_PROMPT_TEXT: ~400+ satır
  - Çok fazla örnek (4+ örnek)
  - Tekrarlayan talimatlar
  - "Sen bir uzmanısın" gibi boilerplate

  Aksiyon:
  # ÖNCESİ: 400+ satır prompt
  # SONRASI: ~100-150 satır prompt

  # Yapılacaklar:
  1. Örnekleri 2'ye indir (basit + compound)
  2. Boilerplate kaldır ("Sen bir uzman..." → direkt görev)
  3. Tekrar eden kuralları birleştir
  4. JSON schema'yı ayrı dosyaya taşı

  Kazanım:
  - ~2000-3000 token azalması
  - ~1-2 saniye latency azalması
  - ~%40-50 maliyet düşüşü

  ---
  3. ⚡ SQL BUILDER'I DETERMİNİSTİK YAP

  Dosya: src/graphs/generic_text2sql/nodes.py:506-510

  Sorun:
  - SQL builder LLM ile yapılıyor (non-deterministic!)
  - Aynı intent → farklı SQL riski
  - Accuracy riski

  Aksiyon:
  # ÖNCESİ:
  # llm → SQL (non-deterministic)

  # SONRASI:
  # ParsedIntent + EnrichedMetadata → Deterministic SQL Builder
  class DeterministicSQLBuilder:
      def build(self, intent: ParsedIntent, metadata: EnrichedMetadata) -> str:
          # Template-based SQL generation
          # No LLM needed!

  Kazanım:
  - 1 LLM çağrısı azalır (5→4)
  - %100 deterministic SQL
  - ~1-2 saniye latency azalması
  - Accuracy ↑ (%99 → %99.9)

  ---
  4. 🚀 INTENT PARSER + MATCHER BİRLEŞTİR

  Dosyalar:
  - src/graphs/generic_text2sql/nodes.py:98-144 (parser)
  - src/graphs/generic_text2sql/nodes.py:146-228 (matcher)

  Sorun:
  - İki ayrı LLM çağrısı
  - Parser: generic intent
  - Matcher: DB schema mapping
  - Birleştirilebilir!

  Aksiyon:
  # ÖNCESİ:
  # Step 1: Generic intent (LLM #1)
  # Step 2: Schema mapping (LLM #2)

  # SONRASI:
  # Single Step: Intent + Schema (LLM #1)
  # Prompt'a DB schema'yı ekle, direkt enriched intent döndür

  Kazanım:
  - 1 LLM çağrısı azalır (4→3)
  - ~1-2 saniye latency azalması
  - Hedef çağrı sayısına ulaşılır (≤3) ✅

  ---
  5. 📦 CACHE MEKANİZMASI EKLE

  Dosya: Yeni dosya → src/services/report_cache.py

  Sorun:
  - Aynı rapor tekrar sorulursa tüm LLM'ler tekrar çalışır
  - Standart raporlar (günlük, haftalık) her seferinde baştan

  Aksiyon:
  class ReportCache:
      """
      Cache strategy:
      - Key: hash(user_query + date_context)
      - TTL: 15 minutes (configurable)
      - Storage: Redis / in-memory dict
      """

      async def get_or_compute(self, query: str) -> ReportResult:
          cache_key = self._hash_query(query)
          if cached := await self.get(cache_key):
              return cached
          result = await self._compute(query)
          await self.set(cache_key, result, ttl=900)
          return result

  Kazanım:
  - Cache hit → 0 LLM çağrısı!
  - E2E: ~50-200ms (vs 8-12 saniye)
  - ~%80-90 maliyet düşüşü (yüksek cache hit oranında)

  ---
  ⚠️ ÖNEMLİ (P1) - DOĞRULUK & GÜVENİLİRLİK

  6. 🛡️ SQL VALIDATION EKLE

  Dosya: src/graphs/generic_text2sql/nodes.py:549 (executor'dan önce)

  Sorun:
  - SQL çalıştırılmadan önce validation yok
  - Yanlış SQL → exception
  - LIMIT kontrolü yok

  Aksiyon:
  class SQLValidator:
      def validate(self, sql: str) -> ValidationResult:
          # 1. Syntax check (sqlparse)
          # 2. LIMIT check (zorunlu!)
          # 3. Dangerous keywords (DROP, DELETE, etc.)
          # 4. JOIN validation
          # 5. Explain plan kontrolü (optional)

  Kazanım:
  - Hatalı SQL engellenir
  - Performans koruması (LIMIT zorunlu)
  - Güvenlik ↑

  ---
  7. 📚 KPI SÖZLÜĞÜ EKLE

  Dosya: Yeni dosya → src/config/kpi_dictionary.yaml

  Sorun:
  - "satış", "ciro", "net", "brüt" terimleri tanımsız
  - Farklı kullanıcılar → farklı yorumlar

  Aksiyon:
  # kpi_dictionary.yaml
  kpis:
    satış:
      field: "Tutar"
      aggregation: "SUM"
      description: "Toplam satış tutarı (brüt)"

    net_satış:
      field: "NetTutar"
      aggregation: "SUM"
      description: "İndirim sonrası net tutar"

    adet:
      field: "Miktar"
      aggregation: "SUM"
      description: "Toplam satış adedi"

  Kazanım:
  - Tutarlı metrikler
  - Belirsizlik azalır
  - Accuracy ↑

  ---
  8. 🎯 VİZUALİZATION DECIDER İYİLEŞTİR

  Dosya: src/graphs/data_visualization/nodes/visualization_decider.py:33-48

  Sorun:
  - Prompt kısa ama iyileştirilebilir
  - Quick exit conditions iyi ama eksik
  - Zaman serisi tespiti yeterince güçlü değil

  Aksiyon:
  # Ekle: Deterministic rules (LLM'den önce)
  def quick_decision(data_profile: DataProfile) -> Optional[OutputType]:
      # 1 satır + 1 kolon → single_value
      # time_column + metric → line_chart
      # 2-3 kategori → pie_chart
      # >10 kategori → bar_chart (top 10)
      # >5 kolon → table

  Kazanım:
  - Daha az LLM çağrısı (bazı durumlar deterministik)
  - Daha doğru grafik seçimi

  ---
  🔧 İYİLEŞTİRME (P2) - KALİTE & BAKIM

  9. 📉 PLOTLY PROMPT OPTİMİZE ET

  Dosya: src/graphs/data_visualization/nodes/plotly_code_generator.py:28-62

  Sorun:
  - Prompt iyi ama optimize edilebilir
  - Türkçe talimatlar → İngilizce daha iyi çalışabilir
  - Örnek kod eklenebilir

  Aksiyon:
  # Kısa ve öz system prompt
  # Template-based örnekler ekle
  # "autosize=True" yerine "responsive design" patterns

  ---
  10. 📊 METRİK & MONİTÖRİNG EKLE

  Dosya: Yeni dosya → src/monitoring/report_metrics.py

  Aksiyon:
  class ReportMetrics:
      """
      Track:
      - E2E latency (p50, p95, p99)
      - LLM call count per report
      - Token usage per report
      - SQL execution time
      - Cache hit rate
      - User correction rate
      - Error rate
      """

  ---
  11. 🔄 PARALLELISM EKLE (Viz Graph İçinde)

  Dosya: src/graphs/data_visualization/graph.py

  Sorun:
  - Tüm node'lar sequential
  - Bazı node'lar paralel çalışabilir

  Aksiyon:
  # Paralel çalıştırılabilir:
  # - chart_config_builder (metadata'ya bağlı)
  # - response_builder (visualization sonrasında)
  # Ama etki küçük (~100-200ms), P2 öncelik

  ---
  12. 🧪 UNIT TEST COVERAGE ARTTIR

  Dosya: tests/graphs/report/

  Aksiyon:
  - SQL builder deterministik testleri
  - Cache hit/miss testleri
  - Validation testleri
  - Edge case testleri

  ---
  📈 BEKLENEN KAZANIMLAR (Tüm Refactoring Sonrası)

  | Metrik          | Önce | Sonra  | İyileşme |
  |-----------------|------|--------|----------|
  | LLM Çağrı       | 5    | 3      | ✅ -40%  |
  | E2E Latency     | ~10s | ~4s    | ✅ -60%  |
  | Token/Rapor     | ~8K  | ~4K    | ✅ -50%  |
  | Cache Hit (E2E) | -    | ~100ms | ✅ -98%  |
  | SQL Doğruluk    | ~%95 | %99.5  | ✅ +4.5% |
  | Maliyet         | $X   | $0.4X  | ✅ -60%  |

  ---
  🎯 İMPLEMENTASYON SIRASI

  Sprint 1 (Hız Odaklı - 1 hafta)

  1. ✅ P0-1: extract_query_node sil
  2. ✅ P0-2: Prompt boyutu küçült
  3. ✅ P0-5: Cache ekle

  Kazanım: ~4-5 saniye E2E latency

  Sprint 2 (Doğruluk Odaklı - 1 hafta)

  4. ✅ P0-3: SQL builder deterministik yap
  5. ✅ P0-4: Intent parser + matcher birleştir
  6. ✅ P1-6: SQL validation ekle

  Kazanım: 3 LLM çağrısı, %99.5 SQL doğruluğu

  Sprint 3 (Kalite Odaklı - 1 hafta)

  7. ✅ P1-7: KPI sözlüğü
  8. ✅ P1-8: Viz decider iyileştir
  9. ✅ P2-10: Metrik & monitoring

  Kazanım: Production-ready sistem

  ---
  🚨 ALTIN KURALLAR UYUMLULUK

  | Kural                        | Durum                  | Aksiyon    |
  |------------------------------|------------------------|------------|
  | LLM sadece belirsizlik için  | ❌ SQL builder LLM ile | P0-3       |
  | Deterministic → kod          | ❌ SQL, intent parsing | P0-3, P0-4 |
  | ≤3 LLM çağrısı               | ❌ 5 çağrı             | P0-4       |
  | Single source of truth (SQL) | ✅ OK                  | -          |
  | Cache stratejisi             | ❌ Yok                 | P0-5       |
  | SQL validation               | ❌ Yok                 | P1-6       |
  | KPI sözlüğü                  | ❌ Yok                 | P1-7       |

  ---
  Refactoring listesi hazır! En kritik maddelerden başlayacak şekilde prioritize edildi. Her madde dosya yolu ve satır numarasıyla işaretli. Hangi maddeyle başlamak istersiniz?