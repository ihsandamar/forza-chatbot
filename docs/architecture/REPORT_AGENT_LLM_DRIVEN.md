# Report Agent - LLM-Driven Conversational Architecture

**Version:** 5.0 (LLM-Driven, Business-Aware)
**Philosophy:** Smart conversation, not pattern matching

---

## 🎯 Core Principle

> **"LLM should understand user intent and business context, not just match keywords."**

### Why LLM-Driven?

**❌ Pattern Matching Problems:**
- Static, requires manual pattern updates
- Cannot understand business context
- Breaks with natural language variations
- No reasoning capability

**✅ LLM-Driven Benefits:**
- Understands user intent dynamically
- Applies business logic reasoning
- Handles natural conversation
- Adapts to new query types
- Explains decisions to user

---

## Architecture Philosophy

### The Right Balance

```
┌─────────────────────────────────────────────────────┐
│           LLM: Brain of the System                  │
│                                                      │
│  • User intent understanding                        │
│  • Business context reasoning                       │
│  • Conversation management                          │
│  • Report interpretation                            │
│  • Natural language generation                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│        Optimization: Smart, Not Aggressive          │
│                                                      │
│  • Token optimization WHERE IT MAKES SENSE          │
│  • Cache repeated expensive calls                   │
│  • Truncate old, irrelevant context                 │
│  • BUT: Keep business-critical information          │
└─────────────────────────────────────────────────────┘
```

**NOT:**
- ❌ Replace LLM with patterns (loses intelligence)
- ❌ Remove conversation history (loses context)
- ❌ Skip business reasoning (loses accuracy)

**DO:**
- ✅ Use LLM for understanding and reasoning
- ✅ Optimize prompts (concise but complete)
- ✅ Cache when semantically identical
- ✅ Smart context windowing (keep relevant, drop old)

---

## LLM-Driven Components

### 1. Conversation Manager (LLM Core)

**Purpose:** Understand what user wants, manage conversation flow, ask clarifying questions.

**LLM Responsibilities:**
- Parse user intent with business context
- Extract entities and parameters
- Identify missing information
- Decide if clarification needed
- Generate natural responses

#### Implementation

