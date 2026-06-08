"""
LLMInterpreter — Findings → grouped natural language + action recommendations.
"""
import logging
from collections import defaultdict
from typing import List

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Sen bir üst düzey iş analisti asistanısın. Birden fazla matematiksel analiz \
katmanından gelen bulgular verilecek.

KURALLAR:
- Sadece verilen bulgulardan çıkarım yap
- Kendi hesaplama veya tahmin yapma
- Bulgular arasındaki ilişkileri ve örüntüleri birleştir (korelasyon + trend + anomali = bütünsel resim)
- Kilit tarih varsa o tarihe özel vurgu yap
- Her kritik bulgu için somut ve uygulanabilir aksiyon öner
- Türkçe yaz
- Sayıları her zaman bulgulardan al, kendiliğinden üretme

FORMAT:
📊 Özet: (1-2 cümle — birleştirici kolektif görüş, tek bir bulgu değil)

🔍 Kritik Bulgular:
- [bulgu1]: [sayıyla destekli açıklama]
- [bulgu2]: ...

🔗 Bağlantılar: (varsa — farklı bulgular arasındaki örüntü veya korelasyon)
- [örüntü/ilişki]

💡 Aksiyon Önerileri:
- [somut öneri1]
- [somut öneri2]"""

_CATEGORY_MAP = {
    "trend_increase": "📈 Trend",
    "trend_decline": "📉 Trend",
    "anomaly_high": "⚠️ Anomali",
    "anomaly_low": "⚠️ Anomali",
    "cusum_shift": "🔴 Kalıcı Değişim",
    "regime_change": "🔄 Rejim Değişimi",
    "seasonal_peak": "🗓️ Mevsimsellik",
    "seasonal_trough": "🗓️ Mevsimsellik",
    "periodic_pattern": "🗓️ Periyodik Örüntü",
    "top_performer": "🏆 Segment",
    "bottom_performer": "⬇️ Segment",
    "pareto_dominant": "🎯 Pareto",
    "bcg_star": "⭐ BCG Yıldız",
    "bcg_cash_cow": "🐄 BCG Nakit İnek",
    "bcg_question_mark": "❓ BCG Soru İşareti",
    "bcg_dog": "🐕 BCG Köpek",
    "peak_period": "⏰ Zaman",
    "weak_period": "⏰ Zaman",
    "wow_surge": "🚀 Momentum",
    "wow_drop": "📉 Momentum",
    "high_momentum": "💪 Momentum",
    "high_volatility": "〰️ Volatilite",
    "accelerating": "⬆️ İvme",
    "decelerating": "⬇️ İvme",
    "high_positive_correlation": "🔗 Korelasyon",
    "high_negative_correlation": "🔗 Korelasyon",
}

_NO_FINDINGS_RESPONSE = (
    "Mevcut veri üzerinde istatistiksel olarak anlamlı bir bulgu tespit edilemedi. "
    "Daha geniş bir tarih aralığı veya farklı bir segment seçerek tekrar deneyebilirsiniz."
)


class LLMInterpreter:
    def __init__(self, llm):
        self._llm = llm

    def _build_prompt(self, findings: List[Finding], context: AnalysisContext) -> str:
        if not findings:
            return (
                f"Kullanıcı sorusu: {context.user_query}\n\n"
                "Mevcut veri üzerinde anlamlı bir bulgu bulunamadı. Bunu kullanıcıya açıkla."
            )

        # Group findings by category
        groups: dict = defaultdict(list)
        for f in findings:
            cat = _CATEGORY_MAP.get(f.type, "📊 Diğer")
            groups[cat].append(f)

        parts = []
        for cat in sorted(groups.keys()):
            parts.append(f"\n{cat}:")
            for f in groups[cat]:
                line = (
                    f"  • [{f.type}] {f.dimension}={f.value} | {f.metric} | "
                    f"değişim={f.change_pct:+.1f}% | önem={f.significance:.2f}"
                )
                parts.append(line)
                if f.extra:
                    parts.append(f"    Kanıt: {f.extra}")
        findings_text = "\n".join(parts)

        # Key dates section (CUSUM / regime_change)
        date_findings = [f for f in findings if f.type in ("cusum_shift", "regime_change")]
        key_dates_text = ""
        if date_findings:
            dates = [
                f.extra.get("shift_date") or f.extra.get("changepoint_date") or f.value
                for f in date_findings
            ]
            key_dates_text = f"\nKilit Tarihler: {', '.join(filter(None, dates))}"

        # Correlation section
        corr_findings = [f for f in findings if "correlation" in f.type]
        corr_text = ""
        if corr_findings:
            pairs = [
                f"  • {f.extra.get('product_a', '')} ↔ {f.extra.get('product_b', '')} "
                f"(r={f.extra.get('r', 0):.2f})"
                for f in corr_findings
            ]
            corr_text = "\nÜrün İlişkileri:\n" + "\n".join(pairs)

        filters_text = (
            ", ".join(f"{d['field']}={d['value']}" for d in context.active_filters)
            if context.active_filters else "Yok"
        )

        return (
            f"Kullanıcı sorusu: {context.user_query}\n"
            f"Aktif filtreler: {filters_text}\n"
            f"Dönem: {context.period_label}"
            f"{key_dates_text}"
            f"{corr_text}\n\n"
            f"BULGULAR ({len(findings)} bulgu, kategoriye göre gruplandırılmış):\n"
            f"{findings_text}\n\n"
            "Yukarıdaki bulgulara dayanarak kolektif bir analiz yap. "
            "Zaman değişimlerini, korelasyonları ve momentum bilgilerini birleştirerek "
            "bütünsel bir değerlendirme sun. Kendi hesaplama yapma — sadece verilen sayıları kullan."
        )

    async def interpret(self, findings: List[Finding], context: AnalysisContext) -> str:
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
