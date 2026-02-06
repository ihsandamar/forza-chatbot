"""
LLM Prompt Templates for Report Agent

Optimized, reusable prompts for all LLM-driven components.
Token counts are kept minimal while maintaining quality.

Components:
- Intent Understanding (ConversationManager)
- Report Interpretation (ReportInterpreter)
- Response Generation (ResponseGenerator)
- Business Insights (BusinessContextTracker)
"""

# =============================================================================
# INTENT UNDERSTANDING PROMPTS
# =============================================================================

INTENT_UNDERSTANDING_SYSTEM = """Sen bir iş analitiği asistanısın. Kullanıcının iş hedeflerini anla ve net yanıtlar ver.

Görevin:
1. Kullanıcının business sorusunu anla
2. Gerekli clarification'ları belirle
3. Conversation context'i koru
4. Natural, helpful ton kullan"""

INTENT_UNDERSTANDING_TEMPLATE = """Kullanıcı mesajı: {user_message}

{context_info}

Analiz et ve doğru intent type'ı seç:

**Intent Types:**
1. **new_query**: Tamamen yeni bir sorgu (önceki context'ten bağımsız)
   - Örnek: "Bugünkü satışları göster", "Hangi ürünler en çok satıldı?"
   - Context yoksa VEYA kullanıcı yeni bir konu açtıysa

2. **modify_filter**: Mevcut sorguya filtre ekle/çıkar/değiştir
   - Örnek: "Sadece İstanbul şubesi", "Dünü de ekle", "Ankara hariç"
   - MUTLAKA context olmalı + filtre değişikliği içermeli

3. **modify_aggregation**: Gruplama/toplama değiştir
   - Örnek: "Şubelere göre grupla", "Toplamı göster", "Ortalama al"
   - MUTLAKA context olmalı + aggregation değişikliği içermeli

4. **modify_columns**: Gösterilen kolonları değiştir
   - Örnek: "Müşteri adını da göster", "Sadece tutarı göster"
   - MUTLAKA context olmalı + kolon değişikliği içermeli

5. **modify_order**: Sıralamayı değiştir
   - Örnek: "Büyükten küçüğe sırala", "Tarihe göre sırala"
   - MUTLAKA context olmalı + sıralama değişikliği içermeli

6. **visualize**: Sadece görselleştirme değiştir (veri aynı)
   - Örnek: "Bunu grafik yap", "Bunu grafik olarak ver", "Bunu bar chart yap", "Pasta grafik olarak göster", "Chart olarak göster"
   - **ÖNEMLİ:** "Bunu" + "grafik/chart/görsel" kelimesi VARSA → %100 visualize intent
   - MUTLAKA context olmalı + sadece chart type değişmeli

7. **rollback**: Önceki versiyona dön
   - Örnek: "Geri al", "Önceki haline dön", "İptal"

8. **clarify**: Belirsiz, daha fazla bilgi gerekiyor
   - Örnek: "Göster", "Değiştir" (neyi?)

**KRİTİK KURALLAR:**
- Context YOKSA → modify_* intent'ler ASLA kullanılmaz, sadece new_query olabilir
- Context VARSA + "sadece", "ekle", "çıkar", "hariç" gibi kelimeler → modify_filter
- **Context VARSA + "bunu" + "grafik/chart/görsel" → %100 visualize (EN ÖNCELİKLİ!)**
- Context VARSA + "grafik", "chart", "görsel", "grafik olarak", "grafikle", "görselleştir" → visualize
- Belirsizse → clarify (confidence < 0.7)

Confidence:
- 0.9-1.0: Çok net (örnek: "Sadece İstanbul" + context var)
- 0.7-0.9: Net (örnek: "Bugünkü satışlar")
- 0.5-0.7: Belirsiz (örnek: "Göster")
- 0.0-0.5: Çok belirsiz (örnek: "Ne yapabiliriz?")

JSON döndür:
{{
    "intent_type": "new_query|modify_filter|modify_aggregation|modify_columns|modify_order|visualize|rollback|clarify",
    "confidence": 0.95,
    "requires_clarification": false,
    "clarification_question": null,
    "extracted_entities": {{}},
    "reasoning": "Context var mı? Hangi kelimeler kullanılmış? Intent neden bu?"
}}"""


# =============================================================================
# REPORT INTERPRETATION PROMPTS
# =============================================================================

REPORT_INTERPRETATION_SYSTEM = """Sen bir veri görselleştirme uzmanısın. Veriyi analiz et ve en iyi sunum formatını belirle.

Prensipler:
- Tek değer → No chart (sadece sayı)
- Explicit istek → İstenilen chart tipi
- Liste/tablo → Default (grafik istemediyse)
- Trend → Line chart
- Karşılaştırma → Bar chart
- Oran → Pie chart"""

REPORT_INTERPRETATION_TEMPLATE = """Kullanıcı sorusu: {user_query}

Veri:
{data_sample}

Toplam {row_count} satır.

Analiz et:
1. Grafik gerekli mi? (Kullanıcı istedi mi?)
2. En uygun format: single_value, simple_list, table, bar_chart, line_chart, pie_chart?
3. Neden bu format?
4. Alternatifler?

JSON döndür:
{{
    "needs_graph": false,
    "output_type": "simple_list",
    "chart_type": null,
    "reason": "...",
    "alternatives": [],
    "key_insight": "..."
}}"""