```python
class ConversationManager:
    """
    LLM-powered conversation manager.

    Core of the system - understands user intent and business context.
    """

    def __init__(self, llm_chat):
        self.llm = llm_chat
        self.conversation_history = []

    async def understand_intent(
        self,
        user_message: str,
        active_context: Optional[QueryContext],
        conversation_history: List[Message]
    ) -> ConversationIntent:
        """
        Use LLM to understand user intent with full context.

        NOT simple pattern matching - actual understanding.
        """

        # Build rich context for LLM
        prompt = self._build_intent_prompt(
            user_message=user_message,
            active_context=active_context,
            conversation_history=conversation_history
        )

        # LLM analyzes and reasons
        response = await self.llm.ainvoke(prompt)

        # Parse structured response
        intent = self._parse_intent_response(response)

        return intent

    def _build_intent_prompt(
        self,
        user_message: str,
        active_context: Optional[QueryContext],
        conversation_history: List[Message]
    ) -> List[Message]:
        """
        Build prompt for intent understanding.

        Key: Rich context, but focused on RELEVANT information.
        """

        system_prompt = """Sen bir business intelligence asistanısın.

Görevin: Kullanıcının ne istediğini anlamak ve doğru aksiyonu belirlemek.

Bağlam Analizi:
1. Kullanıcı yeni bir rapor mu istiyor?
2. Mevcut raporu mu değiştiriyor (filtre, gruplama, sıralama)?
3. Sonuçları görselleştirmek mi istiyor?
4. Önceki sorguya mı dönmek istiyor?
5. Başka bir şey mi?

Business Logic:
- Eğer kullanıcı "sadece", "için", "hariç" gibi kelimeler kullanıyorsa ve aktif bir sorgu varsa, bu muhtemelen bir filtre modifikasyonu.
- Eğer "grafiğe dönüştür", "çubuk grafik" gibi kelimeler varsa, görselleştirme isteği.
- Eğer "aylık", "kategoriye göre" varsa, gruplama değişikliği.

Eksik Bilgi Kontrolü:
- Kullanıcının isteği belirsiz mi?
- Daha fazla detay gerekiyor mu?
- Hangi seçenekler sunulabilir?

Cevap formatı (JSON):
{
    "intent_type": "new_query" | "modify_filter" | "modify_aggregation" | "visualize" | "rollback" | "clarification_needed",
    "confidence": 0.0-1.0,
    "reasoning": "Neden bu intent'i seçtin?",
    "extracted_info": {
        "filters": [...],
        "aggregations": [...],
        "chart_type": "...",
        ...
    },
    "missing_info": ["field1", "field2"],
    "clarification_question": "Kullanıcıya sorulacak soru (eğer gerekiyorsa)",
    "suggested_options": ["option1", "option2"]
}
"""

        # Conversation history (SMART truncation - keep relevant)
        relevant_history = self._get_relevant_history(
            conversation_history,
            user_message,
            max_messages=5  # Not arbitrary - context window
        )

        # Active context (if exists)
        context_summary = ""
        if active_context:
            context_summary = f"""
Aktif Sorgu Bağlamı:
- Kullanıcının son sorusu: {active_context.user_query}
- Sonuç sayısı: {active_context.result_summary.get('row_count', 0)} satır
- Sütunlar: {', '.join(active_context.result_summary.get('columns', []))}
"""

        # User message
        user_prompt = f"""
{context_summary}

Son Konuşma:
{self._format_history(relevant_history)}

Kullanıcı: {user_message}

Bu mesajı analiz et ve kullanıcının ne istediğini belirle.
"""

        return [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

    def _get_relevant_history(
        self,
        history: List[Message],
        current_message: str,
        max_messages: int = 5
    ) -> List[Message]:
        """
        Get relevant conversation history (smart truncation).

        NOT just "last N messages" - actually relevant ones.

        Strategy:
        1. Always keep last 2 messages (immediate context)
        2. Keep messages that mention same entities
        3. Drop very old messages (> 10 messages ago)
        """

        if len(history) <= max_messages:
            return history

        # Always keep recent
        recent = history[-2:]

        # Find relevant older messages
        older = history[:-2]
        relevant_older = []

        # Simple relevance: contains same keywords
        current_keywords = set(current_message.lower().split())

        for msg in older[-10:]:  # Only check last 10
            msg_keywords = set(msg.content.lower().split())
            overlap = len(current_keywords & msg_keywords)

            if overlap > 2:  # Some shared context
                relevant_older.append(msg)

        # Combine: relevant older + recent
        combined = relevant_older[-3:] + recent  # Max 3 older + 2 recent = 5

        return combined

    def _parse_intent_response(self, response) -> ConversationIntent:
        """Parse LLM response into structured intent."""
        import json

        try:
            # LLM should return JSON
            content = response.content

            # Extract JSON (might be wrapped in markdown)
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            data = json.loads(json_str)

            return ConversationIntent(
                intent_type=IntentType(data["intent_type"]),
                confidence=data["confidence"],
                reasoning=data["reasoning"],
                extracted_info=data.get("extracted_info", {}),
                missing_info=data.get("missing_info", []),
                clarification_question=data.get("clarification_question"),
                suggested_options=data.get("suggested_options", []),
                requires_clarification=data["intent_type"] == "clarification_needed"
            )

        except Exception as e:
            logger.error(f"Failed to parse intent: {e}", exc_info=True)

            # Fallback
            return ConversationIntent(
                intent_type=IntentType.UNKNOWN,
                confidence=0.3,
                reasoning="Parse error",
                requires_clarification=True,
                clarification_question="Lütfen isteğinizi açıklayabilir misiniz?"
            )
```

**Example Conversation:**

```
User: "Geçen ay satışları nasıldı?"

LLM Analysis:
{
    "intent_type": "new_query",
    "confidence": 0.9,
    "reasoning": "Kullanıcı belirli bir dönem (geçen ay) için satış verisi istiyor. Yeni bir rapor oluşturulmalı.",
    "extracted_info": {
        "time_period": "last_month",
        "metric": "sales"
    },
    "missing_info": [],
    "clarification_question": null
}

---

User: "Sadece İstanbul için"
(Active context: previous sales query)

LLM Analysis:
{
    "intent_type": "modify_filter",
    "confidence": 0.95,
    "reasoning": "Kullanıcı mevcut sorguya bir filtre eklemek istiyor. 'Sadece' kelimesi ve aktif context olması bunu gösteriyor. İstanbul şehir filtresi eklenmeli.",
    "extracted_info": {
        "filter_type": "city",
        "filter_value": "İstanbul",
        "filter_operation": "equals"
    },
    "missing_info": [],
    "clarification_question": null
}

---

User: "Daha iyi göster"

LLM Analysis:
{
    "intent_type": "clarification_needed",
    "confidence": 0.4,
    "reasoning": "Kullanıcının 'daha iyi' ile ne kastettiği belirsiz. Görselleştirme mi, daha detaylı veri mi, yoksa başka bir format mı istiyor açık değil.",
    "extracted_info": {},
    "missing_info": ["improvement_type"],
    "clarification_question": "Neyi daha iyi görmek istersiniz?",
    "suggested_options": [
        "Grafiğe dönüştür",
        "Daha detaylı veri",
        "Farklı bir gruplama",
        "Başka bir format"
    ]
}
```

