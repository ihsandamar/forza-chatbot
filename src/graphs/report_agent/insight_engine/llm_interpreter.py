"""
LLMInterpreter — Findings JSON → natural language + action recommendations.
"""
import logging
from typing import List

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Sen bir iş analisti asistanısın. Sana matematiksel olarak hesaplanmış bulgular verilecek.

KURALLAR:
- Sadece verilen bulgulardan çıkarım yap
- Kendi hesaplama veya tahmin yapma
- Her kritik bulgu için somut ve uygulanabilir aksiyon öner
- Türkçe yaz
- Sayıları her zaman bulgulardan al, kendiliğinden üretme

FORMAT:
📊 Özet: (1-2 cümle — en önemli bulgu)

🔍 Kritik Bulgular:
- [bulgu1]: [sayıyla destekli açıklama]
- [bulgu2]: ...

💡 Aksiyon Önerileri:
- [somut öneri1]
- [somut öneri2]"""

_NO_FINDINGS_RESPONSE = (
    "Mevcut veri üzerinde istatistiksel olarak anlamlı bir bulgu tespit edilemedi. "
    "Daha geniş bir tarih aralığı veya farklı bir segment seçerek tekrar deneyebilirsiniz."
)


class LLMInterpreter:
    """Interpret findings using LLM to generate natural language insights and action recommendations."""

    def __init__(self, llm):
        """
        Args:
            llm: LLM instance with ainvoke method (e.g., ChatAnthropic).
        """
        self._llm = llm

    def _build_prompt(self, findings: List[Finding], context: AnalysisContext) -> str:
        """
        Build a prompt from findings and analysis context for LLM interpretation.

        Args:
            findings: List of Finding objects from analyzers.
            context: AnalysisContext containing user query, filters, period, and columns.

        Returns:
            Prompt string for LLM, or "no findings" message if findings is empty.
        """
        if not findings:
            return f"Kullanıcı sorusu: {context.user_query}\n\nMevcut veri üzerinde anlamlı bir bulgu bulunamadı. Bunu kullanıcıya açıkla."

        findings_text = "\n".join(
            f"{i+1}. {f.type} | {f.dimension}={f.value} | {f.metric} | "
            f"değişim={f.change_pct:+.1f}% | önem={f.significance:.2f} | dönem: {f.period_label}"
            + (f"\n   Kanıt: {f.extra}" if f.extra else "")
            for i, f in enumerate(findings)
        )

        filters_text = (
            ", ".join(f"{d['field']}={d['value']}" for d in context.active_filters)
            if context.active_filters else "Yok"
        )

        return (
            f"Kullanıcı sorusu: {context.user_query}\n"
            f"Aktif filtreler: {filters_text}\n"
            f"Dönem: {context.period_label}\n\n"
            f"BULGULAR (önem sırasına göre):\n{findings_text}\n\n"
            f"Yukarıdaki bulgulara dayanarak yorum yap ve aksiyon öner. "
            f"Kendi hesaplama yapma — sadece verilen sayıları kullan."
        )

    async def interpret(self, findings: List[Finding], context: AnalysisContext) -> str:
        """
        Interpret findings using LLM to generate natural language insights.

        Args:
            findings: List of Finding objects to interpret.
            context: AnalysisContext for the analysis.

        Returns:
            Natural language interpretation string, or _NO_FINDINGS_RESPONSE if no findings.
        """
        if not findings:
            return _NO_FINDINGS_RESPONSE

        prompt = self._build_prompt(findings, context)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            response = await self._llm.ainvoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            return response.content.strip()
        except Exception as exc:
            logger.warning(f"[LLM_INTERPRETER] LLM call failed: {exc}")
            return _NO_FINDINGS_RESPONSE
