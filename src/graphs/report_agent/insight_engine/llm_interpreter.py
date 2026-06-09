"""
LLMInterpreter — Python → LLM geçiş katmanı.

Prompt yapısı:
  1. GENEL TABLO    — DataFrame'den özet istatistikler (bağlam)
  2. BULGULAR       — risk badge + insan dili delil, significance sıralı

LLM çıktı formatı (6 bölüm, veri yoksa bölüm atlanır):
  📊 Genel Bakış / 🏆 En İyi & En Kötü / 📈 Trend & Büyüme
  ⚠️ Dikkat Gereken / 📅 Haftalık Örüntü / 💡 Aksiyonlar
"""
import logging
from typing import List

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

_FINDING_LABELS: dict = {
    "trend_increase": "Artış trendi",
    "trend_decline": "Düşüş trendi",
    "anomaly_high": "Yüksek anomali",
    "anomaly_low": "Düşük anomali",
    "cusum_shift": "Kalıcı değişim",
    "regime_change": "Rejim değişimi",
    "seasonal_peak": "Zirve günü",
    "seasonal_trough": "Düşük gün",
    "periodic_pattern": "Tekrar eden örüntü",
    "top_performer": "En iyi performans",
    "bottom_performer": "En düşük performans",
    "pareto_dominant": "Pareto baskınlığı",
    "bcg_star": "Yıldız ürün",
    "bcg_cash_cow": "Nakit ineği",
    "bcg_question_mark": "Soru işareti ürün",
    "bcg_dog": "Zayıf ürün",
    "peak_period": "Zirve dönemi",
    "weak_period": "Düşük dönem",
    "wow_surge": "Haftalık sıçrama",
    "wow_drop": "Haftalık düşüş",
    "high_momentum": "Güçlü büyüme ivmesi",
    "high_volatility": "Yüksek dalgalanma",
    "accelerating": "Hızlanan büyüme",
    "decelerating": "Yavaşlayan büyüme",
    "high_positive_correlation": "Birlikte hareket",
    "high_negative_correlation": "Zıt hareket",
}

_ROLE_INSTRUCTIONS: dict = {
    "branch_manager": (
        "Kullanıcı şube müdürü — kendi şubesine odaklan, genel karşılaştırmalar gerekmez."
    ),
    "general_manager": (
        "Kullanıcı genel müdür — en iyi ve en kötü şubeyi öne çıkar, tüm bazında karşılaştır."
    ),
    "operations": (
        "Kullanıcı operasyon ekibi — anomalilere ve zaman örüntülerine odaklan."
    ),
}

_SYSTEM_PROMPT = """Sen bir iş analisti asistanısın. Veriler Python tarafından analiz edilmiş
ve insan dilinde özetlenmiştir.

DİL KURALLARI — KESİNLİKLE UY:
- Teknik terim kullanma — istatistiksel semboller ve analiz terimleri çıktıda görünmemeli
- Her bulgu için maksimum 2 cümle
- Önce sonuç, sonra neden: "LATTE bu hafta zirveye çıktı — geçen haftaya göre +%18"
- Aktif dil: "incele", "takip et", "uygula" — "incelenmelidir" gibi pasif ifade yok
- Her rakam bağlamlı: "+%18 artarak 583K" — asla sadece "583K"
- Belirsiz ifade yok: "dikkat çekmektedir", "görülmektedir" gibi dolgu cümle yok

SAYI FORMATI:
- M veya K kullan (1.250.000 değil, 1.25M)
- Yüzde hep yönlü: +%18 veya -%12 — asla sadece %18

AKSİYONLAR:
- Maksimum 3 öneri, en kritik önce
- Her öneri fiille başlar: "Bu ürünü öne çıkar", "Şubeyi incele"
- Doğrudan yapılabilir — "genel strateji geliştir" gibi muğlak öneri yok

FORMAT KURALLARI:
- 🔴 bulgular en kritik — önce bunları işle
- Bölüm yoksa o bölümü yazma — boş bölüm çıkmasın
- Her bölüm maksimum 3-4 cümle
- Bütünsel değerlendirme: bulgular arasındaki bağlantıyı göster

ÇIKTI FORMATI:
📊 Genel Bakış: (Genel Tablo'dan toplam, dönem, günlük ort — 1-2 cümle)

🏆 En İyi & En Kötü: (hangi ürün/segment zirve yapıyor, hangisi dipte — veri varsa)

📈 Trend & Büyüme: (büyüyen/düşen ürünler, haftalık değişimler — veri varsa)

⚠️ Dikkat Gereken: (anomali, kalıcı değişim, tarihle birlikte — veri varsa)

📅 Haftalık Örüntü: (hangi gün yüksek/düşük — veri varsa)

💡 Aksiyonlar: (maksimum 3, en kritik önce, fiille başlar)"""