---

### 2. Business Context Tracker

**Purpose:** Maintain business context across conversation, not just technical state.

```python
class BusinessContextTracker:
    """
    Track business context, not just technical state.

    Understands:
    - What business question is being answered?
    - What's the user's goal?
    - What insights have been discovered?
    - What follow-up questions make sense?
    """

    def __init__(self, llm_chat):
        self.llm = llm_chat
        self.context_summary = None

    async def update_context(
        self,
        user_query: str,
        sql_results: List[dict],
        conversation_history: List[Message]
    ) -> BusinessContext:
        """
        Update business context with LLM interpretation.

        LLM analyzes:
        - What business question was asked?
        - What insights do results show?
        - What might user want to explore next?
        """

        prompt = f"""
Kullanıcı Sorusu: {user_query}

Sonuçlar: {self._summarize_results(sql_results)}

Önceki Konuşma:
{self._format_history(conversation_history[-3:])}

Görevin:
1. Bu sorgunun business anlamını özetle
2. Sonuçlardan çıkan önemli içgörüleri belirle
3. Kullanıcının ilgisini çekebilecek takip sorularını öner

Cevap formatı (JSON):
{{
    "business_question": "Kullanıcı neyi öğrenmek istiyor?",
    "key_insights": ["İçgörü 1", "İçgörü 2"],
    "data_summary": "Veri özeti (1-2 cümle)",
    "suggested_follow_ups": [
        "Bu verileri grafiğe dönüştürmek ister misiniz?",
        "Belirli bir kategori için detaya inmek ister misiniz?",
        ...
    ]
}}
"""

        response = await self.llm.ainvoke(prompt)
        context = self._parse_business_context(response)

        self.context_summary = context
        return context

    def _summarize_results(self, results: List[dict], max_rows: int = 5) -> str:
        """Summarize results for LLM (don't send full data)."""

        if not results:
            return "Sonuç yok"

        summary = f"{len(results)} satır, {len(results[0].keys())} sütun\n"
        summary += f"Sütunlar: {', '.join(results[0].keys())}\n"
        summary += f"İlk {max_rows} satır:\n"

        for i, row in enumerate(results[:max_rows], 1):
            summary += f"{i}. {row}\n"

        if len(results) > max_rows:
            summary += f"... ve {len(results) - max_rows} satır daha"

        return summary
```

---

### 3. Report Interpreter (LLM-Assisted)

**Purpose:** Interpret results and decide how to present them.

```python
class ReportInterpreter:
    """
    LLM-powered report interpretation.

    Decides:
    - How should results be presented?
    - What visualization makes sense?
    - What narrative should accompany the data?
    """

    def __init__(self, llm_chat):
        self.llm = llm_chat

    async def interpret_results(
        self,
        user_query: str,
        sql_results: List[dict],
        metadata: Dict[str, Any]
    ) -> ReportInterpretation:
        """
        LLM interprets results and decides presentation.

        NOT just rule-based heuristics - actual reasoning.
        """

        prompt = f"""
Kullanıcı Sorusu: {user_query}

Veri Özeti:
- {len(sql_results)} satır
- Sütunlar: {', '.join(sql_results[0].keys()) if sql_results else 'yok'}
- İlk birkaç satır: {sql_results[:3] if sql_results else 'yok'}

Görevin:
1. Bu veriyi kullanıcıya nasıl sunmalıyız?
2. Görselleştirme gerekli mi? Hangi tip?
3. Hangi narrative eşlik etmeli?

Karar Kriterleri:
- Kullanıcı açıkça bir format istedi mi? (liste, tablo, grafik)
- Veri görselleştirmeye uygun mu? (numeric data, reasonable row count)
- En iyi anlatım yöntemi nedir?

Cevap formatı (JSON):
{{
    "presentation_type": "table" | "simple_list" | "single_value" | "chart",
    "chart_type": "bar" | "pie" | "line" | null,
    "reasoning": "Neden bu format seçildi?",
    "narrative": "Kullanıcıya gösterilecek açıklama",
    "should_offer_alternatives": true/false,
    "alternative_formats": ["format1", "format2"]
}}
"""

        response = await self.llm.ainvoke(prompt)
        interpretation = self._parse_interpretation(response)

        return interpretation
```

