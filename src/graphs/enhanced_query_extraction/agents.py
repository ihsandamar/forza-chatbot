
##Agents for Enhanced Query Extraction Graph

import time
import re
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage, HumanMessage
from langchain_community.utilities import SQLDatabase
from src.config.business_terms_config import business_config
from .tools import (
    table_data_extraction_tool, 
    context_analysis_tool, 
    prompt_builder_tool, 
    response_parser_tool,
    distinct_value_replacement_tool
)
from .models import EnhancedText2SQLState


class TableDataAgent:
        # Agent for table data extraction and schema preparation
    
    def __init__(self, db: SQLDatabase, logger):
        self.db = db
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
            # Execute table data extraction workflow
        #  Ensure state is properly initialized
        if state is None:
            state = {}
        if "messages" not in state:
            state["messages"] = []
        if "agent_results" not in state or state["agent_results"] is None:
            state["agent_results"] = {}
            
        state["current_agent"] = "table_data_agent"
        
        try:
            configurable = config.get("configurable", {})
            assistant_config = configurable.get("assistant_config", {})
            
            # Debug logging
            print(f"DEBUG TableDataAgent - configurable: {configurable}")
            print(f"DEBUG TableDataAgent - assistant_config: {assistant_config}")
            
            table_name = assistant_config.get("table_name", "")
            config_columns = assistant_config.get("table_columns", [])
            max_distinct_values = assistant_config.get("max_distinct_values", business_config.get_max_distinct_values())
            
            print(f"DEBUG TableDataAgent - table_name: {table_name}")
            print(f"DEBUG TableDataAgent - config_columns count: {len(config_columns)}")
            
            # If no table configuration provided, use auto-discovery
            if not table_name or not config_columns:
                self.logger.info("No table configuration provided, using auto-discovery")
                # Get table names from database
                table_names = self.db.get_usable_table_names()
                if table_names:
                    table_name = table_names[0]  # Use first available table
                    self.logger.info(f"Auto-discovered table: {table_name}")
                else:
                    error_msg = "No tables found in database"
                    state["errors"] = {"error_message": error_msg}
                    return state
            
            #  Use table data extraction tool
            tool_result = table_data_extraction_tool.invoke({
                "table_name": table_name,
                "table_columns": config_columns,
                "max_distinct_values": max_distinct_values,
                "db_connection": self.db
            })
            
            state["table_info"] = tool_result
            
            columns = tool_result.get("columns", [])
            searchable_columns = [col["name"] for col in columns if col.get("distinct_values")]
            
            #  Debug log for distinct values
            distinct_summary = []
            for col in columns:
                col_name = col.get("name", "")
                distinct_vals = col.get("distinct_values", [])
                if distinct_vals:
                    distinct_summary.append(f"{col_name}: {len(distinct_vals)} values")
                    self.logger.info(f"Column {col_name} has {len(distinct_vals)} distinct values: {distinct_vals[:5]}...")
            
            success_msg = "Tablo semasi basariyla cekildi:\n\n"
            success_msg += f"- **Tablo:** {table_name}\n"
            success_msg += f"- **Kolonlar:** {len(columns)} adet\n"
            success_msg += f"- **Aranabilir Kolonlar:** {len(searchable_columns)} adet\n\n"
            success_msg += "**Distinct degerler cekilen kolonlar:**\n"
            success_msg += chr(10).join(distinct_summary) if distinct_summary else 'Henuz distinct deger cekilmedi'
            
            state["extraction_result"] = success_msg
            state["messages"].append(AIMessage(content=success_msg))
            
            #  Store agent results - ensure state is properly initialized
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
            
            state["agent_results"]["table_data_agent"] = {
                "status": "success",
                "table_name": table_name,
                "total_columns": len(columns),
                "searchable_columns": len(searchable_columns),
                "execution_time": time.time()
            }
            
            self.logger.info("Table data extraction completed successfully")
            return state
            
        except Exception as e:
            error_msg = f"Table data extraction failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=f"* {error_msg}"))
            
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
            
            state["agent_results"]["table_data_agent"] = {
                "status": "error", 
                "error": str(e),
                "execution_time": time.time()
            }
            
            self.logger.error(f"Table data extraction failed: {e}")
            return state


class ContextAnalysisAgent:
        # Agent for analyzing conversation context and flow
    
    def __init__(self, logger):
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
            # Execute context analysis workflow
        #  Ensure state is properly initialized
        if state is None:
            state = {}
        if "messages" not in state:
            state["messages"] = []
        if "agent_results" not in state or state["agent_results"] is None:
            state["agent_results"] = {}
            
        state["current_agent"] = "context_analysis_agent"
        
        try:
            all_messages = state.get("messages", [])
            
            #  Simplified: Get only the current/last human message
            human_messages = [
                msg for msg in all_messages 
                if isinstance(msg, HumanMessage) or 
                (hasattr(msg, 'type') and msg.type == 'human') or
                (hasattr(msg, '__class__') and 'Human' in msg.__class__.__name__)
            ]
            
            #  Get current message content
            current_message = ""
            if human_messages:
                last_msg = human_messages[-1]
                if hasattr(last_msg, 'content'):
                    current_message = str(last_msg.content)
                else:
                    current_message = str(last_msg)
            
            #  Simplified context data - only current message, no conversation history
            context_result = {
                "current_message": current_message,
                "total_tokens": len(current_message.split()) * 4,  # Rough estimation
                "has_previous_results": False,  # Always false for new_query mode
                "key_entities": [],
                "topics": [],
                "recent_context": [],
                "conversation_summary": "",
                "flow_words": [],
                "pronoun_references": [],
                "query_references": [],
                "topic_continuity": False,
                "entity_continuity": []
            }
            
            state["context_data"] = context_result
            
            human_message_count = len(human_messages)
            current_tokens = context_result.get("total_tokens", 0)
            
            summary = "Konusma baglami (sadece mevcut mesaj):\n\n"
            summary += f"- **Mevcut mesaj:** \"{current_message[:100]}{'...' if len(current_message) > 100 else ''}\"\n"
            summary += f"- **Token kullanimi:** {current_tokens}\n"
            summary += "- **Mod:** Yeni sorgu (baglam analizi devre disi)\n"
            summary += f"- **Toplam human mesajlari:** {human_message_count} adet"
            
            state["analysis_result"] = summary
            state["messages"].append(AIMessage(content=summary))
            
            #  Store agent results
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["context_analysis_agent"] = {
                "status": "success",
                "mode": "new_query_only",
                "human_messages_count": human_message_count,
                "current_message_length": len(current_message),
                "total_tokens": current_tokens,
                "has_previous_results": False,
                "execution_time": time.time()
            }
            
            self.logger.info(f"Context analysis simplified - current message only ({len(current_message)} chars, {current_tokens} tokens)")
            return state
            
        except Exception as e:
            error_msg = f"Context analysis failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=f"* {error_msg}"))
            
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["context_analysis_agent"] = {
                "status": "error",
                "error": str(e),
                "execution_time": time.time()
            }
            
            total_messages = len(state.get("messages", []))
            human_count = len([m for m in state.get("messages", []) if isinstance(m, HumanMessage)])
            self.logger.error(f"Context analysis failed: {e} (Total messages: {total_messages}, Human: {human_count})")
            return state