_NO_FINDINGS_RESPONSE = (
    "Bu dönemde öne çıkan bir hareket tespit edilemedi. "
    "Daha geniş bir tarih aralığı seçerek tekrar deneyebilirsiniz."
)


def _fmt_number(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{sign}{v / 1_000:.1f}K"
    return f"{value:.2f}"


def _risk_badge(significance: float) -> str:
    """🔴 kritik (≥0.7) / 🟡 izle (≥0.4) / 🟢 iyi (< 0.4)."""
    if significance >= 0.7:
        return "🔴"
    if significance >= 0.4:
        return "🟡"
    return "🟢"


def _humanize_evidence(f: Finding) -> str:
    """Finding.extra'daki teknik veriyi insan diline çevirir."""
    e = f.extra
    cur = f.current_value
    cmp = f.comparison_value
    chg = f.change_pct
    t = f.type

    if t in ("anomaly_high", "anomaly_low"):
        mean_val = e.get("mean", cmp)
        ratio = round(abs(cur) / abs(mean_val), 1) if mean_val else 0
        direction = "üzerinde" if chg > 0 else ("altında" if chg < 0 else "eşit")
        return (
            f"Ortalama {_fmt_number(mean_val)}'ye karşı {_fmt_number(cur)} — "
            f"normalin {ratio}x {direction}"
        )
    if t == "cusum_shift":
        shift_date = e.get("shift_date", f.value)
        before = e.get("before_avg", cmp)
        after = e.get("after_avg", cur)
        direction = "yükseldi" if after > before else "düştü"
        return (
            f"{shift_date} tarihinden itibaren kalıcı değişim — "
            f"{_fmt_number(before)}'den {_fmt_number(after)}'ye {direction}"
        )
    if t == "regime_change":
        cp_date = e.get("changepoint_date", f.value)
        before = e.get("before_avg", cmp)
        after = e.get("after_avg", cur)
        direction = "yükseldi" if after > before else "düştü"
        return (
            f"{cp_date} tarihinde rejim değişimi — "
            f"{_fmt_number(before)}'den {_fmt_number(after)}'ye {direction}"
        )
    if t in ("trend_increase", "trend_decline"):
        r2 = e.get("r_squared", 0)
        reliability = "tutarlı" if r2 > 0.6 else ("kısmen tutarlı" if r2 > 0.3 else "dalgalı")
        direction = "artış" if chg > 0 else "düşüş"
        return f"Dönem boyunca {chg:+.1f}% {direction} — {reliability} seyir"
    if t == "wow_surge":
        last7 = e.get("last7_sum", cur)
        prev7 = e.get("prev7_sum", cmp)
        return f"Bu hafta {_fmt_number(last7)}, geçen hafta {_fmt_number(prev7)} — {chg:+.1f}% artış"
    if t == "wow_drop":
        last7 = e.get("last7_sum", cur)
        prev7 = e.get("prev7_sum", cmp)
        return f"Bu hafta {_fmt_number(last7)}, geçen hafta {_fmt_number(prev7)} — {chg:+.1f}% düşüş"
    if t == "high_momentum":
        return f"Dönem sonu başa göre {chg:+.1f}% — güçlü ve tutarlı büyüme"
    if t == "high_volatility":
        cv = e.get("cv", 0)
        mean_val = e.get("mean", 0)
        return (
            f"Ortalama {_fmt_number(mean_val)}, günler arası dalgalanma yüksek "
            f"(değişkenlik: {cv:.0%})"
        )
    if t == "accelerating":
        return "Büyüme hızlanıyor — ikinci yarı ilk yarıya göre daha güçlü seyir"
    if t == "decelerating":
        return "Büyüme yavaşlıyor — ikinci yarı ilk yarıya kıyasla ivme kaybetti"
    if t in ("seasonal_peak", "seasonal_trough"):
        direction = "yüksek" if chg > 0 else "düşük"
        return f"Haftalık ortalamadan {chg:+.1f}% {direction}"
    if t == "periodic_pattern":
        period = e.get("fft_period", int(cur))
        return f"{period} günde bir tekrar eden örüntü var"
    if t == "top_performer":
        rank = e.get("rank", 1)
        total_segs = e.get("total_segments", "?")
        return f"{total_segs} segment arasında {rank}. sırada — ortalamadan {chg:+.1f}% yüksek"
    if t == "bottom_performer":
        rank = e.get("rank", "?")
        total_segs = e.get("total_segments", "?")
        return f"{total_segs} segment arasında {rank}. sırada (en düşük) — ortalamadan {chg:+.1f}% düşük"
    if t == "pareto_dominant":
        top_n = e.get("top_n", 1)
        share = e.get("share_pct", abs(chg))
        return f"İlk {top_n} segment toplam cironun %{share:.1f}'ini oluşturuyor"
    if t in ("bcg_star", "bcg_cash_cow", "bcg_question_mark", "bcg_dog"):
        growth = e.get("growth_pct", chg)
        share = e.get("revenue_share_pct", 0)
        label = _FINDING_LABELS.get(t, t)
        return f"Büyüme {growth:+.1f}%, pay %{share:.1f} — {label}"
    if t in ("peak_period", "weak_period"):
        direction = "yüksek" if chg > 0 else "düşük"
        return f"Ortalamadan {chg:+.1f}% {direction}"
    if t in ("high_positive_correlation", "high_negative_correlation"):
        r = abs(e.get("r", 0))
        pa = e.get("product_a", "")
        pb = e.get("product_b", "")
        direction = "birlikte" if "positive" in t else "zıt yönde"
        return f"{pa} ve {pb} {direction} hareket ediyor (güç: {r:.2f})"
    return f"Ortalamadan {chg:+.1f}% sapma"


class LLMInterpreter:
    def __init__(self, llm):
        self._llm = llm

    def _build_general_table(self, context: AnalysisContext) -> str:
        s = context.summary
        if not s:
            return ""
        metric = s.get("primary_metric", "Metrik")
        total = s.get("total", 0.0)
        days = s.get("period_days", 0)
        avg = s.get("daily_avg", 0.0)
        seg_col = s.get("segment_col") or ""
        seg_count = s.get("segment_count", 0)
        top_seg = s.get("top_segment") or ""
        top_share = s.get("top_segment_share_pct", 0.0)
        lines = [
            "\n\n=== GENEL TABLO (Bağlam) ===",
            f"Birincil Metrik : {metric}",
            f"Toplam          : {_fmt_number(total)}",
            f"Dönem           : {days} gün",
            f"Günlük Ort      : {_fmt_number(avg)}",
        ]
        if seg_count > 0:
            seg_line = f"Segment         : {seg_count} {seg_col}"
            if top_seg:
                seg_line += f" — En büyük: {top_seg} (%{top_share:.1f} pay)"
            lines.append(seg_line)
        return "\n".join(lines)

    def _build_prompt(self, findings: List[Finding], context: AnalysisContext) -> str:
        if not findings:
            return (
                f"Kullanıcı sorusu: {context.user_query}\n\n"
                "Mevcut veri üzerinde anlamlı bir bulgu bulunamadı. Bunu kullanıcıya açıkla."
            )

        general_table = self._build_general_table(context)

        # Bulgular: significance sıralı, risk badge + insan dili delil
        sorted_findings = sorted(findings, key=lambda x: x.significance, reverse=True)
        finding_lines = []
        for f in sorted_findings:
            badge = _risk_badge(f.significance)
            label = _FINDING_LABELS.get(f.type, f.type)
            evidence = _humanize_evidence(f)
            finding_lines.append(f"{badge} {label} — {f.value}: {evidence}")
        findings_text = "\n".join(finding_lines)

        # Ürün ilişkileri (korelasyon varsa ek context)
        corr_findings = [f for f in findings if "correlation" in f.type]
        corr_text = ""
        if corr_findings:
            pairs = [
                f"  • {f.extra.get('product_a', '')} ↔ {f.extra.get('product_b', '')} "
                f"(güç: {abs(f.extra.get('r', 0)):.2f})"
                for f in corr_findings
            ]
            corr_text = "\nÜrün İlişkileri:\n" + "\n".join(pairs)

        # Kullanıcı rolü (varsa)
        role_text = ""
        role = getattr(context, "user_role", None)
        if role:
            role_instruction = _ROLE_INSTRUCTIONS.get(role, "")
            if role_instruction:
                role_text = f"\nKullanıcı Rolü: {role_instruction}"

        filters_text = (
            ", ".join(f"{d['field']}={d['value']}" for d in context.active_filters)
            if context.active_filters else "Yok"
        )

        return (
            f"Kullanıcı sorusu: {context.user_query}\n"
            f"Filtreler: {filters_text}\n"
            f"Dönem: {context.period_label}"
            f"{role_text}"
            f"{corr_text}"
            f"{general_table}"
            f"\n\n=== BULGULAR ({len(findings)} adet, en kritik önce) ===\n"
            f"{findings_text}\n\n"
            "🔴 bulgular en kritik. Tarihleri ve sayıları kullan. Kendi hesaplama yapma."
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