**Example:**

```
User: "En çok satan 5 ürün"
Results: [
    {"product": "A", "sales": 1000},
    {"product": "B", "sales": 850},
    ...
]

LLM Interpretation:
{
    "presentation_type": "chart",
    "chart_type": "bar",
    "reasoning": "5 ürün ve numeric data var. Karşılaştırma için çubuk grafik ideal. Kullanıcı 'en çok' dedi, ranking görsel olarak daha etkili.",
    "narrative": "En çok satan 5 ürününüz gösteriliyor. A ürünü 1000 satışla lider konumda.",
    "should_offer_alternatives": true,
    "alternative_formats": ["Listeye dönüştür", "Pasta grafiğe çevir"]
}
```

---

### 4. Natural Language Response Generator

**Purpose:** Generate natural, helpful responses.

```python
class ResponseGenerator:
    """
    Generate natural language responses with LLM.

    NOT template-based - actual natural language generation.
    """

    def __init__(self, llm_chat):
        self.llm = llm_chat

    async def generate_response(
        self,
        user_query: str,
        report_interpretation: ReportInterpretation,
        business_context: BusinessContext,
        visualization_available: bool
    ) -> str:
        """
        Generate natural, conversational response.
        """

        prompt = f"""
Kullanıcı: {user_query}

Rapor Yorumu:
- Format: {report_interpretation.presentation_type}
- Açıklama: {report_interpretation.narrative}

Business Context:
- Soru: {business_context.business_question}
- İçgörüler: {', '.join(business_context.key_insights)}

Görselleştirme: {"Mevcut" if visualization_available else "Yok"}

Görevin: Kullanıcıya doğal, yardımcı bir yanıt oluştur.

İyi Yanıt:
- Doğal dil (şablon değil)
- İçgörüleri vurgular
- Takip soruları önerir
- Kısa ve öz (max 3-4 cümle)

Kötü Yanıt:
- "Sorgunuz işlendi" gibi robotik ifadeler
- Gereksiz detay
- Teknik jargon
"""

        response = await self.llm.ainvoke(prompt)
        return response.content
```

**Example:**

```
User: "Mart ayı satışları"

Generated Response (LLM):
"Mart ayında toplam 12,450₺ satış gerçekleştirmişsiniz. En çok satan ürün kategorisiniz
Elektronik oldu. Geçen aya göre %15 artış var. İsterseniz bu rakamları grafiğe dönüştürebilirim
veya belirli bir ürün kategorisine odaklanabiliriz."

NOT: "📊 Rapor Sonucu: 10 satır bulundu. Tip: table" (BAD - robotik)
```

---

## Token Optimization (The Smart Way)

### Where to Optimize

✅ **DO Optimize:**
1. **Schema caching** - Database schema doesn't change often
2. **Repeated identical queries** - Semantic caching
3. **Old irrelevant history** - Smart truncation
4. **Intermediate large data** - Summarize, don't store full
5. **Prompt engineering** - Concise but complete prompts

❌ **DON'T Optimize:**
1. **Business context** - Critical for understanding
2. **Recent conversation** - Needed for coherence
3. **LLM reasoning** - Core intelligence, don't skip
4. **User preferences** - Important for personalization

---

### Smart Caching Strategy