class IntentAnalysisAgent:
        # Agent for analyzing user intent and conversation type using template-based prompting
    
    def __init__(self, llm, logger, assistant_configuration=None):
        self.llm = llm
        self.logger = logger
        self.assistant_configuration = assistant_configuration
        self._initialize_templates()
        
    def _initialize_templates(self):
            # Initialize prompt templates - simplified for new_query only mode
        self.templates = {
            "entity_extraction": {
                "system": """Sen uzman bir SQL entity cikarma asistanisin. Kullanicinin Turkce sorgusundaki tum onemli entity'leri analiz et ve veritabani kolonlariyla eslestir.""",
                "user": """*� KULLANICI SORGUSU: {current_message}

*�* VERITABANI KOLONLARI (İsim, Tip, Açıklama):
{column_matching_info}

📋 KOLON TİP REHBERİ:
- **NVARCHAR/VARCHAR**: Metin kolonları (firma adı, ürün adı, açıklama)
- **INT/BIGINT**: Sayısal kolonlar (ID, miktar, adet)
- **DECIMAL/MONEY**: Para ve ondalık sayılar (fiyat, tutar)
- **DATETIME/DATE**: Tarih ve zaman kolonları
- **BIT**: Boolean değerler (aktif/pasif, true/false)

*� ANALIZ GOREVLERI:

🎯 ENTITY TYPE BELİRLEME (ÇOK ÖNEMLİ - SELECT'E ÖNCELIK VER):

1*⃣ SELECT ENTITIES (Kullanıcının GÖRMEK istediği veriler - filtreleme YOK):
   ├─ GENEL LİSTELEME: "ürünler", "firmalar", "müşteriler", "fiyatlar", "durumlar"
   ├─ GÖRÜNTÜLEME AMACİ: "hangi ürünler", "firma adları", "müşteri listesi"
   ├─ KOLON GÖSTERİMİ: Kullanıcı o kolonu görmek istiyor ama spesifik değer aramıyor
   └─ ÖZET AMAÇ: "tüm ürünler", "mevcut firmalar" (filtreleme değil, listeleme)

2*⃣ VALUE ENTITIES (WHERE koşulları için spesifik değer filtrelemesi):
   ├─ KESIN FİLTRE: Spesifik firma/ürün: "Aksa Elektrik firması", "Coca Cola"
   ├─ TARİH FİLTRE: "temmuz 2025", "2024 yılında", "bu ay"
   ├─ DURUM FİLTRE: "aktif durum", "iptal edilmiş", "onaylanmış"
   └─ SPESIFIK DEĞ: Belirli bir değeri arayan entity'ler

3*⃣ STRUCTURAL ENTITIES (SQL yapısı - gruplama/sıralama/aggregation):
   ├─ GROUP BY: "kategoriye göre", "müşteriye göre", "aylık"
   ├─ ORDER BY: "sıralı", "tersten", "büyükten küçüğe"
   ├─ TOPLAMA: "toplam", "sum" → SUM(kolon)
   ├─ SAYMA: "adet", "kaç tane", "count" → COUNT(kolon)
   ├─ ORTALAMA: "ortalama", "average" → AVG(kolon)
   └─ MIN/MAX: "en büyük", "minimum", "en fazla" → MAX/MIN(kolon)

🧠 ENTITY TYPE KARAR AĞACI:
```
SORU: Kullanıcı bu entity ile ne yapmak istiyor?

├─ GÖRÜNTÜLEME/LİSTELEME → entity_type = "select"
│  └─ "ürünleri göster", "hangi firmalar", "müşteri listesi"
│
├─ FİLTRELEME/ARAMA → entity_type = "value"  
│  └─ "Aksa firması", "sadece aktif durumlar", "temmuz ayı"
│
└─ HESAPLAMA/GRUPLAMA → entity_type = "structural"
   └─ "toplam", "sayısı", "kategoriye göre", "en fazla"
```

*� KOLON ESLESTIRME STRATEJISI:
   - Description'lara dikkat et 
   - Kolon tiplerini degerlendir (varchar → text, int → sayilar)
   - Kolon isimlerinden anlam cikar 
   - Benzer isimleri yakala
* DİKKAT ETMEN ÖNEMLİ NOKTALAR:
   - eğer entity_keyword için birden fazla kolon öneriyorsan, her kolon için similarity_score ver (0.5-1.0 arası)
   
   ** REQUIRES_VALUE_MATCHING KURALLARI (ÇOK ÖNEMLİ):
   ├─ TRUE: SADECE değer filtrelemesi gereken entity'ler için (WHERE koşulu gerektirir)
   │  └─ Örnekler: "Aksa firması", "2025 yılı", "aktif durum", "soda ürünü", "temmuz ayı"
   ├─ FALSE: SELECT/görüntüleme amaçlı entity'ler için (filtreleme gerektirmez)
   │  ├─ SELECT entities: "firma adı", "ürün listesi", "durumlar", "fiyatlar" 
   │  ├─ STRUCTURAL entities: "toplam", "sayı", "hangi", "listele"
   │  └─ Aggregation entities: "kaç", "en fazla", "ortalama", "minimum"
   
   ** ENTITY_TYPE BAZLI REQUIRES_VALUE_MATCHING:
   ├─ "select": requires_value_matching = FALSE (görüntüleme amaçlı)
   ├─ "structural": requires_value_matching = FALSE (gruplama/sıralama amaçlı) 
   └─ "value": requires_value_matching = TRUE (filtreleme amaçlı)
   
   - Birden fazla kolon seçmede esnek ol
   - Semantik olarak kullanıcının istediği select kolonlarını belirle ve nvarchar alanları seçme eğiliminde ol.
   - Select kolonları kullanıcının görmek istediği alanları semantik olarak olabildiğince fazla seç ve STRUCTURAL ENTITIESleri de ekle. 
** ISLEM SIRASI:
   1. Sorgudaki tum entity'leri belirle (kesin + fuzzy/possibility)
   2. KESIN entities: net eslesen ifadeler (0.8+ score)
   3. FUZZY/POSSIBILITY entities: belirsiz ifadeler - birden fazla kolon potansiyeli
   4. Her entity icin confidence_level belirle: "definite"|"fuzzy"|"possibility" 
   5. Fuzzy entities icin tum potansiyel kolonlari ekle (0.5+ score)
   6. Sonraki agent bu confidence'lara gore distinct value kontrolu yapacak

*� CIKTI FORMATI:
{{"entities": [
  {{"entity_keyword": "sorgudaki_tam_ifade", "entity_type": "value|structural|select", "confidence_level": "definite|fuzzy|possibility", "suggested_columns": [
    {{"column_name": "kolon_adi", "similarity_score": 0.5-1.0}}
  ], "requires_value_matching": true/false, "aggregation_function": "sum|count|avg|max|min|none", "pagination_limit": null/number, "complex_pattern": null/object}}
]}}

*� COMPLEX_PATTERN OBJESI (karmasik sorgular icin):
{{"complex_pattern": {{"type": "superlative|ranking|comparison", "requires_order_by": true/false, "order_direction": "desc|asc", "combined_entities": ["related_entity_keywords"]}}}}

COMPLEX PATTERN TIPLERI:
- superlative: "en cok", "en az", "ilk", "son" → TOP 1 + ORDER BY
- ranking: "hangi", "siralamasi" → ORDER BY + optionally TOP N  
- comparison: "daha fazla", "karsilastir" → HAVING/WHERE karsilastirmasi

*� ORNEKLER (SELECT ÖNCELİKLİ):

*� ORNEK 1 - SELECT ENTITIES (Görüntüleme amaçlı):
Sorgu: "ürünler ve fiyatları"
{{"entities": [
  {{"entity_keyword": "ürünler", "entity_type": "select", "confidence_level": "definite", "suggested_columns": [{{"column_name": "ProductName", "similarity_score": 0.9}}, {{"column_name": "ProductId", "similarity_score": 0.7}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "fiyatları", "entity_type": "select", "confidence_level": "definite", "suggested_columns": [{{"column_name": "UnitPrice", "similarity_score": 0.9}}, {{"column_name": "TotalAmount", "similarity_score": 0.8}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}}
]}}

*� ORNEK 2 - VALUE ENTITIES (Filtreleme amaçlı):
Sorgu: "Aksa Elektrik firmasının 2025 temmuz işlemleri"
{{"entities": [
  {{"entity_keyword": "Aksa Elektrik", "entity_type": "value", "confidence_level": "definite", "suggested_columns": [{{"column_name": "CariAdi", "similarity_score": 0.9}}], "requires_value_matching": true, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "2025 temmuz", "entity_type": "value", "confidence_level": "definite", "suggested_columns": [{{"column_name": "DocumentDate", "similarity_score": 0.9}}], "requires_value_matching": true, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}}
]}}

*� ORNEK 3 - KARMA (Select + Value):
Sorgu: "hangi ürünler enerji kategorisinde"
{{"entities": [
  {{"entity_keyword": "ürünler", "entity_type": "select", "confidence_level": "definite", "suggested_columns": [{{"column_name": "ProductName", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "enerji", "entity_type": "value", "confidence_level": "fuzzy", "suggested_columns": [{{"column_name": "CategoryName", "similarity_score": 0.8}}, {{"column_name": "ProductName", "similarity_score": 0.6}}], "requires_value_matching": true, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}}
]}}

*� ORNEK 4 - STRUCTURAL ENTITIES:
Sorgu: "ürün sayısı kategoriye göre"
{{"entities": [
  {{"entity_keyword": "ürün sayısı", "entity_type": "structural", "confidence_level": "definite", "suggested_columns": [{{"column_name": "ProductName", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "count", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "kategoriye göre", "entity_type": "structural", "confidence_level": "definite", "suggested_columns": [{{"column_name": "CategoryName", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}}
]}}

*� ORNEK 5 - KARMASIK SUPERLATIVE SORGU:
Sorgu: "En çok sade soda satan firma hangisidir?"
{{"entities": [
  {{"entity_keyword": "firma", "entity_type": "select", "confidence_level": "definite", "suggested_columns": [{{"column_name": "CariAdi", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "sade soda", "entity_type": "value", "confidence_level": "definite", "suggested_columns": [{{"column_name": "ProductName", "similarity_score": 0.9}}], "requires_value_matching": true, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "En çok satan", "entity_type": "structural", "confidence_level": "definite", "suggested_columns": [{{"column_name": "Quantity", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "sum", "pagination_limit": 1, "complex_pattern": {{"type": "superlative", "requires_order_by": true, "order_direction": "desc", "combined_entities": ["firma"]}}}}
]}}

*� ORNEK 6 - RANKING SORGU:
Sorgu: "Hangi kategoriler en fazla ciro yapıyor, ilk 5"
{{"entities": [
  {{"entity_keyword": "kategoriler", "entity_type": "select", "confidence_level": "definite", "suggested_columns": [{{"column_name": "CategoryName", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": null, "complex_pattern": null}},
  {{"entity_keyword": "en fazla ciro", "entity_type": "structural", "confidence_level": "definite", "suggested_columns": [{{"column_name": "RowAmount", "similarity_score": 0.9}}], "requires_value_matching": false, "aggregation_function": "sum", "pagination_limit": null, "complex_pattern": {{"type": "ranking", "requires_order_by": true, "order_direction": "desc", "combined_entities": ["kategoriler"]}}}},
  {{"entity_keyword": "ilk 5", "entity_type": "structural", "confidence_level": "definite", "suggested_columns": [], "requires_value_matching": false, "aggregation_function": "none", "pagination_limit": 5, "complex_pattern": null}}
]}}

[WARNING] ÖNEMLİ HATIRLATMA:
- "ürünler", "firmalar", "kategoriler" → entity_type = "select", requires_value_matching = false
- "Aksa firması", "sade soda" → entity_type = "value", requires_value_matching = true  
- "en fazla", "toplam", "sayısı" → entity_type = "structural", requires_value_matching = false""",
            }
        }
    
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
            # Execute intent analysis using template-based approach
        #  Ensure state is properly initialized
        if state is None:
            state = {}
        if "messages" not in state:
            state["messages"] = []
        if "agent_results" not in state or state["agent_results"] is None:
            state["agent_results"] = {}
            
        state["current_agent"] = "intent_analysis_agent"
        
        try:
            context_data = state.get("context_data", {})
            table_info = state.get("table_info", {})
            
            self.logger.info(f"Intent analysis starting - context_data available: {bool(context_data)}")
            self.logger.info(f"Context data keys: {list(context_data.keys()) if context_data else 'None'}")
            
            if not context_data:
                raise Exception("Context data not found - run context analysis first")
            
            #  Step 1: Analyze conversation type
            conversation_analysis = self._analyze_conversation_type(context_data)
            
            #  Step 2: Analyze intent category  
            intent_analysis = self._analyze_intent_category(
                context_data, conversation_analysis.get("conversation_type", "new_query")
            )
            
            #  Step 3: Extract entities
            self.logger.info("Starting entity extraction...")
            entity_analysis = self._extract_entities(context_data, table_info)
            self.logger.info(f"Entity analysis completed. Result: {entity_analysis}")
            self.logger.info(f"Entities found: {len(entity_analysis.get('entities', []))} entities")
            
            #  Combine results
            intent_data = {
                **conversation_analysis,
                **intent_analysis,
                **entity_analysis,
                "reasoning": self._generate_reasoning(conversation_analysis, intent_analysis, entity_analysis)
            }
            
            self.logger.info(f"Final intent_data entities: {intent_data.get('entities', [])}")
            
            state["intent_data"] = intent_data
            
            #  Generate summary
            conversation_type = intent_data.get("conversation_type", "unknown")
            confidence = intent_data.get("confidence", 0.0)
            intent_category = intent_data.get("intent_category", "unknown")
            entities = intent_data.get("entities", [])
            
            summary = "Intent analizi tamamlandi:\n\n"
            summary += f"- **Konusma Turu:** {conversation_type}\n"
            summary += f"- **Guven Skoru:** {confidence:.2f}\n"
            summary += f"- **Intent Kategorisi:** {intent_category}\n"
            summary += f"- **Tespit Edilen Varliklar:** {len(entities)} adet\n\n"
            summary += f"**Reasoning:** {intent_data.get('reasoning', 'Template-based analysis completed')}"
            
            state["messages"].append(AIMessage(content=summary))
            
            #  Store agent results
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["intent_analysis_agent"] = {
                "status": "success",
                "conversation_type": conversation_type,
                "confidence": confidence,
                "intent_category": intent_category,
                "entities_count": len(intent_data.get('entities', [])),
                "execution_time": time.time()
            }
            
            self.logger.info(f"Intent analysis completed: {conversation_type} ({confidence:.2f})")
            return state
            
        except Exception as e:
            error_msg = f"Intent analysis failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=f"* {error_msg}"))
            
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["intent_analysis_agent"] = {
                "status": "error",
                "error": str(e),
                "execution_time": time.time()
            }
            
            self.logger.error(f"Intent analysis failed: {e}")
            return state

    def _analyze_conversation_type(self, context_data: Dict) -> Dict:
            # Always return new_query - simplified for single query processing
        self.logger.info("Conversation type analysis simplified - returning new_query")
        return {
            "conversation_type": "new_query", 
            "confidence": 1.0
        }
    
    def _analyze_intent_category(self, context_data: Dict, conversation_type: str) -> Dict:
            # Simplified intent category - always return data_retrieval for new_query mode
        self.logger.info("Intent category analysis simplified - returning data_retrieval")
        return {
            "intent_category": "data_retrieval",
            "intent_confidence": 1.0
        }
    
    def _get_column_semantic_context(self, col_name: str, col_type: str, col_description: str, sample_values: List) -> str:
            # Generate semantic context for column based on type, name, and sample values
        context_parts = []
        
        #  Date/DateTime columns
        if "datetime" in col_type.lower() or "date" in col_type.lower():
            if sample_values and any("datetime" in str(v) for v in sample_values):
                context_parts.append("TARIH/SAAT (tam tarih verisi - ay/yil icin kismi eslestirme yapilabilir)")
            else:
                context_parts.append("TARIH kolonu")
        
        #  Text/String columns with specific patterns
        elif "nvarchar" in col_type.lower() or "varchar" in col_type.lower():
            #  Company/Customer names
            if any(keyword in col_name.lower() for keyword in ["cari", "customer", "firma", "company"]):
                context_parts.append("FIRMA/MUSTERI adi (kismi eslestirme - 'dogal' → 'DOGALGAZ A.S.')")
            #  Product names
            elif any(keyword in col_name.lower() for keyword in ["product", "urun", "item"]):
                context_parts.append("URUN adi (kismi/fuzzy eslestirme)")
            #  Category names
            elif any(keyword in col_name.lower() for keyword in ["category", "kategori"]):
                context_parts.append("KATEGORI adi")
            #  General text
            else:
                context_parts.append("METIN verisi")
        
        #  Numeric columns
        elif any(t in col_type.lower() for t in ["int", "decimal", "float", "money"]):
            if "tutar" in col_name.lower() or "amount" in col_name.lower():
                context_parts.append("TUTAR (sayisal karsilastirma - >, <, = operatorleri)")
            elif "quantity" in col_name.lower() or "miktar" in col_name.lower():
                context_parts.append("MIKTAR (sayisal)")
            elif "id" in col_name.lower():
                context_parts.append("ID (kimlik numarasi)")
            else:
                context_parts.append("SAYISAL veri")
        
        #  Boolean/Bit columns
        elif "bit" in col_type.lower():
            context_parts.append("DOGRU/YANLIS (1/0)")
        
        #  Add sample values hint if available
        if sample_values:
            sample_str = ", ".join(str(v)[:20] for v in sample_values[:3])
            context_parts.append(f"Ornek: {sample_str}")
        
        result = " | ".join(context_parts) if context_parts else ""
        # Escape curly braces to prevent template formatting issues
        return result.replace("{", "{{").replace("}", "}}")
    
    def _extract_entities(self, context_data: Dict, table_info: Dict) -> Dict:
            # Extract entities using template
        current_message = context_data.get("current_message", "")
        
        #  Build table context
        table_context = ""
        if table_info and table_info.get("columns"):
            searchable_columns = [
                col["name"] for col in table_info["columns"][:10] 
                if col.get("distinct_values")
            ]
            table_context = f"Kolonlar: {', '.join(searchable_columns)}"
        
        #  Build column matching info with semantic context for better matching
        column_matching_info = ""
        if table_info and table_info.get("columns"):
            column_details = []
            for col in table_info["columns"]:  # Show all columns
                col_name = col.get("name", "")
                col_type = col.get("data_type", "")
                col_description = col.get("description", "")
                distinct_values = col.get("distinct_values", [])
                
                #  Skip empty column names
                if not col_name:
                    continue
                
                #  Build detailed column info with semantic context
                col_info_parts = [f"[{col_name}]"]
                if col_type:
                    col_info_parts.append(f"({col_type})")
                if col_description:
                    col_info_parts.append(f"- {col_description}")
                
                #  Add semantic matching context based on column type and content
                semantic_context = self._get_column_semantic_context(col_name, col_type, col_description, distinct_values[:5])
                if semantic_context:
                    col_info_parts.append(f"| SEMANTIK: {semantic_context}")
                
                column_details.append(" ".join(col_info_parts))
            
            column_matching_info = "\n".join(column_details)
        
        template = self.templates["entity_extraction"]
        system_part = template["system"]
        user_part = template["user"].format(
            current_message=current_message,
            table_context=table_context or "Tablo bilgisi yok",
            column_matching_info=column_matching_info or "Sutun eslestirme bilgisi yok"
        )
        prompt = system_part + "\n\n" + user_part

        self.logger.info(f"Built entity extraction prompt. Length: {len(prompt)} chars")
        self.logger.info(f"Prompt preview: {prompt[:200]}...")

        try:
            self.logger.info(f"Sending entity extraction prompt for: '{current_message}'")
            response = self.llm.get_chat().invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            self.logger.info(f"Entity extraction LLM response: {response_text[:300]}...")
            
            # Clean response text - remove markdown code blocks if present
            clean_text = response_text.strip()
            
            # Remove markdown json code blocks
            if clean_text.startswith('```json'):
                self.logger.info("Removing markdown code block wrapper from entity extraction response")
                clean_text = clean_text.replace('```json', '').replace('```', '').strip()
            elif clean_text.startswith('```'):
                self.logger.info("Removing generic code block wrapper from entity extraction response")
                clean_text = clean_text.replace('```', '').strip()
            
            try:
                result = json.loads(clean_text)
                entities = result.get("entities", [])
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON parsing failed in entity extraction: {e}")
                self.logger.error(f"Cleaned text preview: {clean_text[:200]}...")
                # Try regex fallback
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        entities = result.get("entities", [])
                        self.logger.info("Successfully extracted JSON with regex in entity extraction")
                    except json.JSONDecodeError:
                        self.logger.error("Regex extracted text is not valid JSON in entity extraction")
                        entities = []
                else:
                    self.logger.error("No valid JSON found in entity extraction response")
                    entities = []
            
            self.logger.info(f"Extracted {len(entities)} entities: {entities}")
            
            return {
                "entities": entities
            }
            
        except Exception as e:
            self.logger.error(f"Entity extraction failed: {e}")
            self.logger.error(f"Error type: {type(e).__name__}")
            self.logger.error(f"Current message length: {len(current_message)} chars")
            self.logger.error(f"Table info available: {bool(table_info)}")
            self.logger.error(f"Column matching info length: {len(column_matching_info)} chars")
            return {"entities": []}
    
    def _generate_reasoning(self, conversation_analysis: Dict, intent_analysis: Dict, entity_analysis: Dict) -> str:
            # Generate reasoning for the analysis
        reasoning_parts = []
        
        #  Conversation type reasoning
        conv_type = conversation_analysis.get("conversation_type", "unknown")
        conv_confidence = conversation_analysis.get("confidence", 0.0)
        reasoning_parts.append(f"Konusma turu '{conv_type}' ({conv_confidence:.2f} guven)")
        
        #  Intent category reasoning
        intent_cat = intent_analysis.get("intent_category", "unknown")
        intent_confidence = intent_analysis.get("intent_confidence", 0.0)
        reasoning_parts.append(f"Intent '{intent_cat}' ({intent_confidence:.2f} guven)")
        
        #  Entity reasoning
        entities = entity_analysis.get("entities", [])
        if entities:
            entity_keywords = [e.get("entity_keyword", "") for e in entities[:3]]
            reasoning_parts.append(f"{len(entities)} varlik tespit edildi: {', '.join(entity_keywords)}")
        else:
            reasoning_parts.append("Varlik tespit edilmedi")
        
        return " | ".join(reasoning_parts)