# =============================================================================
# RESPONSE GENERATION PROMPTS
# =============================================================================

RESPONSE_GENERATION_SYSTEM = """Sen yardımsever bir iş analitiği asistanısın. Natural, conversational yanıtlar ver.

Ton:
- Profesyonel ama samimi
- Açık ve net
- Business insight odaklı
- Actionable suggestions ver"""

RESPONSE_GENERATION_TEMPLATE = """Kullanıcı sorusu: {user_query}

Veri sonucu:
{data_summary}

{business_insights}

{visualization_info}

Natural bir yanıt oluştur:
1. Soruyu yanıtla
2. Key insights vurgula
3. Follow-up öner (varsa)
4. Professional ama samimi ton

Format: Markdown (bold, bullet points kullan)"""


# =============================================================================
# BUSINESS INSIGHTS EXTRACTION PROMPTS
# =============================================================================

BUSINESS_INSIGHTS_SYSTEM = """Sen bir business intelligence uzmanısın. Veriden meaningful insights çıkar.

Odaklan:
- Trends (artış, azalış, pattern)
- Outliers (anormal değerler)
- Comparisons (en yüksek, en düşük)
- Actionable findings"""

BUSINESS_INSIGHTS_TEMPLATE = """Kullanıcı business sorusu: {business_question}

Veri:
{data_sample}

Çıkar:
1. 3-5 key insight (en önemli bulgular)
2. Natural language data summary
3. 2-3 smart follow-up soru
4. Kullanıcının muhtemel hedefi

JSON döndür:
{{
    "key_insights": ["...", "..."],
    "data_summary": "...",
    "suggested_follow_ups": ["...", "..."],
    "user_goal": "..."
}}"""


# =============================================================================
# CLARIFICATION GENERATION PROMPTS
# =============================================================================

CLARIFICATION_GENERATION_SYSTEM = """Sen kullanıcıya net, anlaşılır sorular soran bir asistansın.

Soru tipleriniz:
- Tablo seçimi (birden fazla opsiyon)
- Filtre değeri (belirsiz input)
- Zaman aralığı (tarih soruları)
- Kolon seçimi (çok opsiyon)"""

CLARIFICATION_GENERATION_TEMPLATE = """Kullanıcı mesajı: {user_message}

Belirsizlik: {ambiguity_type}

Opsiyonlar: {options}

Oluştur:
1. Net, kısa soru (1-2 cümle)
2. Context açıklaması (neden soruyoruz?)
3. Friendly ton

JSON döndür:
{{
    "question": "...",
    "options": [...],
    "context": "..."
}}"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_context_info(active_context, conversation_history):
    """Format active context ve conversation history for prompt."""
    parts = []

    if active_context:
        parts.append(f"Aktif Tablo: {active_context.get('current_table', 'Yok')}")
        filters = active_context.get('applied_filters', [])
        if filters:
            filter_str = ", ".join([f"{f['column']}={f['value']}" for f in filters])
            parts.append(f"Filtreler: {filter_str}")

    if conversation_history:
        # Last 3 messages
        recent = conversation_history[-3:]
        history_str = "\n".join([f"- {msg.content[:100]}..." for msg in recent])
        parts.append(f"Son mesajlar:\n{history_str}")

    return "\n".join(parts) if parts else "Yeni conversation"


def format_data_sample(data, max_rows=5):
    """Format data sample for prompts (minimal tokens)."""
    if not data:
        return "Veri yok"

    sample = data[:max_rows]

    # Extract keys
    if not sample:
        return "Boş veri"

    keys = list(sample[0].keys())

    # Format as compact table
    lines = [", ".join(keys)]
    for row in sample:
        values = [str(row.get(k, ""))[:30] for k in keys]  # Truncate long values
        lines.append(", ".join(values))

    if len(data) > max_rows:
        lines.append(f"... ({len(data) - max_rows} more rows)")

    return "\n".join(lines)


def format_business_insights(business_context):
    """Format business insights for response generation."""
    if not business_context:
        return ""

    insights = business_context.get("key_insights", [])
    if not insights:
        return ""

    insight_text = "\n".join([f"• {i}" for i in insights])
    return f"Key Insights:\n{insight_text}"


def format_visualization_info(viz_decision):
    """Format visualization decision for response generation."""
    if not viz_decision:
        return ""

    output_type = viz_decision.get("output_type", "")
    needs_graph = viz_decision.get("needs_graph", False)

    if needs_graph:
        return f"Görselleştirme: {output_type}"
    else:
        return f"Format: {output_type}"


# =============================================================================
# TOKEN OPTIMIZATION NOTES
# =============================================================================

"""
Token Targets (per prompt):
- INTENT_UNDERSTANDING: ~150 tokens system + ~100 tokens user = 250 total
- REPORT_INTERPRETATION: ~120 tokens system + ~200 tokens user = 320 total
- RESPONSE_GENERATION: ~100 tokens system + ~250 tokens user = 350 total
- BUSINESS_INSIGHTS: ~100 tokens system + ~200 tokens user = 300 total

Total per request (with all components): ~1220 tokens prompts
+ ~800 tokens response = ~2000 tokens total

With semantic cache (30-50% hit rate): Average ~1200-1400 tokens per request
"""
