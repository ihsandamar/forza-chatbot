# data_visualization/nodes/visualization_decider.py

import json
import logging
from typing import Dict, Any

from src.models.llm import LLM
from ..state import (
    DataVisualizationState,
    VisualizationDecision,
    OutputType,
    DataProfile
)

logger = logging.getLogger(__name__)


class VisualizationDecider:
    """
    Decides if visualization is needed and what type.
    Single LLM call - ~250 tokens
    """

    def __init__(self, llm: LLM):
        """Initialize with LLM instance"""
        self.llm = llm
        self.chat_model = llm.get_chat()

        # Enable JSON mode for OpenAI/Anthropic
        if llm.provider in ["openai", "anthropic"]:
            self.chat_model = self.chat_model.bind(response_format={"type": "json_object"})

    SYSTEM_PROMPT = """Sen bir veri görselleştirme uzmanısın.
Kullanıcı sorusu ve veri profiline göre en uygun görselleştirme tipini belirle.

ÖNEMLİ KURAL: Kullanıcı grafik türünü açıkça belirtmişse (örn: "çubuk grafik", "pasta grafik", "çizgi grafik", "daire grafik"), MUTLAKA o türü kullan!
- "çubuk grafik", "bar grafik", "bar chart" → bar_chart
- "çizgi grafik", "line chart" → line_chart
- "pasta grafik", "pie chart", "daire grafik" → pie_chart
- "scatter", "dağılım grafik" → scatter_chart

Kullanıcı grafik türü belirtmemişse veri profiline göre karar ver:
- Tek sayı sonucu → single_value (grafik yok)
- 1-2 kolonlu kısa liste → simple_list (grafik yok)
- Zaman serisi trendi → line_chart
- Kategori karşılaştırması → bar_chart
- Oran/dağılım gösterimi → pie_chart
- İki değişken ilişkisi → scatter_chart
- Çok kolonlu detaylı veri → table
- Dönem karşılaştırması → comparison

ÖNEMLİ: Yanıtın SADECE geçerli bir JSON objesi olmalı, başka hiçbir metin, açıklama veya markdown yazma.
Sadece şu formattaki JSON'u döndür:
{"needs_graph": true, "output_type": "bar_chart", "reason": "kullanıcı çubuk grafik istedi"}"""

    def decide(self, state: DataVisualizationState) -> DataVisualizationState:
        """Main decision method"""
        
        data_profile = state.get("data_profile")
        user_query = state.get("user_query", "")
        raw_data = state.get("raw_data", [])
        
        # Quick exit conditions (no LLM needed)
        if not raw_data or len(raw_data) == 0:
            return {
                **state,
                "viz_decision": VisualizationDecision(
                    needs_graph=False,
                    output_type=OutputType.TABLE,
                    reason="Veri yok"
                )
            }
        
        # Single value - no graph needed
        if len(raw_data) == 1 and data_profile and data_profile["column_count"] == 1:
            return {
                **state,
                "viz_decision": VisualizationDecision(
                    needs_graph=False,
                    output_type=OutputType.SINGLE_VALUE,
                    reason="Tek değer sonucu"
                )
            }
        
        # Prepare context for LLM
        profile_summary = self._create_profile_summary(data_profile)
        sample_data = raw_data[:3] if len(raw_data) >= 3 else raw_data
        
        prompt = f"""KULLANICI SORUSU: "{user_query}"

ÖNEMLİ: Kullanıcı grafik türünü açıkça belirtmişse (çubuk, çizgi, pasta, vb.), MUTLAKA o grafik türünü kullan!

Veri Profili:
{profile_summary}

Örnek Veri (ilk 3 satır):
{json.dumps(sample_data, ensure_ascii=False, indent=2)}

Toplam Satır: {len(raw_data)}

Kullanıcının isteğini ve veri profilini analiz et, en uygun görselleştirmeyi belirle ve sadece JSON objesi döndür."""

        try:
            # Use LangChain chat model
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]

            response = self.chat_model.invoke(messages)

            # Clean and parse response content
            content = response.content.strip()

            # Check if content is empty
            if not content:
                logger.error("LLM returned empty response")
                raise ValueError("Empty response from LLM")

            logger.debug(f"LLM response (first 200 chars): {content[:200]}")

            # Handle markdown code blocks
            if content.startswith("```"):
                parts = content.split("```")
                if len(parts) >= 2:
                    content = parts[1]
                    # Remove 'json' prefix if present
                    if content.startswith("json"):
                        content = content[4:].strip()
                    elif content.startswith("JSON"):
                        content = content[4:].strip()

            # Parse JSON
            decision_raw = json.loads(content)
            logger.debug(f"Parsed decision: {decision_raw}")
            
            # Parse output type
            output_type_str = decision_raw.get("output_type", "table")
            try:
                output_type = OutputType(output_type_str)
            except ValueError:
                output_type = OutputType.TABLE
            
            # Determine if graph is needed
            needs_graph = decision_raw.get("needs_graph", False)
            if output_type in [OutputType.SINGLE_VALUE, OutputType.SIMPLE_LIST, OutputType.TABLE]:
                needs_graph = False
            else:
                needs_graph = True
            
            viz_decision = VisualizationDecision(
                needs_graph=needs_graph,
                output_type=output_type,
                reason=decision_raw.get("reason", "")
            )
            
            return {**state, "viz_decision": viz_decision}
            
        except json.JSONDecodeError as e:
            # JSON parsing error - log and fallback
            logger.error(f"JSON decode error: {str(e)}")
            logger.error(f"Problematic content: {content[:500] if 'content' in locals() else 'N/A'}")
            return {
                **state,
                "viz_decision": VisualizationDecision(
                    needs_graph=False,
                    output_type=OutputType.TABLE,
                    reason=f"JSON parse hatası, tablo kullanılıyor: {str(e)}"
                )
            }
        except Exception as e:
            # Generic error - log and fallback
            logger.error(f"Visualization decision error: {str(e)}", exc_info=True)
            return {
                **state,
                "viz_decision": VisualizationDecision(
                    needs_graph=False,
                    output_type=OutputType.TABLE,
                    reason=f"Karar hatası, tablo kullanılıyor: {str(e)}"
                )
            }
    
    def _create_profile_summary(self, profile: DataProfile) -> str:
        """Create concise profile summary for LLM"""
        if not profile:
            return "Profil yok"
        
        lines = [
            f"Satır: {profile['row_count']}, Kolon: {profile['column_count']}",
            f"Dimension kolonları: {', '.join(profile['dimension_columns']) or 'Yok'}",
            f"Metric kolonları: {', '.join(profile['metric_columns']) or 'Yok'}",
            f"Zaman kolonu: {profile['time_column'] or 'Yok'}",
            f"Zaman serisi: {'Evet' if profile['has_time_series'] else 'Hayır'}"
        ]
        
        return "\n".join(lines)


def create_visualization_decider_node(llm: LLM):
    """Factory function to create visualization decider node with LLM"""
    def visualization_decider_node(state: DataVisualizationState) -> Dict[str, Any]:
        """LangGraph node wrapper"""
        decider = VisualizationDecider(llm)
        return decider.decide(state)
    return visualization_decider_node