class QueryEnhancementAgent:
        # Agent for enhancing user queries by replacing terms with actual distinct values from database
    
    def __init__(self, llm, db, logger, assistant_configuration=None):
        self.llm = llm
        self.db = db
        self.logger = logger
        self.assistant_configuration = assistant_configuration
    
    def _get_column_semantic_context(self, col_name: str, col_type: str, col_description: str, sample_values: List) -> str:
            # Generate semantic context for column based on type, name, and sample values
        context_parts = []
        
        #  Date/DateTime columns
        if "datetime" in col_type.lower() or "date" in col_type.lower():
            if sample_values and any("datetime" in str(v) for v in sample_values):
                context_parts.append("TARIH/SAAT (tam tarih verisi - ay/yil icin kismi eslestirme yapilabilir)")
            else:
                context_parts.append("TARIH kolonu")
        
        #  Text/String columns with specific patterns
        elif "nvarchar" in col_type.lower() or "varchar" in col_type.lower():
            #  Company/Customer names
            if any(keyword in col_name.lower() for keyword in ["cari", "customer", "firma", "company"]):
                context_parts.append("FIRMA/MUSTERI adi (kismi eslestirme - 'dogal' → 'DOGALGAZ A.S.')")
            #  Product names
            elif any(keyword in col_name.lower() for keyword in ["product", "urun", "item"]):
                context_parts.append("URUN adi (kismi/fuzzy eslestirme)")
            #  Category names
            elif any(keyword in col_name.lower() for keyword in ["category", "kategori"]):
                context_parts.append("KATEGORI adi")
            #  General text
            else:
                context_parts.append("METIN verisi")
        
        #  Numeric columns
        elif any(t in col_type.lower() for t in ["int", "decimal", "float", "money"]):
            if "tutar" in col_name.lower() or "amount" in col_name.lower():
                context_parts.append("TUTAR (sayisal karsilastirma - >, <, = operatorleri)")
            elif "quantity" in col_name.lower() or "miktar" in col_name.lower():
                context_parts.append("MIKTAR (sayisal)")
            elif "id" in col_name.lower():
                context_parts.append("ID (kimlik numarasi)")
            else:
                context_parts.append("SAYISAL veri")
        
        #  Boolean/Bit columns
        elif "bit" in col_type.lower():
            context_parts.append("DOGRU/YANLIS (1/0)")
        
        #  Add sample values hint if available
        if sample_values:
            sample_str = ", ".join(str(v)[:20] for v in sample_values[:3])
            context_parts.append(f"Ornek: {sample_str}")
        
        result = " | ".join(context_parts) if context_parts else ""
        # Escape curly braces to prevent template formatting issues
        return result.replace("{", "{{").replace("}", "}}")
    
    def _create_natural_replacement(self, target_column: str, sql_pattern: str, entity_keyword: str) -> str:
        """Parse SQL pattern and create natural language replacement"""
        import re
        try:
            # LIKE patterns
            if "LIKE" in sql_pattern.upper():
                # Extract pattern from LIKE '%pattern%'
                like_match = re.search(r"LIKE\s*'%([^%]+)%'", sql_pattern, re.IGNORECASE)
                if like_match:
                    pattern = like_match.group(1)
                    return f"[{target_column}] '{pattern}' iceren ({sql_pattern})"
                else:
                    return f"[{target_column}] pattern iceren ({sql_pattern})"
            
            # YEAR and MONTH combined patterns
            elif "YEAR" in sql_pattern and "MONTH" in sql_pattern:
                # Extract year and month from pattern like "YEAR([col]) = 2025 AND MONTH([col]) = 7"
                year_match = re.search(r"YEAR\([^)]+\)\s*=\s*(\d+)", sql_pattern)
                month_match = re.search(r"MONTH\([^)]+\)\s*=\s*(\d+)", sql_pattern)
                if year_match and month_match:
                    year = year_match.group(1)
                    month = month_match.group(1)
                    return f"[{target_column}] {year} yili {month}. ayinda olan ({sql_pattern})"
                else:
                    return f"[{target_column}] yil ve ay filtreleme ({sql_pattern})"
            
            # YEAR only patterns
            elif "YEAR" in sql_pattern.upper():
                year_match = re.search(r"YEAR\([^)]+\)\s*=\s*(\d+)", sql_pattern)
                if year_match:
                    year = year_match.group(1)
                    return f"[{target_column}] {year} yilinda olan ({sql_pattern})"
                else:
                    return f"[{target_column}] yili filtreleme ({sql_pattern})"
            
            # MONTH only patterns  
            elif "MONTH" in sql_pattern.upper():
                month_match = re.search(r"MONTH\([^)]+\)\s*=\s*(\d+)", sql_pattern)
                if month_match:
                    month = month_match.group(1)
                    return f"[{target_column}] {month}. ayinda olan ({sql_pattern})"
                else:
                    return f"[{target_column}] ayi filtreleme ({sql_pattern})"
            
            # Exact match patterns (= 'value')
            elif sql_pattern.strip().startswith("="):
                value_match = re.search(r"=\s*'([^']+)'", sql_pattern)
                if value_match:
                    value = value_match.group(1)
                    return f"[{target_column}] '{value}' olan ({sql_pattern})"
                else:
                    return f"[{target_column}] degeri olan ({sql_pattern})"
            
            # Default fallback
            else:
                return f"[{target_column}] filtreleme ({sql_pattern})"
                
        except Exception as e:
            # Fallback in case of any parsing error
            return f"[{target_column}] filtreleme ({sql_pattern})"
    
    def _initialize_templates(self):
            # Initialize templates for query enhancement
            self.templates = {
    "entity_distinct_matching": {
        "system": """Sen uzman bir entity-value eşleştirme asistanısın. Kullanıcı entity'lerini veritabanı değerleriyle BAĞLAMSAL ANLAYışA ve AMACA DAYALI olarak doğru şekilde eşleştir.

TEMEL PRENSIP: Kullanıcının NE İSTEDİĞİNİ ANLAYARAK, bazen ESNEK bazen KATI eşleştirme yap.""",
        
        "user": """🎯 GÖREV: Entity'leri hedef kolonlarındaki distinct değerlerle BAĞLAMSAL ANLAYış ve KULLANICI AMACına göre eşleştir.

{entities_and_columns_context}

🧠 AKILLI EŞLEŞTIRME STRATEJİSİ:

** 1. BAĞLAM ANALİZİ - Kullanıcının Ne İstediğini Anla **
├─ SPESIFIK ARAMA: "Aksa Elektrik firması" → TAM eşleştirme gerekli (KATI)
├─ KATEGORI ARAMA: "enerji firmaları" → GENİŞ eşleştirme (ESNEK)
├─ ÖZET/RAPOR: "tüm durumlar" → Tüm benzer değerleri kapsayacak pattern (ESNEK)
└─ FİLTRELEME: "sadece aktif durum" → Kesin değer gerekli (KATI)

** 2. CONFIDENCE LEVEL BAZLI ESNEK-KATI DENGE **

📌 DEFINITE entities (confidence: definite):
   ├─ YAKLAŞIM: KATI eşleştirme 
   ├─ THRESHOLD: 0.8+ (yüksek kesinlik)
   ├─ SONUÇ: TEK, EN UYGUN eşleştirme
   ├─ PATTERN: Tam değer ya da çok spesifik LIKE
   └─ ÖRNEK: "Aksa Elektrik" → "AKSA ELEKTRİK A.Ş." (exact/specific)

🔄 FUZZY entities (confidence: fuzzy):
   ├─ YAKLAŞIM: DENGELI (esnek ama mantıklı)
   ├─ THRESHOLD: 0.6+ (orta kesinlik)
   ├─ SONUÇ: 1-2 ana eşleştirme + alternatifler
   ├─ PATTERN: Ortak kelime bazlı LIKE
   └─ ÖRNEK: "enerji firması" → "ENERJİ" keyword'ü içeren tüm firmalar

[GLOBE] POSSIBILITY entities (confidence: possibility):  
   ├─ YAKLAŞIM: ÇOK ESNEK (geniş yorumlama)
   ├─ THRESHOLD: 0.4+ (düşük kesinlik)
   ├─ SONUÇ: Tüm potansiyel eşleştirmeler
   ├─ PATTERN: En geniş LIKE pattern'ları
   └─ ÖRNEK: "durum" → DURUM içeren tüm pattern'lar

** 3. TÜRKÇE DİL İŞLEME (Esnek Ek Analizi) **
├─ KÖK ÇIKARMA: "firmaların" → "FIRMA" 
├─ ÇOĞUL EKİ: "durumlar" → "DURUM"
├─ HAL EKİ: "enerjiden" → "ENERJİ"
├─ İYELİK EKİ: "şirketin" → "ŞİRKET"
└─ MORF. ANALİZ: Türkçe ek yapısını dikkate al

** 4. SEMANTİK GENİŞLETME (Bağlam Odaklı) **
```
KULLANICI BAĞLAMI → SEMANTİK GENİŞLETME
"enerji" → ["ENERJİ", "ENERGY", "ELEKTRIK", "GÜÇ"]
"durum" → ["DURUM", "STATUS", "STATÜSÜ", "HAL"]
"firma" → ["FIRMA", "ŞİRKET", "COMPANY", "KURUM"]
"tarih" → [AY_ADI, YIL, TARİH pattern'ları]
```

** 5. PATTERN KARARLAŞTIRMA (Amaç Odaklı) **

A) EXACT MATCH (Katı):
   ├─ Koşul: %90+ benzerlik + aynı anlam
   ├─ SQL: column = 'exact_value'
   └─ Örnek: "Aksa" → "AKSA ELEKTRİK A.Ş."

B) SEMANTIC LIKE (Dengeli):
   ├─ Koşul: Ortak keyword + bağlamsal uyum
   ├─ SQL: column LIKE '%KEYWORD%' 
   └─ Örnek: "enerji firma" → LIKE '%ENERJİ%'

C) BROAD LIKE (Esnek):
   ├─ Koşul: Kök kelime bazlı geniş arama
   ├─ SQL: column LIKE '%ROOT%'
   └─ Örnek: "durum" → LIKE '%DURUM%'

D) TEMPORAL MATCH (Tarih Spesifik):
   ├─ Koşul: Tarih/zaman ifadesi
   ├─ SQL: MONTH(column) = X, YEAR(column) = Y
   └─ Örnek: "temmuz 2025" → MONTH=7 AND YEAR=2025

** 6. BAĞLAMSAL KARAR VERİCİ **
```
IF kullanıcı_amacı == "spesifik_arama":
    threshold = yüksek, pattern = dar, sonuç = tek
ELIF kullanıcı_amacı == "kategori_listeleme": 
    threshold = orta, pattern = orta, sonuç = 2-3
ELSE kullanıcı_amacı == "genel_analiz":
    threshold = düşük, pattern = geniş, sonuç = çoklu
```

* JSON ÇIKTI FORMATI:
{{
  "entity_matches": [
    {{
      "entity_keyword": "original_entity",
      "target_column": "column_name",
      "column_semantic_context": "extracted_context", 
      "best_match": {{
        "matched_value": "calculated_common_keyword_or_exact_value",
        "similarity_score": 0.0-1.0,
        "match_type": "exact|semantic_like|broad_like|temporal",
        "sql_operator": "=|LIKE|MONTH|YEAR",
        "sql_pattern": "working_sql_condition",
        "reasoning": "bağlam_analizi + eşleştirme_mantığı"
      }}
    }}
  ]
}}

[WARNING] KRİTİK BAŞARI KRİTERLERİ:
1. **BAĞLAM ANLAMA**: Kullanıcının amacını entity confidence + keyword'den çıkar
2. **ESNEK-KATI DENGE**: Amaca göre threshold ve pattern genişliği ayarla
3. **TÜRKÇE DİL DESTEĞİ**: Ekleri doğru analiz et, kök bul
4. **SQL_PATTERN DOĞRULUĞU**: Çalışabilir, test edilebilir SQL üret
5. **REASONING DETAYI**: Neden bu eşleştirmeyi yaptığını açıkla

🔍 ÖZEL DURUMLAR:
- **Value yok ama distinct matching yapılıyor**: Kullanıcı amacına bak, genel kategori mi istiyor, spesifik değer mi?
- **Çok fazla benzer değer**: En anlamlı ortak pattern'ı bul
- **Hiç eşleşme yok**: En yakın semantik alternatifi sun
- **Belirsiz entity**: POSSIBILITY olarak işaretle ve geniş arama yap
"""
    },
    
    "query_replacement": {
        "system": """Sen uzman bir sorgu duzenleme asistanisin. User query'lerini SQL-uyumlu enhanced query'ye donusturursun. Veritabani kurallarini ve domain bilgilerini kullanarak en dogru donusumu yaparsin.""",
        
        "user": """GOREV: Original user query'sini veritabani yapisina ve domain kurallarina uygun enhanced query'ye donustur

* ORIGINAL QUERY: {original_query}

* ENTITY DEGISIMLERI:
{entity_matches}

* REPLACEMENT DETAYLARI:
{entities_to_replace}

* VERITABANI DOMAIN BILGISI VE KURALLAR:
- Aşağıdaki kuralları yanlızca verilen şekilde kullanmalısın.Bunlar dışında bu kuralları kullanarak ekleme yapma. 
{table_description}

* ENHANCED QUERY YAPISI (Natural Language + SQL Elements):

**TEMEL FORMAT:** "Ne istiyorum + hangi kosullarda + nasil sirali/gruplu"

**VALUE ENTITY DONUSUMLERI (SQL Pattern Bilgisi ile):**
- sql_operator: "=" → natural filter: "[Column] 'exact_value' olan" (sql_pattern dahil: = 'value')
- sql_operator: "LIKE" → natural filter: "[Column] 'pattern' iceren" (sql_pattern dahil: LIKE '%pattern%') 
- sql_operator: "MONTH" → natural filter: "[Column] N. ayinda olan" (sql_pattern dahil: MONTH([Column]) = N)
- sql_operator: "YEAR" → natural filter: "[Column] YYYY yilinda olan" (sql_pattern dahil: YEAR([Column]) = YYYY)

**SQL PATTERN ENTEGRASYONU:**
- Entity matches'den gelen sql_pattern'leri parantez icinde ek bilgi olarak ekle
- Doğal dil akisini BOZMA, sadece teknik detay olarak parantez icinde belirt
- Format: "doğal dil ifadesi (sql_pattern)"
- FUZZY entities: LIKE pattern'leri direkt kullan
- EXACT entities: = pattern'leri direkt kullan
- DATE entities: MONTH/YEAR fonksiyonlari direkt kullan
- Ornek FUZZY: "[CariAdi] 'DOGALGAZ' iceren veriler (LIKE '%DOGALGAZ%')"
- Ornek EXACT: "[ProductName] 'SADE SODA' olan veriler (= 'SADE SODA')"

**STRUCTURAL ELEMENTS:**
- Aggregation: "toplam [Column]", "sayi [Column]", "ortalama [Column]"
- Grouping: "[Column] bazinda", "[Column] grubuna gore"
- Sorting: "[Column] gore sirali", "[Column] gore azalan"
- Limiting: "ilk N", "en fazla N", "TOP N"

**COMPLEX PATTERNS:**
- Superlative: "en yuksek [Column] olan", "en dusuk [Column] olan"
- Ranking: "ilk 5 [Column] degeri", "top 10 [Column] sonucu"
- Comparison: "[Column1] [Column2]'dan buyuk olan"

* VERITABANI KURALLARI UYGULAMASI:
- Table description'daki SQL kurallarini mutlaka uygula
- Ozel durumlar (Normal satis, iadeler, ikram, zayi, iptal) icin dogru WHERE kosullari
- Tarih sorgulari icin dogru SQL syntax
- Aggregation sorgulari icin GROUP BY gereksinimlerini karsila
- Performance icin TOP/LIMIT kullan

* ENHANCED QUERY OZELLIKLERI:
- SQL operator ve pattern'leri kullan
- LIKE, MONTH(), YEAR() fonksiyonlarini destekle
- Partial matching'i dogru sekilde ifade et
- Turkce domain terimleri korunmali
- Complex patterns (superlative, ranking) desteklenmeli

* NATURAL LANGUAGE + SQL ORNEKLER:

* **FUZZY LIKE PATTERN ornegi (SQL pattern):**
Entity match: {{"sql_operator": "LIKE", "sql_pattern": "LIKE '%DOGALGAZ%'"}}
Input: "dogalgaz firmasi satislari"
Output: "[CariAdi] 'DOGALGAZ' iceren satis verilerini getir (LIKE '%DOGALGAZ%')"

* **DATE MONTH ornegi (SQL pattern):**
Entity match: {{"sql_operator": "MONTH", "sql_pattern": "MONTH([DocumentDate]) = 7"}}
Input: "temmuz ayinin toplam satislari"
Output: "[DocumentDate] 7. ayinda olan toplam [RowAmount] hesapla (MONTH([DocumentDate]) = 7)"

* **DATE YEAR ornegi (SQL pattern):**
Entity match: {{"sql_operator": "YEAR", "sql_pattern": "YEAR([DocumentDate]) = 2025"}}
Input: "2025 yili musteri sayisi"
Output: "[DocumentDate] 2025 yilinda olan toplam [CariAdi] sayisini getir (YEAR([DocumentDate]) = 2025)"

* **EXACT MATCH ornegi (SQL pattern):**
Entity match: {{"sql_operator": "=", "sql_pattern": "= 'SADE SODA'"}}
Input: "sade soda satis miktari"
Output: "[ProductName] 'SADE SODA' olan toplam [Quantity] miktarini getir (= 'SADE SODA')"

* **FUZZY DURUM ORNEGI (SQL pattern):**
Entity match: {{"sql_operator": "LIKE", "sql_pattern": "LIKE '%DURUM%'"}}
Input: "durum kayitlari"
Output: "[StatusColumn] 'DURUM' iceren kayitlari getir (LIKE '%DURUM%')"

* **COMPLEX AGGREGATION ornegi:**
Input: "en cok satan ilk 5 urun"
Output: "toplam [Quantity] bazinda [ProductName] grubuna gore [Quantity] gore azalan ilk 5 sonucu getir"

* **FILTERED AGGREGATION ornegi:**
Input: "temmuz ayinda dogalgaz firmasi satis toplami"
Output: "[DocumentDate] 7. ayinda olan ve [CariAdi] 'DOGALGAZ' iceren toplam [RowAmount] hesapla"

* ENHANCED QUERY FORMATI:
- **Natural language structure:** Insan dilinde anlasilir
- **SQL elements:** [Column] ve 'value' formatinda SQL-aware
- **Action words:** "getir", "hesapla", "listele", "goster"
- **Turkish terms:** Domain terimleri Turkce korunmali

* CIKTI FORMATI (JSON):
{{"enhanced_user_input": "natural_language_query_with_sql_elements"}}

* ORNEKLESTIRME:
* Kotu: "[CariAdi] LIKE '%DOGALGAZ%'"
* Iyi: "[CariAdi] 'DOGALGAZ' iceren satis verilerini getir"

* Kotu: "MONTH([DocumentDate]) = 7"  
* Iyi: "[DocumentDate] 7. ayinda olan kayitlari goster"
"""
    }
}

    def _get_highest_scoring_columns(self, entities: List[Dict]) -> List[str]:
            # Get columns with highest scores from VALUE entities only
        columns = set()
        
        self.logger.info(f"Checking {len(entities)} entities for VALUE type and value matching requirement")
        
        for entity in entities:
            entity_keyword = entity.get("entity_keyword", "unknown")
            entity_type = entity.get("entity_type", "unknown")
            requires_value_matching = entity.get("requires_value_matching", True)
            
            self.logger.info(f"Entity '{entity_keyword}' ({entity_type}): requires_value_matching = {requires_value_matching}")
            
            # Only process VALUE entities that require value matching
            if entity_type != "value":
                self.logger.info(f"Skipping entity '{entity_keyword}' - not VALUE type")
                continue
                
            if not requires_value_matching:
                self.logger.info(f"Skipping VALUE entity '{entity_keyword}' - no value matching required")
                continue
                
            suggested_columns = entity.get("suggested_columns", [])
            if suggested_columns:
                best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
                column_name = best_column.get("column_name", "")
                if column_name:
                    columns.add(column_name)
                    self.logger.info(f"Added column '{column_name}' for VALUE entity '{entity_keyword}'")
        
        self.logger.info(f"Final columns for distinct value matching: {list(columns)}")
        return list(columns)
    
    def _create_fallback_matches(self, entities: List[Dict], columns: List[Dict]) -> List[Dict]:
            # Create manual fallback matches with improved LIKE logic when LLM fails
        fallback_matches = []
        
        for entity in entities[:3]:
            entity_keyword = entity.get("entity_keyword", "").lower()
            suggested_columns = entity.get("suggested_columns", [])
            
            if not suggested_columns:
                continue
                
            best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
            target_column = best_column.get("column_name", "")
            
            #  Dynamic LIKE pattern matching logic
            matched_value = None
            sql_operator = "="
            sql_pattern = ""
            similarity_score = 0.0
            match_type = "no_match"
            
            #  Find column info
            column_info = None
            for col in columns:
                if col.get("name", "") == target_column:
                    column_info = col
                    break
            
            if column_info:
                distinct_values = column_info.get("distinct_values", [])
                col_type = column_info.get("data_type", "")
                
                #  Check for datetime columns first
                if "datetime" in col_type.lower() or "date" in col_type.lower():
                    #  Temporal matching
                    month_map = {
                        "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
                        "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
                        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
                    }

                    
                    for month_name, month_num in month_map.items():
                        if month_name in entity_keyword:
                            matched_value = str(month_num)
                            sql_operator = "MONTH"
                            sql_pattern = f"MONTH([{target_column}]) = {month_num}"
                            similarity_score = 1.0
                            match_type = "temporal_partial"
                            break
                    
                    #  Check for year
                    if not matched_value:
                        for year in ["2024", "2025", "2026"]:
                            if year in entity_keyword:
                                matched_value = year
                                sql_operator = "YEAR"
                                sql_pattern = f"YEAR([{target_column}]) = {year}"
                                similarity_score = 1.0
                                match_type = "temporal_partial"
                                self.logger.info(f"Found year match: '{entity_keyword}' → '{year}'")
                                break
                
                else:
                    #  String column matching - apply LIKE logic
                    matching_values = []
                    for val in distinct_values:
                        val_str = str(val).lower()
                        if entity_keyword in val_str or any(word in val_str for word in entity_keyword.split()):
                            matching_values.append(str(val))
                    
                    if len(matching_values) == 1:
                        #  Exact match
                        matched_value = matching_values[0]
                        sql_operator = "="
                        sql_pattern = f"= '{matched_value}'"
                        similarity_score = 1.0
                        match_type = "exact"
                    
                    elif len(matching_values) > 1:
                        #  Multiple matches - use LIKE pattern
                        #  Find common pattern
                        common_pattern = self._find_common_pattern(entity_keyword, matching_values)
                        matched_value = common_pattern
                        sql_operator = "LIKE"
                        sql_pattern = f"LIKE '%{common_pattern}%'"
                        similarity_score = 0.8
                        match_type = "partial_like"
                    
                    else:
                        #  No match found - try fuzzy matching
                        for val in distinct_values:
                            val_str = str(val).lower()
                            #  Simple fuzzy logic - check if first few chars match
                            if len(entity_keyword) >= 3 and val_str.startswith(entity_keyword[:3]):
                                matched_value = str(val)
                                sql_operator = "="
                                sql_pattern = f"= '{matched_value}'"
                                similarity_score = 0.7
                                match_type = "fuzzy"
                                break
            
            if matched_value and similarity_score >= 0.6:
                fallback_match = {
                    "entity_keyword": entity.get("entity_keyword", ""),
                    "target_column": target_column,
                    "best_match": {
                        "matched_value": matched_value,
                        "similarity_score": similarity_score,
                        "match_type": match_type,
                        "sql_operator": sql_operator,
                        "sql_pattern": sql_pattern,
                        "reasoning": f"Fallback {match_type} matching"
                    }
                }
                fallback_matches.append(fallback_match)
                self.logger.info(f"Fallback match: '{entity.get('entity_keyword', '')}' → '{matched_value}' (operator: {sql_operator}, score: {similarity_score})")
        
        return fallback_matches

    def _find_common_pattern(self, entity_keyword: str, matching_values: List[str]) -> str:
            # Find common pattern for LIKE matching from multiple values
        entity_lower = entity_keyword.lower()
        
        #  Strategy 1: Use entity keyword if it appears in values
        for val in matching_values:
            if entity_lower in val.lower():
                #  Extract the relevant part from the value
                val_parts = val.upper().split()
                for part in val_parts:
                    if entity_lower in part.lower():
                        return part
        
        #  Strategy 2: Find longest common substring
        if matching_values:
            first_val = matching_values[0].upper()
            common_parts = []
            
            for val in matching_values[1:]:
                val_upper = val.upper()
                #  Find common words
                first_words = set(first_val.split())
                val_words = set(val_upper.split())
                common_words = first_words.intersection(val_words)
                if common_words:
                    common_parts.extend(common_words)
            
            if common_parts:
                #  Return the longest common word
                return max(common_parts, key=len)
        
        #  Strategy 3: Fallback - use entity keyword in uppercase
        return entity_keyword.upper()
    
    def _fetch_distinct_values_for_columns(self, columns_to_fetch: List[str], table_info: Dict):
            # Fetch distinct values for specific columns and update table_info
        table_name = table_info.get("table_name", "")
        columns = table_info.get("columns", [])
        
        if not table_name:
            self.logger.warning("No table name found")
            return
        
        for target_column in columns_to_fetch:
            column_info = None
            for col in columns:
                if col.get("name", "") == target_column:
                    column_info = col
                    break
            
            if not column_info or column_info.get("distinct_values"):
                continue
            
            # Skip datetime columns - they use temporal matching instead
            col_type = column_info.get("data_type", "").lower()
            if "datetime" in col_type or "date" in col_type:
                self.logger.info(f"Skipping distinct values for datetime column: {target_column}")
                column_info["distinct_values"] = []  # Empty list for datetime columns
                continue
            
            try:
                query = f"SELECT DISTINCT TOP 50 [{target_column}] FROM [{table_name}] WHERE [{target_column}] IS NOT NULL"
                result = self.db.run(query)
                
                values = []
                if result and isinstance(result, str):
                    for line in result.strip().split('\n'):
                        line = line.strip()
                        if line and line != target_column and not line.startswith('-') and not line.startswith('('):
                            values.append(line)
                
                column_info["distinct_values"] = values[:50]
                self.logger.info(f"Fetched {len(values)} distinct values for {target_column}")
                
            except Exception as e:
                self.logger.error(f"Failed to fetch distinct values for {target_column}: {e}")
                column_info["distinct_values"] = []
    
    def _match_entities_with_distinct_values(self, entities: List[Dict], table_info: Dict) -> List[Dict]:
            # Match entities with distinct values from their highest scoring columns
        if not entities:
            self.logger.warning("No entities provided for matching")
            return []
        
        self._initialize_templates()
        columns = table_info.get("columns", [])
        
        self.logger.info(f"Starting entity matching with {len(entities)} entities and {len(columns)} columns")
        
        #  Build context for bulk matching - only for entities that require value matching
        entities_context = []
        valid_entities = []
        
        for entity in entities[:3]:  # Limit to 3 entities as per requirement
            entity_keyword = entity.get("entity_keyword", "")
            suggested_columns = entity.get("suggested_columns", [])
            requires_value_matching = entity.get("requires_value_matching", True)  # Default to True for backward compatibility
            confidence_level = entity.get("confidence_level", "definite")  # New confidence level field
            
            self.logger.info(f"Processing entity: '{entity_keyword}' (requires_value_matching: {requires_value_matching}, confidence: {confidence_level}) with {len(suggested_columns)} suggested columns")
            
            if not entity_keyword or not suggested_columns:
                self.logger.warning(f"Skipping entity '{entity_keyword}' - missing keyword or columns")
                continue
                
            #  Skip structural entities (they don't need value matching)
            if not requires_value_matching:
                self.logger.info(f"Skipping structural entity '{entity_keyword}' - no value matching required")
                continue
            
            # For fuzzy/possibility entities, process all potential columns
            columns_to_process = []
            if confidence_level in ["fuzzy", "possibility"]:
                # Process all suggested columns for fuzzy entities
                self.logger.info(f"  Fuzzy entity '{entity_keyword}' - checking all {len(suggested_columns)} potential columns")
                columns_to_process = suggested_columns[:3]  # Limit to top 3 for performance
            else:
                # For definite entities, use only the highest scoring column
                best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
                columns_to_process = [best_column]
                self.logger.info(f"  Definite entity '{entity_keyword}' - using best column only")
            
            # Process each column
            for column_data in columns_to_process:
                target_column = column_data.get("column_name", "")
                column_score = column_data.get("similarity_score", 0)
                
                if not target_column:
                    continue
                    
                self.logger.info(f"  Processing column '{target_column}' for entity '{entity_keyword}' (score: {column_score:.2f})")
                
                #  Find distinct values for this column
                column_info = None
                for col in columns:
                    if col.get("name", "") == target_column:
                        column_info = col
                        break
                
                if not column_info:
                    self.logger.warning(f"  Column '{target_column}' not found in table_info")
                    continue
                    
                distinct_values = column_info.get("distinct_values", [])
                if not distinct_values:
                    self.logger.warning(f"  No distinct values found for column '{target_column}'")
                    continue
                    
                distinct_values = distinct_values[:10]  # Top 10 values
                self.logger.info(f"  Found {len(distinct_values)} distinct values: {distinct_values}")
                
                #  Get semantic context for this column
                col_type = column_info.get("data_type", "")
                col_description = column_info.get("description", "")
                semantic_context = self._get_column_semantic_context(target_column, col_type, col_description, distinct_values[:3])
                
                # Escape any format string placeholders in the data to prevent KeyErrors
                safe_entity_keyword = str(entity_keyword).replace("{", "{{").replace("}", "}}")
                safe_target_column = str(target_column).replace("{", "{{").replace("}", "}}")
                safe_col_type = str(col_type).replace("{", "{{").replace("}", "}}")
                safe_col_description = str(col_description).replace("{", "{{").replace("}", "}}")
                safe_semantic_context = str(semantic_context).replace("{", "{{").replace("}", "}}")
                
                # Also escape distinct values
                safe_distinct_values = []
                for v in distinct_values:
                    safe_v = str(v).replace("{", "{{").replace("}", "}}")
                    safe_distinct_values.append(safe_v)
                
                # Create unique context for each column (especially important for fuzzy entities)
                entity_context = f"\nENTITY: \"{safe_entity_keyword}\" (confidence: {confidence_level})\n"
                entity_context += f"TARGET COLUMN: {safe_target_column} ({safe_col_type})\n"
                entity_context += f"COLUMN DESCRIPTION: {safe_col_description}\n"
                entity_context += f"SEMANTIC CONTEXT: {safe_semantic_context}\n"
                entity_context += f"DISTINCT VALUES: {', '.join(safe_distinct_values)}\n---"
                entities_context.append(entity_context)
            
            # Add entity to valid_entities only once, not for each column
            if entity not in valid_entities:
                valid_entities.append(entity)
        
        if not entities_context:
            self.logger.warning("No valid entities with distinct values found")
            return []
        
        self.logger.info(f"Prepared {len(entities_context)} entities for LLM matching")
        
        #  Call LLM for entity-distinct value matching
        try:
            template = self.templates["entity_distinct_matching"]
            system_part = template["system"]
            
            # Safely join entities_context and format template
            try:
                entities_and_columns_context = "\n".join(entities_context) if entities_context else "No entities found"
                # Ensure the context doesn't contain format placeholders that could cause KeyError
                safe_context = str(entities_and_columns_context).replace("{", "{{").replace("}", "}}")
                
                user_part = template["user"].format(
                    entities_and_columns_context=safe_context
                )
                self.logger.debug("Entity matching template formatting successful")
            except KeyError as e:
                self.logger.error(f"Missing template parameter in entity_distinct_matching: {e}")
                return self._create_fallback_matches(valid_entities, columns)
            except Exception as e:
                self.logger.error(f"Error formatting entity_distinct_matching template: {e}")
                return self._create_fallback_matches(valid_entities, columns)
            prompt = system_part + "\n\n" + user_part

            self.logger.info("Sending entity matching prompt to LLM...")
            self.logger.info(f"Prompt preview: {prompt[:500]}...")
            
            response = self.llm.get_chat().invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            self.logger.info(f"LLM response for entity matching (full): {response_text}")
            self.logger.info(f"Response length: {len(response_text)} chars")
            
            #  Try to parse JSON with improved handling
            try:
                # Clean response text - remove markdown code blocks if present
                clean_text = response_text.strip()
                
                # Remove markdown json code blocks
                if clean_text.startswith('```json'):
                    self.logger.info("Removing markdown code block wrapper")
                    clean_text = clean_text.replace('```json', '').replace('```', '').strip()
                elif clean_text.startswith('```'):
                    self.logger.info("Removing generic code block wrapper")
                    clean_text = clean_text.replace('```', '').strip()
                
                result = json.loads(clean_text)
                self.logger.info(f"JSON parsing successful. Keys: {list(result.keys())}")
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON parsing failed after cleanup: {e}")
                self.logger.error(f"Cleaned text preview: {clean_text[:200]}...")
                
                #  Try regex fallback to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group().strip()
                        result = json.loads(extracted_json)
                        self.logger.info("Successfully extracted JSON with regex")
                    except json.JSONDecodeError:
                        self.logger.error("Regex extracted text is not valid JSON either")
                        self.logger.error(f"Extracted text: {json_match.group()[:200]}...")
                        return self._create_fallback_matches(valid_entities, columns)
                else:
                    self.logger.error("No valid JSON found in response, using fallback")
                    return self._create_fallback_matches(valid_entities, columns)
            
            # Safely extract entity_matches with better error handling
            entity_matches = []
            try:
                if "entity_matches" in result:
                    entity_matches = result["entity_matches"]
                    if not isinstance(entity_matches, list):
                        self.logger.error(f"entity_matches is not a list: {type(entity_matches)}")
                        entity_matches = []
                else:
                    # Try alternative key names
                    alternative_keys = ["matches", "results", "entity_results", "entities"]
                    for alt_key in alternative_keys:
                        if alt_key in result:
                            entity_matches = result[alt_key]
                            if isinstance(entity_matches, list):
                                self.logger.info(f"Found entity matches under alternative key: {alt_key}")
                                break
                            else:
                                self.logger.warning(f"Key {alt_key} found but not a list: {type(entity_matches)}")
            except Exception as e:
                self.logger.error(f"Error extracting entity_matches from result: {e}")
                self.logger.error(f"Result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
                entity_matches = []
            
            self.logger.info(f"Entity matching completed: {len(entity_matches)} matches")
            
            # Safely iterate through matches
            for i, match in enumerate(entity_matches):
                try:
                    if not isinstance(match, dict):
                        self.logger.error(f"Match {i} is not a dict: {type(match)}")
                        continue
                    
                    entity_keyword = match.get("entity_keyword", "")
                    best_match = match.get("best_match", {})
                    
                    if isinstance(best_match, dict):
                        matched_value = best_match.get("matched_value", "")
                        similarity_score = best_match.get("similarity_score", 0)
                        self.logger.info(f"  '{entity_keyword}' → '{matched_value}' (score: {similarity_score})")
                    else:
                        self.logger.error(f"best_match for '{entity_keyword}' is not a dict: {type(best_match)}")
                except Exception as e:
                    self.logger.error(f"Error processing match {i}: {e}")
                    continue
            
            return entity_matches
            
        except Exception as e:
            self.logger.error(f"Entity distinct value matching failed: {e}")
            self.logger.error(f"Error type: {type(e).__name__}")
            return self._create_fallback_matches(valid_entities, columns)
        
    def _replace_query_terms(self, original_query: str, entity_matches: List[Dict], all_entities: List[Dict] = None, table_description: str = "") -> Dict:
            # Replace terms in query with highest scoring matches, handle both value and structural entities
        if not entity_matches and not all_entities:
            return {
                "enhanced_query": original_query,
                "replacements_made": [],
                "replacement_count": 0
            }
        
        self._initialize_templates()
        
        #  Build entity matches context for replacement
        matches_context = []
        valid_replacements = []
        entities_to_replace = []
        
        #  Process value entities (with distinct value matches)
        for match in entity_matches:
            best_match = match.get("best_match", {})
            if not isinstance(best_match, dict):
                self.logger.warning(f"best_match is not a dict for entity: {match.get('entity_keyword', 'unknown')}")
                continue
                
            similarity_score = best_match.get("similarity_score", 0)
            
            if similarity_score >= 0.7:  # Only use good matches
                entity_keyword = match.get('entity_keyword', '')
                matched_value = best_match.get('matched_value', '')
                target_column = match.get('target_column', '')
                entity_type = match.get('entity_type', 'value')
                
                if not entity_keyword or not matched_value or not target_column:
                    self.logger.warning(f"Missing required fields in match: entity_keyword='{entity_keyword}', matched_value='{matched_value}', target_column='{target_column}'")
                    continue
                
                #  New: SQL operator and pattern support with safe defaults
                try:
                    # Ensure best_match is a dictionary and has required fields
                    if not isinstance(best_match, dict):
                        self.logger.warning(f"best_match is not a dict for '{entity_keyword}': {type(best_match)}")
                        best_match = {}
                    
                    sql_operator = best_match.get('sql_operator', '=') if best_match.get('sql_operator') else '='
                    sql_pattern = best_match.get('sql_pattern', f"= '{matched_value}'") if best_match.get('sql_pattern') else f"= '{matched_value}'"
                    match_type = best_match.get('match_type', 'exact') if best_match.get('match_type') else 'exact'
                    
                    # Validate sql_operator value
                    valid_operators = ['=', 'LIKE', 'MONTH', 'YEAR', '>=', '<=', '>', '<', '!=']
                    if sql_operator not in valid_operators:
                        self.logger.warning(f"Invalid sql_operator '{sql_operator}' for '{entity_keyword}', defaulting to '='")
                        sql_operator = '='
                        sql_pattern = f"= '{matched_value}'"
                        match_type = 'exact'
                    
                    self.logger.debug(f"Extracted SQL info for '{entity_keyword}': operator={sql_operator}, pattern={sql_pattern}, type={match_type}")
                except Exception as e:
                    self.logger.error(f"Error extracting SQL info for '{entity_keyword}': {e}")
                    sql_operator = '='
                    sql_pattern = f"= '{matched_value}'"
                    match_type = 'exact'
                
                #  Build context string and entity replacement dynamically based on SQL pattern
                match_str = f'"{entity_keyword}" → {target_column} ({match_type})'
                
                # Parse sql_pattern and create appropriate natural language description
                entity_replacement = self._create_natural_replacement(target_column, sql_pattern, entity_keyword)
                
                # Escape curly braces to prevent format issues
                safe_match_str = match_str.replace("{", "{{").replace("}", "}}")
                safe_entity_replacement = entity_replacement.replace("{", "{{").replace("}", "}}")
                
                matches_context.append(safe_match_str)
                entities_to_replace.append(safe_entity_replacement)
                
                self.logger.debug(f"Added match string: {safe_match_str}")
                self.logger.debug(f"Added entity replacement: {safe_entity_replacement}")
                
                # Ensure all fields are safe before adding to valid_replacements
                safe_replacement = {
                    "original_term": str(entity_keyword) if entity_keyword else "unknown",
                    "replacement": str(matched_value) if matched_value else "unknown",
                    "column": str(target_column) if target_column else "unknown",
                    "score": float(similarity_score) if isinstance(similarity_score, (int, float)) else 0.0,
                    "entity_type": "value",
                    "sql_operator": str(sql_operator) if sql_operator else "=",
                    "sql_pattern": str(sql_pattern) if sql_pattern else f"= '{matched_value}'",
                    "match_type": str(match_type) if match_type else "exact"
                }
                valid_replacements.append(safe_replacement)
        
        #  Process structural and select entities (only column mapping, no value replacement)
        if all_entities:
            for entity in all_entities:
                requires_value_matching = entity.get("requires_value_matching", True)
                entity_type = entity.get("entity_type", "unknown")
                
                if not requires_value_matching:  # This is a structural or select entity
                    entity_keyword = entity.get("entity_keyword", "")
                    suggested_columns = entity.get("suggested_columns", [])
                    aggregation_function = entity.get("aggregation_function", "none")
                    complex_pattern = entity.get("complex_pattern", None)
                    
                    if entity_keyword and suggested_columns:
                        best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
                        target_column = best_column.get("column_name", "")
                        similarity_score = best_column.get("similarity_score", 0)
                        
                        if similarity_score >= 0.7:
                            column_type = best_column.get("column_type", "") or best_column.get("type", "")
                            
                            #  Different handling for structural vs select entities
                            if entity_type == "select":
                                #  For select entities, include aggregation function
                                if aggregation_function != "none":
                                    replacement = f"{aggregation_function.upper()}([{target_column}])"
                                    #  Handle complex patterns for select entities
                                    if complex_pattern:
                                        pattern_type = complex_pattern.get("type", "")
                                        if pattern_type in ["superlative", "ranking"]:
                                            order_dir = complex_pattern.get("order_direction", "desc")
                                            replacement += f" ORDER BY {aggregation_function.upper()}([{target_column}]) {order_dir.upper()}"
                                    
                                    match_str = f'"{entity_keyword}" select+complex → "{replacement}"'
                                    safe_complex_entity = f"{replacement} (complex select: '{entity_keyword}')".replace("{", "{{").replace("}", "}}")
                                    entities_to_replace.append(safe_complex_entity)
                                else:
                                    replacement = f"[{target_column}]"
                                    match_str = f'"{entity_keyword}" select → "{replacement}"'
                                    safe_select_entity = f"[{target_column}] (select kolon: '{entity_keyword}')".replace("{", "{{").replace("}", "}}")
                                    entities_to_replace.append(safe_select_entity)
                            else:
                                #  For structural entities, just column name
                                replacement = f"[{target_column}]"
                                match_str = f'"{entity_keyword}" yapisal → "{replacement}"'
                                safe_entity_replacement = f"[{target_column}] (yapisal: '{entity_keyword}')".replace("{", "{{").replace("}", "}}")
                                entities_to_replace.append(safe_entity_replacement)
                            
                            # Escape curly braces for structural entities too
                            safe_match_str = match_str.replace("{", "{{").replace("}", "}}")
                            matches_context.append(safe_match_str)
                            self.logger.debug(f"Added structural match string: {safe_match_str}")
                            
                            # Ensure all fields are safe for structural entities
                            safe_structural_replacement = {
                                "original_term": str(entity_keyword) if entity_keyword else "unknown",
                                "replacement": str(replacement) if replacement else "unknown",
                                "column": str(target_column) if target_column else "unknown",
                                "score": float(similarity_score) if isinstance(similarity_score, (int, float)) else 0.0,
                                "entity_type": str(entity_type) if entity_type else "structural",
                                "aggregation_function": str(aggregation_function) if aggregation_function else "",
                                "complex_pattern": str(complex_pattern) if complex_pattern else "",
                                "sql_operator": "=",  # Default for structural/select entities
                                "sql_pattern": f"= '{replacement}'" if replacement else "= 'unknown'",  # Default pattern
                                "match_type": "structural"  # Default match type
                            }
                            valid_replacements.append(safe_structural_replacement)
        
        self.logger.info(f"Valid replacements for query enhancement: {len(valid_replacements)}")
        for i, replacement in enumerate(valid_replacements):
            try:
                # Safely extract all fields with default values
                entity_type = str(replacement.get('entity_type', 'unknown')) if replacement.get('entity_type') else 'unknown'
                original_term = str(replacement.get('original_term', 'unknown')) if replacement.get('original_term') else 'unknown'
                replacement_value = str(replacement.get('replacement', 'unknown')) if replacement.get('replacement') else 'unknown'
                score = float(replacement.get('score', 0.0)) if isinstance(replacement.get('score'), (int, float)) else 0.0
                sql_operator = str(replacement.get('sql_operator', '=')) if replacement.get('sql_operator') else '='
                sql_pattern = str(replacement.get('sql_pattern', 'missing')) if replacement.get('sql_pattern') else 'missing'
                
                self.logger.info(f"  [{i}] '{original_term}' → '{replacement_value}' ({entity_type}, score: {score:.2f}, operator: {sql_operator}, pattern: {sql_pattern})")
            except Exception as e:
                self.logger.error(f"Error processing replacement {i}: {e}")
                self.logger.error(f"Replacement content: {replacement}")
        
        if not matches_context:
            return {
                "enhanced_query": original_query,
                "replacements_made": [],
                "replacement_count": 0
            }
        
        try:
            # Build entity matches string with SQL patterns from original entity_matches
            entity_matches_str = ""
            entities_to_replace_str = ""
            
            try:
                # Create entity matches string with sql_pattern information from entity_matches
                entity_matches_lines = []
                for match in entity_matches:
                    entity_keyword = match.get("entity_keyword", "unknown")
                    target_column = match.get("target_column", "unknown")
                    best_match = match.get("best_match", {})
                    sql_pattern = best_match.get("sql_pattern", "N/A")
                    sql_operator = best_match.get("sql_operator", "N/A")
                    match_type = best_match.get("match_type", "unknown")
                    
                    line = f'"{entity_keyword}" → {target_column} ({match_type}) [sql_pattern: {sql_pattern}]'
                    entity_matches_lines.append(line)
                
                entity_matches_str = "\n".join(entity_matches_lines) if entity_matches_lines else "Hic entity eslestirme yok"
                self.logger.debug(f"Entity matches string with SQL patterns built: {len(entity_matches_str)} chars")
            except Exception as e:
                self.logger.error(f"Error building entity matches string with patterns: {e}")
                entity_matches_str = "Hata: Entity eslestirme string'i olusturulamadi"
            
            try:
                entities_to_replace_str = "\n".join(entities_to_replace) if entities_to_replace else "Hic replacement yok"
                self.logger.debug(f"Entities to replace string built successfully: {len(entities_to_replace_str)} chars")
            except Exception as e:
                self.logger.error(f"Error building entities to replace string: {e}")
                entities_to_replace_str = "Hata: Entities to replace string'i olusturulamadi"
            
            template = self.templates["query_replacement"]
            system_part = template["system"]
            
            # Ensure all template parameters are safe strings
            try:
                format_params = {
                    'original_query': str(original_query) if original_query else "Sorgu belirtilmedi",
                    'entity_matches': str(entity_matches_str) if entity_matches_str else "Hic entity eslestirme yok",
                    'entities_to_replace': str(entities_to_replace_str) if entities_to_replace_str else "Hic replacement yok",
                    'table_description': str(table_description) if table_description else "Domain bilgisi mevcut degil"
                }
                
                user_part = template["user"].format(**format_params)
                self.logger.debug("Template formatting successful")
            except KeyError as e:
                self.logger.error(f"Missing template parameter: {e}")
                return {
                    "enhanced_query": original_query,
                    "replacements_made": valid_replacements,
                    "replacement_count": len(valid_replacements)
                }
            except Exception as e:
                self.logger.error(f"Error formatting template: {e}")
                return {
                    "enhanced_query": original_query,
                    "replacements_made": valid_replacements,
                    "replacement_count": len(valid_replacements)
                }
            prompt = system_part + "\n\n" + user_part

            self.logger.info(f"Sending query replacement prompt for: '{original_query}'")
            response = self.llm.get_chat().invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            self.logger.info(f"LLM response for query replacement: {response_text[:200]}...")
            
            #  Try to extract JSON from response with improved handling
            try:
                # Clean response text - remove markdown code blocks if present
                clean_text = response_text.strip()
                
                # Remove markdown json code blocks
                if clean_text.startswith('```json'):
                    self.logger.info("Removing markdown code block wrapper from query replacement response")
                    clean_text = clean_text.replace('```json', '').replace('```', '').strip()
                elif clean_text.startswith('```'):
                    self.logger.info("Removing generic code block wrapper from query replacement response")
                    clean_text = clean_text.replace('```', '').strip()
                
                result = json.loads(clean_text)
            except json.JSONDecodeError:
                self.logger.error("JSON parsing failed after cleanup in query replacement")
                #  Try to find JSON in response text
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group())
                        self.logger.info("Successfully extracted JSON with regex in query replacement")
                    except json.JSONDecodeError:
                        raise ValueError("No valid JSON found in response after regex extraction")
                else:
                    raise ValueError("No valid JSON found in response")
            
            #  New format returns only enhanced_user_input
            enhanced_query = result.get("enhanced_user_input", original_query)
            replacements_made = valid_replacements  # Use the ones we prepared
            replacement_count = len(valid_replacements)
            
            self.logger.info(f"Query replacement successful: '{original_query}' → '{enhanced_query}'")
            self.logger.info(f"Replacements made: {replacement_count}")
            
            return {
                "enhanced_query": enhanced_query,
                "replacements_made": replacements_made,
                "replacement_count": replacement_count
            }
            
        except Exception as e:
            import traceback
            self.logger.error(f"Query replacement failed: {e}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            self.logger.error(f"Exception args: {e.args}")
            self.logger.error(f"Full traceback:")
            self.logger.error(traceback.format_exc())
            #  Fallback: Try simple string replacement manually
            enhanced_query = original_query
            replacements_made = []
            
            for replacement in valid_replacements:
                original_term = replacement.get("original_term", "")
                new_value = replacement.get("replacement", "")
                
                #  Case-insensitive replacement
                if original_term.lower() in enhanced_query.lower():
                    #  Find the actual case in the query
                    import re
                    pattern = re.compile(re.escape(original_term), re.IGNORECASE)
                    enhanced_query = pattern.sub(new_value, enhanced_query)
                    replacements_made.append({
                        "original_term": original_term,
                        "replacement": new_value,
                        "column": replacement.get("column", "")
                    })
            
            replacement_count = len(replacements_made)
            self.logger.info(f"Fallback replacement completed: {replacement_count} replacements made")
            
            return {
                "enhanced_query": enhanced_query,
                "replacements_made": replacements_made,
                "replacement_count": replacement_count
            }

    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
            # Execute query enhancement workflow - two-step process
        #  Initialize state
        if state is None:
            state = {}
        if "messages" not in state:
            state["messages"] = []
        if "agent_results" not in state or state["agent_results"] is None:
            state["agent_results"] = {}
            
        state["current_agent"] = "query_enhancement_agent"
        
        try:
            intent_data = state.get("intent_data", {})
            table_info = state.get("table_info", {})
            context_data = state.get("context_data", {})
            
            #  Get table_description from config for enhanced query generation
            configurable = config.get("configurable", {})
            assistant_config = configurable.get("assistant_config", {})
            table_description = assistant_config.get("table_description", "")
            
            if not intent_data:
                raise Exception("Intent data not found - run intent analysis first")
            
            user_query = context_data.get("current_message", "")
            entities = intent_data.get("entities", [])
            
            self.logger.info(f"Query enhancement starting - entities found: {len(entities)}")
            self.logger.info(f"User query: '{user_query}'")
            
            if not entities:
                #  If no entities found, return original query
                self.logger.warning(f"No entities found in intent_data for query: '{user_query}'")
                self.logger.warning(f"Intent data content: {intent_data}")
                self.logger.warning("Skipping LLM calls due to no entities - QueryEnhancementAgent will not send prompts")
                
                state["enhanced_query"] = user_query
                state["query_enhancements"] = {
                    "entity_matches": [],
                    "replacements_made": [],
                    "replacement_count": 0
                }
                
                summary = "Sorgu gelistirilmesi tamamlandi:\n\n"
                summary += f"- **Orijinal sorgu:** {user_query}\n"
                summary += f"- **Gelistirilmis sorgu:** {user_query}\n"
                summary += "- **Degisim sayisi:** 0\n"
                summary += "- **Sebep:** Entity bulunamadi (Intent Analysis Agent ciktisini kontrol edin)"
                
                state["messages"].append(AIMessage(content=summary))
                state["agent_results"]["query_enhancement_agent"] = {
                    "status": "success",
                    "entities_found": 0,
                    "replacements_made": 0,
                    "execution_time": time.time()
                }
                return state
            
            self.logger.info(f"Starting query enhancement for {len(entities)} entities")
            self.logger.info(f"User query to enhance: '{user_query}'")
            
            for i, entity in enumerate(entities):
                entity_keyword = entity.get('entity_keyword', 'unknown')
                suggested_columns = entity.get('suggested_columns', [])
                self.logger.info(f"  Entity {i+1}: '{entity_keyword}' - columns: {len(suggested_columns)}")
                
                if suggested_columns:
                    best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
                    self.logger.info(f"    Best column: {best_column.get('column_name', '')} (score: {best_column.get('similarity_score', 0):.2f})")
            
            #  STEP 1: Entity-Distinct Value Matching
            #  Get columns that need distinct values
            columns_to_fetch = self._get_highest_scoring_columns(entities)
            self.logger.info(f"Columns to fetch distinct values: {columns_to_fetch}")
            

            #  Fetch distinct values for those columns
            if columns_to_fetch and table_info and isinstance(table_info, dict):
                self.logger.info(f"Fetching distinct values for {len(columns_to_fetch)} columns")
                self._fetch_distinct_values_for_columns(columns_to_fetch, table_info)
                
                #  Filter only VALUE entities for distinct matching
                value_entities = [entity for entity in entities 
                                if entity.get("entity_type") == "value" and 
                                   entity.get("requires_value_matching", True)]
                
                self.logger.info(f"Filtering entities: {len(entities)} total → {len(value_entities)} VALUE entities for matching")
                
                if value_entities:
                    #  Match only VALUE entities with distinct values
                    self.logger.info("Starting entity-distinct value matching for VALUE entities only...")
                    entity_matches = self._match_entities_with_distinct_values(value_entities, table_info)
                    self.logger.info(f"Entity matching completed, found {len(entity_matches)} matches")
                else:
                    self.logger.info("No VALUE entities found - skipping distinct value matching")
                    entity_matches = []
                
                    #  STEP 2: Query Text Replacement
                self.logger.info(f"Starting query text replacement with {len(entity_matches)} matches")
                
                #  # Debug log the matches before replacement
                #  for i, match in enumerate(entity_matches):
                #      keyword = match.get('entity_keyword', '')
                #      best_match = match.get('best_match', {})
                #      matched_value = best_match.get('matched_value', '')
                #      score = best_match.get('similarity_score', 0)
                #      self.logger.info(f"  Match {i+1}: '{keyword}' → '{matched_value}' (score: {score})")
                
                replacement_result = self._replace_query_terms(user_query, entity_matches, entities, table_description)

                enhanced_query = replacement_result.get("enhanced_query", user_query)
                replacements_made = replacement_result.get("replacements_made", [])
                replacement_count = replacement_result.get("replacement_count", 0)
                
                self.logger.info(f"Query replacement completed: '{user_query}' → '{enhanced_query}'")
                
                #  Store results in state
                state["enhanced_query"] = enhanced_query
                state["query_enhancements"] = {
                    "entity_matches": entity_matches,
                    "replacements_made": replacements_made,
                    "replacement_count": replacement_count
                }
                
                #  Also store for backward compatibility with SQL generation
                state["entity_distinct_matches"] = entity_matches
            else:
                self.logger.warning("No columns to fetch - entities may not have suggested_columns")
                state["enhanced_query"] = user_query
                state["query_enhancements"] = {
                    "entity_matches": [],
                    "replacements_made": [],
                    "replacement_count": 0
                }
            
            #  Generate summary with details
            enhancements = state.get("query_enhancements", {})
            entity_matches = enhancements.get("entity_matches", [])
            replacements_made = enhancements.get("replacements_made", [])
            replacement_count = enhancements.get("replacement_count", 0)
            enhanced_query = state.get("enhanced_query", user_query)
            
            #  Build replacements detail
            replacements_detail = ""
            if replacements_made:
                replacements_list = []
                for repl in replacements_made[:5]:  # Show max 5 replacements
                    original = repl.get("original_term", "")
                    replacement = repl.get("replacement", "")
                    column = repl.get("column", "")
                    replacements_list.append(f"  - '{original}' → '{replacement}' (kolon: {column})")
                replacements_detail = f"\n\n**Yapilan degisimler:**\n" + "\n".join(replacements_list)
            
            summary = "Sorgu gelistirilmesi tamamlandi:\n\n"
            summary += f"- **Orijinal sorgu:** `{user_query}`\n"
            summary += f"- **Gelistirilmis sorgu:** `{enhanced_query}`\n"
            summary += f"- **Entity eslestirmeleri:** {len(entity_matches)} adet\n"
            summary += f"- **Basarili degisimler:** {replacement_count} adet{replacements_detail}\n\n"
            summary += "**Yontem:** Iki asamali sorgu gelistirme\n"
            summary += "1. Entity-distinct value eslestirme (AI tabanli)\n"
            summary += "2. Metin replacement (AI + fallback)"
            
            state["messages"].append(AIMessage(content=summary))
            
            #  Store agent results
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["query_enhancement_agent"] = {
                "status": "success",
                "method": "two_step_query_enhancement",
                "entities_found": len(entities),
                "entity_matches": len(entity_matches),
                "replacements_made": replacement_count,
                "original_query": user_query,
                "enhanced_query": enhanced_query,
                "execution_time": time.time()
            }
            
            self.logger.info(f"Query enhancement completed - Entities: {len(entities)}, Matches: {len(entity_matches)}, Replacements: {replacement_count}")
            return state
            
        except Exception as e:
            error_msg = f"Sorgu gelistirilmesi basarisiz: {str(e)}"
            state["errors"] = {"error_message": error_msg, "error_type": "query_enhancement_failure"}
            
            #  Provide error context
            error_context = ""
            if "intent_data" not in locals():
                error_context = " (Intent analizi bulunamadi)"
            elif "table_info" not in locals():
                error_context = " (Tablo bilgisi bulunamadi)"
            
            detailed_error_msg = f"* {error_msg}{error_context}\n\n*� **Oneriler:**\n- Intent analizi agent'inin basarili calistigindan emin olun\n- Tablo bilgisinin mevcut oldugunu kontrol edin"
            
            state["messages"].append(AIMessage(content=detailed_error_msg))
            
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["query_enhancement_agent"] = {
                "status": "error",
                "method": "two_step_query_enhancement",
                "error": str(e),
                "error_type": type(e).__name__,
                "error_context": error_context,
                "execution_time": time.time()
            }
            
            self.logger.error(f"Query enhancement failed: {e}")
            return state


class SQLGenerationAgent:
        # Agent for generating SQL queries from extracted parameters
    
    def __init__(self, llm, logger, assistant_configuration=None):
        self.llm = llm
        self.logger = logger
        self.assistant_configuration = assistant_configuration
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        #  Execute SQL generation workflow using enhanced query
        #  Initialize state
        if state is None:
            state = {}
        if "messages" not in state:
            state["messages"] = []
        if "agent_results" not in state or state["agent_results"] is None:
            state["agent_results"] = {}
            
        state["current_agent"] = "sql_generation_agent"
        
        try:
            table_info = state.get("table_info", {})
            intent_data = state.get("intent_data", {})
            
            agent_results = state.get("agent_results", {})
            query_enhancement_results = agent_results.get("query_enhancement_agent", {})
            
            #  Ensure query_enhancement_results is not None
            if query_enhancement_results is None:
                query_enhancement_results = {}
    
            enhanced_query = query_enhancement_results.get("enhanced_query", "")
            query_enhancements = query_enhancement_results
            
            if not enhanced_query:
                #  Fallback to original query if no enhancement was done
                context_data = state.get("context_data", {})
                enhanced_query = context_data.get("current_message", "")
                
            if not enhanced_query:
                raise Exception("No query found - run query enhancement first")
            
            table_name = table_info.get("table_name", "")
            
            self.logger.info(f"Generating SQL from enhanced query: '{enhanced_query}'")
            self.logger.info(f"Query enhancements: {query_enhancements.get('replacement_count', 0)} replacements")
            
            #  Build SQL generation prompt using enhanced query
            sql_prompt = self._build_sql_generation_prompt_enhanced(
                enhanced_query, table_info, intent_data, query_enhancements
            )
            
            #  Generate SQL using LLM
            response = self.llm.get_chat().invoke(sql_prompt)
            sql_response = response.content if hasattr(response, 'content') else str(response)
            
            self.logger.info(f"SQL generation LLM response: {sql_response[:300]}...")
            
            #  Extract SQL from response using enhanced cleaner
            from src.utils.sql_cleaner import extract_sql_from_response
            sql_query = extract_sql_from_response(sql_response) or self._extract_sql_from_response(sql_response)
            
            self.logger.info(f"Generated SQL query: {sql_query}")
            
            state["generated_sql"] = sql_query
            state["sql_generation_response"] = sql_response
            
            #  Generate summary
            entity_matches = query_enhancements.get("entity_matches", [])
            replacement_count = query_enhancements.get("replacement_count", 0)
            
            summary = "SQL sorgusu olusturuldu:\n\n"
            summary += "```sql\n"
            summary += sql_query + "\n"
            summary += "```\n\n"
            summary += "**Kullanilan veriler:**\n"
            summary += f"- **Gelistirilmis sorgu:** {enhanced_query}\n"
            summary += f"- **Entity eslestirmeleri:** {entity_matches} adet\n\n"
            summary += "**Yontem:** Gelistirilmis sorgu ile direkt SQL uretimi"
            
            state["messages"].append(AIMessage(content=summary))
            
            #  Store agent results
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["sql_generation_agent"] = {
                "status": "success",
                "method": "enhanced_query_direct_generation",
                "sql_query": sql_query,
                "enhanced_query": enhanced_query,
                "execution_time": time.time()
            }
            
            self.logger.info("SQL generation completed successfully")
            return state
            
        except Exception as e:
            error_msg = f"SQL generation failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=f"* {error_msg}"))
            
            if "agent_results" not in state or state["agent_results"] is None:
                state["agent_results"] = {}
                
            state["agent_results"]["sql_generation_agent"] = {
                "status": "error",
                "error": str(e),
                "execution_time": time.time()
            }
            
            self.logger.error(f"SQL generation failed: {e}")
            return state
    
    def _build_sql_generation_prompt_enhanced(self, enhanced_query: str, table_info: Dict, 
                                         intent_data: Dict, query_enhancements: Dict) -> str:
        #  Build enhanced SQL generation prompt using the improved query
        
        table_name = table_info.get("table_name", "")
        columns = table_info.get("columns", [])
        
        #  Analyze entities for GROUP BY and aggregation detection
        entities = intent_data.get("entities", [])
        has_groupby_entities = any(entity.get("entity_type") == "structural" for entity in entities)
        has_select_entities = any(entity.get("entity_type") == "select" for entity in entities)
        has_aggregation = any(entity.get("aggregation_function", "none") != "none" for entity in entities)
        
        #  Build column information with better context
        column_info = []
        date_columns = []
        text_columns = []
        numeric_columns = []
        
        for col in columns[:25]:  # More columns for better context
            col_name = col.get("name", "")
            col_type = col.get("data_type", "") or col.get("type", "")
            col_description = col.get("description", "")
            distinct_values = col.get("distinct_values", [])[:5]  # Top 5 values
            
            #  Categorize columns for better SQL generation
            if "date" in col_type.lower() or "tarih" in col_name.lower() or "datetime" in col_type.lower():
                date_columns.append(f"{col_name} ({col_type})")
            elif "varchar" in col_type.lower() or "nvarchar" in col_type.lower() or "text" in col_type.lower():
                text_columns.append(f"{col_name} ({col_type})")
            elif "decimal" in col_type.lower() or "int" in col_type.lower() or "bit" in col_type.lower():
                numeric_columns.append(f"{col_name} ({col_type})")
            
            #  Include column description for better context
            col_info_parts = [f"[{col_name}]", f"({col_type})"]
            if col_description:
                col_info_parts.append(f"- {col_description}")
            if distinct_values:
                col_info_parts.append(f"Degerler: {', '.join(str(v) for v in distinct_values)}")
            
            col_info = f"- {' '.join(col_info_parts)}"
            column_info.append(col_info)

        #  Build entity analysis for SQL context
        entity_analysis = ""
        if entities:
            entity_details = []
            for entity in entities:
                entity_type = entity.get("entity_type", "unknown")
                entity_keyword = entity.get("entity_keyword", "")
                aggregation_func = entity.get("aggregation_function", "none")
                suggested_columns = entity.get("suggested_columns", [])
                
                if suggested_columns:
                    best_column = max(suggested_columns, key=lambda x: x.get("similarity_score", 0))
                    column_name = best_column.get("column_name", "")
                    column_type = best_column.get("column_type", "")
                    
                    if entity_type == "select":
                        entity_details.append(f"- SELECT: {entity_keyword} → {aggregation_func.upper()}([{column_name}]) - TIP: {column_type}")
                    elif entity_type == "structural":
                        entity_details.append(f"- STRUCTURAL: {entity_keyword} → [GROUP BY/ORDER BY {column_name}] - TIP: {column_type}")
                    elif entity_type == "value":
                        entity_details.append(f"- VALUE: {entity_keyword} → WHERE [{column_name}] - TIP: {column_type}")
            
            if entity_details:
                entity_analysis = f"\n==== ENTITY ANALIZI ====\n" + "\n".join(entity_details)

        #  Build aggregation guidance
        aggregation_guidance = ""
        if has_groupby_entities or has_select_entities or has_aggregation:
            aggregation_guidance = "\n==== GRUPLAMA VE AGGREGATION KURALLARI ====\n"
            aggregation_guidance += "- GRUP SORGULARI ICIN ZORUNLU: Eger SUM, COUNT, AVG, MAX, MIN varsa GROUP BY kullan\n"
            aggregation_guidance += "- SELECT kisminda aggregation fonksiyonu varsa GROUP BY gerekli\n"
            aggregation_guidance += "- GROUP BY kolonlari SELECT kisminda da olmali\n"
            aggregation_guidance += "- HAVING kullan WHERE yerine aggregation sonuclari icin"

        #  Add column type breakdown for better context
        column_type_info = ""
        if date_columns or text_columns or numeric_columns:
            column_type_info = "\n==== KOLON TIP ANALIZI ====\n"
            column_type_info += f"- TARIH KOLONLARI: {', '.join(date_columns) if date_columns else 'Yok'}\n"
            column_type_info += f"- METIN KOLONLARI: {', '.join(text_columns[:10]) if text_columns else 'Yok'}\n"
            column_type_info += f"- SAYI KOLONLARI: {', '.join(numeric_columns[:10]) if numeric_columns else 'Yok'}"

        #  Build prompt using string concatenation to avoid encoding issues
        prompt = "Sen bir SQL uzmanisin. Gelistirilmis Turkce sorguyu SQL'e cevir.\n\n"
        prompt += f"TABLO: [{table_name}]\n"
        prompt += f"Kolonlar: {len(columns)} adet\n\n"
        prompt += "KOLON DETAYLARI:\n"
        prompt += "\n".join(column_info[:15]) + "\n\n"
        prompt += f"GELISTIRILMIS SORGU:\n{enhanced_query}\n\n"
        prompt += "SORGU ANALIZI:\n"
        prompt += f"- GROUP BY gerekli: {'EVET' if has_groupby_entities else 'HAYIR'}\n"
        prompt += f"- Aggregation gerekli: {'EVET' if has_aggregation else 'HAYIR'}\n"
        prompt += f"- SELECT entities: {'EVET' if has_select_entities else 'HAYIR'}\n"
        if aggregation_guidance:
            prompt += aggregation_guidance + "\n"
        
        #  Add MSSQL-specific SQL syntax guidelines
        prompt += "\n[WARNING] KRİTİK: MICROSOFT SQL SERVER (MSSQL) SENTAKSİ ZORUNLU [WARNING]\n"
        prompt += "==== MSSQL SQL YAZIM KURALLARI (ÇOK ÖNEMLİ) ====\n"
        prompt += "1. Column isimlerini MSSQL formatında koseli parantez ile yaz: [ColumnName]\n"
        prompt += "2. String degerler: 'deger' (tek tırnak - MSSQL standart)\n"
        prompt += "3. Sayi degerler: tırnak yok (MSSQL numeric format)\n"
        prompt += "4. Aggregation varsa GROUP BY ekle (MSSQL aggregation rule)\n"
        prompt += "5. MSSQL Tarih fonksiyonları: MONTH([tarih]), YEAR([tarih]), DATEPART kullan\n"
        prompt += "6. MSSQL String fonksiyonları: LIKE '%deger%', CHARINDEX, LEN kullan\n"
        prompt += f"7. MSSQL SELECT format: SELECT * FROM [{table_name}] WHERE [kolon] = 'deger'\n"
        prompt += "8. MSSQL TOP kullan (LIMIT değil): SELECT TOP 10 * FROM table\n"
        prompt += "9. MSSQL JOIN syntax: INNER JOIN, LEFT JOIN (MSSQL formatında)\n"
        prompt += "10. Cevabini sadece çalıştırılabilir MSSQL kodu olarak ver, açıklama yapma\n"
        prompt += "\n🎯 HEDEF: %100 MSSQL uyumlu, hatasız çalışan SQL kodu üret\n"
        
        return prompt
    
    def _extract_sql_from_response(self, response: str) -> str:
        """
        Extract SQL query from LLM response - flexible parsing for various formats.
        Handles: direct SQL, quoted SQL, code blocks, and mixed text responses.
        """
        try:
            import re
            original_response = response
            response_cleaned = response.strip()
            
            self.logger.debug(f"Extracting SQL from response: {response_cleaned[:100]}...")
            
            # Method 1: Look for SQL in markdown code blocks (```sql...``` or ```...```)
            sql_code_match = re.search(r'```(?:sql)?\s*\n(.*?)\n```', response, re.DOTALL | re.IGNORECASE)
            if sql_code_match:
                extracted_sql = sql_code_match.group(1).strip()
                self.logger.debug(f"Found SQL in code block: {extracted_sql[:50]}...")
                return self._clean_extracted_sql(extracted_sql)
            
            # Method 2: Look for quoted SQL strings ("SELECT..." or 'SELECT...')
            quoted_sql_match = re.search(r'["\'](\s*SELECT\s+.*?)["\']', response, re.DOTALL | re.IGNORECASE)
            if quoted_sql_match:
                extracted_sql = quoted_sql_match.group(1).strip()
                self.logger.debug(f"Found quoted SQL: {extracted_sql[:50]}...")
                return self._clean_extracted_sql(extracted_sql)
            
            # Method 3: Look for SELECT statements with proper boundaries
            # Match SELECT until semicolon, newline, or end of string
            select_pattern = r'(SELECT\s+.*?)(?:;|\n\n|\Z)'
            select_match = re.search(select_pattern, response, re.DOTALL | re.IGNORECASE)
            if select_match:
                extracted_sql = select_match.group(1).strip()
                self.logger.debug(f"Found SELECT statement: {extracted_sql[:50]}...")
                return self._clean_extracted_sql(extracted_sql)
            
            # Method 4: Check if the entire response is a SQL query (direct SQL)
            if self._looks_like_sql(response_cleaned):
                self.logger.debug("Response appears to be direct SQL")
                return self._clean_extracted_sql(response_cleaned)
            
            # Method 5: Look for SQL after common prefixes
            prefix_patterns = [
                r'(?:query|sql|statement):\s*(SELECT\s+.*)',
                r'(?:here|result).*?:\s*(SELECT\s+.*)',
                r'```?\s*(SELECT\s+.*?)```?'
            ]
            
            for pattern in prefix_patterns:
                prefix_match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
                if prefix_match:
                    extracted_sql = prefix_match.group(1).strip()
                    self.logger.debug(f"Found SQL with prefix pattern: {extracted_sql[:50]}...")
                    return self._clean_extracted_sql(extracted_sql)
            
            # Method 6: Last resort - extract any text that contains SELECT and FROM
            if 'SELECT' in response.upper() and 'FROM' in response.upper():
                # Try to extract the most SQL-like portion
                lines = response_cleaned.split('\n')
                for line in lines:
                    if 'SELECT' in line.upper() and 'FROM' in line.upper():
                        self.logger.debug(f"Found SQL-like line: {line[:50]}...")
                        return self._clean_extracted_sql(line.strip())
                        
                # If no single line works, return the whole response cleaned
                self.logger.debug("Using entire response as SQL (last resort)")
                return self._clean_extracted_sql(response_cleaned)
            
            # No SQL found
            raise Exception(f"No SQL query found in response. Response: {response_cleaned[:200]}...")
            
        except Exception as e:
            self.logger.error(f"SQL extraction failed: {str(e)}")
            raise Exception(f"Failed to extract SQL from response: {str(e)}")
    
    def _looks_like_sql(self, text: str) -> bool:
        """Check if text looks like a SQL query."""
        text_upper = text.upper()
        # Must contain SELECT and FROM
        has_select_from = 'SELECT' in text_upper and 'FROM' in text_upper
        # Should not contain too much non-SQL text
        sql_keywords = ['SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'ORDER', 'GROUP', 'HAVING', 'JOIN']
        sql_keyword_count = sum(1 for keyword in sql_keywords if keyword in text_upper)
        total_words = len(text.split())
        
        return has_select_from and (sql_keyword_count >= 2 or total_words <= 20)
    
    def _clean_extracted_sql(self, sql: str) -> str:
        """Clean and normalize extracted SQL."""
        # Remove common prefixes/suffixes
        sql = sql.strip()
        
        # Remove leading/trailing quotes
        if (sql.startswith('"') and sql.endswith('"')) or (sql.startswith("'") and sql.endswith("'")):
            sql = sql[1:-1].strip()
        
        # Remove markdown artifacts
        sql = sql.replace('`', '').strip()
        
        # Remove trailing semicolon if present
        if sql.endswith(';'):
            sql = sql[:-1].strip()
            
        # Basic validation
        if not sql.upper().startswith('SELECT'):
            raise Exception(f"Extracted text doesn't start with SELECT: {sql[:100]}")
            
        return sql
    
    def _get_column_semantic_context(self, column_name: str, column_type: str, description: str = "", sample_values: List = None) -> str:
        #  Generate semantic context for different column types
        context = []
        
        if "datetime" in column_type.lower() or "date" in column_type.lower():
            context.append("TEMPORAL MATCHING: supports MONTH(), YEAR(), date ranges")
            context.append("Example patterns: 'bugun', 'bu ay', '2024', 'ocak'")
        elif "nvarchar" in column_type.lower() or "varchar" in column_type.lower():
            if sample_values:
                context.append(f"STRING MATCHING: exact or LIKE pattern matching")
                context.append(f"Sample values: {', '.join(str(v) for v in sample_values[:3])}")
            else:
                context.append("STRING MATCHING: text search and LIKE patterns")
        elif any(t in column_type.lower() for t in ["int", "decimal", "float", "money"]):
            context.append("NUMERIC MATCHING: exact values, ranges, comparisons")
        elif "bit" in column_type.lower():
            context.append("BOOLEAN MATCHING: 0/1, true/false, yes/no")
        else:
            context.append("GENERAL MATCHING: direct value comparison")
            
        if description:
            context.append(f"PURPOSE: {description}")
            
        return "\n".join(context)


class SQLExecutionAgent:
    """Agent for executing generated SQL queries and returning results"""
    
    def __init__(self, db, logger):
        self.db = db
        self.logger = logger
        
    def execute(self, state: EnhancedText2SQLState, *, config) -> EnhancedText2SQLState:
        """Execute the generated SQL query and return results"""
        if "messages" not in state:
            state["messages"] = []
            
        state["current_agent"] = "sql_execution_agent"
        
        try:
            generated_sql = state.get("generated_sql", "")
            
            if not generated_sql:
                error_msg = "No SQL query found to execute"
                state["errors"] = {"error_message": error_msg}
                state["messages"].append(AIMessage(content=f"* {error_msg}"))
                self.logger.error(error_msg)
                return state
            
            self.logger.info(f"Executing SQL query: {generated_sql}")
            
            # Execute the SQL query
            try:
                result = self.db.run(generated_sql)
                
                # Store execution result
                state["execution_result"] = {
                    "sql_query": generated_sql,
                    "result": result,
                    "status": "success",
                    "row_count": len(result.split('\n')) - 1 if result else 0
                }
                
                # Format the response message
                if result:
                    response_msg = f"SQL Query executed successfully:\n\n**Query:**\n```sql\n{generated_sql}\n```\n\n**Results:**\n```\n{result}\n```"
                else:
                    response_msg = f"SQL Query executed successfully but returned no results:\n\n**Query:**\n```sql\n{generated_sql}\n```\n\n**Result:** No data found"
                
                state["messages"].append(AIMessage(content=response_msg))
                self.logger.info("SQL query executed successfully")
                
            except Exception as db_error:
                error_msg = f"SQL execution failed: {str(db_error)}"
                state["execution_result"] = {
                    "sql_query": generated_sql,
                    "error": str(db_error),
                    "status": "error"
                }
                state["errors"] = {"error_message": error_msg}
                
                response_msg = f"SQL Query execution failed:\n\n**Query:**\n```sql\n{generated_sql}\n```\n\n**Error:** {str(db_error)}"
                state["messages"].append(AIMessage(content=response_msg))
                self.logger.error(f"SQL execution failed: {db_error}")
                
        except Exception as e:
            error_msg = f"SQL execution agent failed: {str(e)}"
            state["errors"] = {"error_message": error_msg}
            state["messages"].append(AIMessage(content=f"* {error_msg}"))
            self.logger.error(f"SQL execution agent failed: {e}")
            
        return state