```python
class SemanticCache:
    """
    Cache based on semantic similarity, not exact match.

    "Mart ayı satışları" ≈ "Mart ayında satış raporu" → Cache hit
    """

    def __init__(self, llm_embeddings):
        self.embeddings = llm_embeddings
        self.cache = {}  # {embedding: result}
        self.threshold = 0.95  # Similarity threshold

    async def get_or_compute(
        self,
        query: str,
        compute_fn: Callable
    ) -> Any:
        """
        Get from cache if semantically similar, else compute.
        """

        # Get embedding for query
        query_embedding = await self.embeddings.aembed_query(query)

        # Check similarity with cached queries
        for cached_embedding, cached_result in self.cache.items():
            similarity = self._cosine_similarity(query_embedding, cached_embedding)

            if similarity > self.threshold:
                logger.info(f"[CACHE] Semantic hit (similarity: {similarity:.2f})")
                return cached_result

        # Cache miss - compute
        logger.info("[CACHE] Miss, computing...")
        result = await compute_fn()

        # Store in cache
        self.cache[tuple(query_embedding)] = result

        return result

    def _cosine_similarity(self, a, b):
        """Cosine similarity between two vectors."""
        import numpy as np
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
```

---

### Smart Context Window

```python
class ContextWindow:
    """
    Intelligent context windowing.

    NOT "keep last N" - actually keep RELEVANT information.
    """

    def get_relevant_context(
        self,
        current_query: str,
        full_history: List[Message],
        max_tokens: int = 2000
    ) -> List[Message]:
        """
        Select relevant context within token budget.

        Strategy:
        1. Always keep last 2 messages (immediate context)
        2. Include messages about same topic
        3. Drop old unrelated messages
        4. Respect token budget
        """

        # Always include recent
        recent = full_history[-2:]
        remaining_budget = max_tokens - self._count_tokens(recent)

        # Older messages (prioritize relevant)
        older = full_history[:-2]
        relevant_older = []

        for msg in reversed(older):  # Start from most recent
            # Check relevance (simple keyword overlap for now)
            if self._is_relevant(msg.content, current_query):
                msg_tokens = self._count_tokens([msg])

                if msg_tokens <= remaining_budget:
                    relevant_older.insert(0, msg)  # Add at beginning
                    remaining_budget -= msg_tokens
                else:
                    break  # No more budget

        return relevant_older + recent

    def _is_relevant(self, old_message: str, current_query: str) -> bool:
        """Check if old message is relevant to current query."""

        # Extract keywords (simple approach)
        old_keywords = set(old_message.lower().split())
        current_keywords = set(current_query.lower().split())

        # Remove stop words
        stop_words = {"için", "bir", "bu", "ve", "ile", "gibi", "kadar"}
        old_keywords -= stop_words
        current_keywords -= stop_words

        # Calculate overlap
        overlap = len(old_keywords & current_keywords)

        return overlap >= 2  # At least 2 shared keywords

    def _count_tokens(self, messages: List[Message]) -> int:
        """Estimate token count."""
        # Simple approximation: 1 token ≈ 4 characters for Turkish
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // 4
```

---

## Optimized Prompt Engineering

### Efficient Prompts (Still Complete)

**Bad Prompt (Wasteful):**
```
Sen bir AI asistanısın. Kullanıcıya yardımcı olmalısın. Her zaman nazik ol.
Doğru bilgi ver. Yanlış bilgi verme. Emin değilsen söyle. Kullanıcıyı dinle.
...
(500 token açıklama)

Kullanıcı şunu sordu: "Satışlar nasıl?"

Lütfen analiz et ve cevapla.
```

**Good Prompt (Efficient):**
```
Business analyst rolündesin. Satış sorgusu analiz et.

Kullanıcı: "Satışlar nasıl?"
Aktif Bağlam: Mart ayı verileri mevcut

Belirle:
1. Intent (new_query/modify/visualize)
2. Missing info
3. Suggested action

JSON formatında dön.
```

**Token savings:** 500 → 100, **but still complete**.

---

### Template-Based System Prompts

```python
SYSTEM_PROMPTS = {
    "intent_understanding": """Business analyst rolündesin. Kullanıcı intent'ini belirle.

Format (JSON):
{
    "intent_type": "...",
    "confidence": 0-1,
    "reasoning": "...",
    "extracted_info": {...}
}""",

    "report_interpretation": """Rapor yorumlayıcısısın. Sunumu belirle.

Format (JSON):
{
    "presentation_type": "chart/table/list",
    "chart_type": "bar/pie/line",
    "narrative": "...",
    "reasoning": "..."
}""",

    "response_generation": """Doğal dil yanıtı oluştur.

İlkeler:
- Conversational (robotik değil)
- İçgörü vurgula
- Kısa (3-4 cümle)
- Takip öner"""
}
```

**Benefit:** Reusable, tested, optimized prompts.

---

## Performance Targets (Realistic)

### Speed

| Component | Target | Achievable? |
|-----------|--------|-------------|
| Intent Understanding (LLM) | 300-500ms | ✅ Yes (with caching) |
| Text2SQL | 800ms | ✅ Yes |
| SQL Execution | 200ms | ✅ Yes |
| Report Interpretation (LLM) | 300-500ms | ✅ Yes |
| Visualization | 200ms | ✅ Yes |
| Response Generation (LLM) | 300-500ms | ✅ Yes |
| **TOTAL** | **2-3s** | ✅ **Realistic** |

**With caching:** 1-1.5s (semantic cache hits)

### Tokens

| Component | Tokens | Notes |
|-----------|--------|-------|
| Intent Understanding | 400-600 | Full context, worth it |
| Context Window | 500-1000 | Relevant history |
| Text2SQL | 1000-1500 | Schema + examples |
| Report Interpretation | 300-500 | Result summary |
| Response Generation | 300-500 | Context + interpretation |
| **TOTAL** | **2500-4000** | **Reasonable for quality** |

**Tradeoff:** More tokens than aggressive optimization (1800), **but much better quality**.

---

## Architecture Diagram

```
User Input: "Geçen ay İstanbul'da hangi ürünler çok sattı?"
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 1. Conversation Manager (LLM)                               │
│    → Intent: NEW_QUERY                                      │
│    → Extracted: time=last_month, location=Istanbul,         │
│                 metric=top_products                         │
│    → Confidence: 0.95                                       │
│    → Missing: None                                          │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Report Orchestrator                                      │
│    → Route to: Text2SQL Agent                               │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Text2SQL Agent (LLM)                                     │
│    → SQL: SELECT product, SUM(sales) FROM orders            │
│            WHERE city='Istanbul' AND month='last_month'     │
│            GROUP BY product ORDER BY SUM(sales) DESC        │
│    → Execute → Results: [...]                               │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Business Context Tracker (LLM)                           │
│    → Business Question: "İstanbul'da en çok satan ürünler"  │
│    → Key Insights: ["Elektronik lider", "+20% artış"]       │
│    → Follow-ups: ["Kategoriye göre detay", "Grafiğe çevir"]│
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Report Interpreter (LLM)                                 │
│    → Presentation: CHART (bar)                              │
│    → Reasoning: "5 ürün, numeric, ranking → bar chart"      │
│    → Narrative: "En çok satan 5 ürün gösteriliyor..."       │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Visualization Agent                                      │
│    → Generate bar chart (Plotly)                            │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Response Generator (LLM)                                 │
│    → Natural response: "İstanbul'da geçen ay en çok         │
│      Elektronik kategorisi sattı. Önceki aya göre %20       │
│      artış var. Detaya inmek ister misiniz?"                │
└─────────────────────────────────────────────────────────────┘
    ↓
User receives: Natural response + Chart + Follow-up suggestions
```

---

## Summary

### Core Principles

1. **LLM is the brain** - Understanding, reasoning, generation
2. **Business context matters** - Not just technical state
3. **Conversation is key** - Natural interaction, not commands
4. **Smart optimization** - Where it makes sense, not everywhere

### What Changed from Token-Optimized Version

| Aspect | Token-Optimized (Wrong) | LLM-Driven (Right) |
|--------|-------------------------|---------------------|
| **Intent** | 95% pattern matching | LLM understanding with context |
| **Context** | Last 3 messages (blind) | Relevant messages (smart) |
| **Visualization** | Pure rules | LLM-assisted reasoning |
| **Response** | Templates | Natural language generation |
| **Business Logic** | ❌ Missing | ✅ Central to system |
| **Tokens** | 1300-1800 | 2500-4000 (worth it) |
| **Speed** | 1.15s | 2-3s (acceptable) |
| **Quality** | ⭐⭐ Static | ⭐⭐⭐⭐⭐ Intelligent |

### Performance (Realistic)

- **Speed:** 2-3s (< 10s target ✅)
- **Tokens:** 2500-4000 (reasonable for quality ✅)
- **Accuracy:** High (LLM reasoning ✅)
- **User Experience:** Natural conversation ✅

**This is the RIGHT architecture** - intelligent, conversational, business-aware.
