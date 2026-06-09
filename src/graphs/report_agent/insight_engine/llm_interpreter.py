"""
LLMInterpreter — Python → LLM geçiş katmanı.

Prompt yapısı (3 katman):
  1. GENEL TABLO    — DataFrame'den hesaplanan özet istatistikler (bağlam)
  2. KRİTİK BULGULAR — significance > 0.6 olanlar (öncelikli okuma)
  3. TÜM BULGULAR   — kategori bazlı gruplandırılmış tam liste

LLM çıktı formatı (6 bölüm):
  📊 Genel Bakış / 🏆 Ürün Performansı / 📈 Trend & Momentum
  ⚠️ Anomaliler / 📅 Sezonsallik / 💡 Aksiyon
"""
import logging
from collections import defaultdict
from typing import List

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

_CRITICAL_THRESHOLD = 0.6

_SYSTEM_PROMPT = """Sen bir üst düzey iş analisti asistanısın.
Sana üç katmanlı veri verilecek: (1) Genel Tablo — ham istatistikler, (2) Kritik Bulgular — en önemli matematiksel tespitler, (3) Tüm Bulgular — kategorize tam liste.

KURALLAR:
- Sadece verilen sayılardan çıkarım yap; kendi hesaplama veya tahmin yapma
- Genel Tablo'daki sayıları (toplam, günlük ort, segment payları) bağlam olarak kullan
- Anomali/CUSUM bulgularındaki tarihleri mutlaka yaz
- Trend bulgularındaki R², slope, momentum_score değerlerini yorum metnine yansıt
- Korelasyon bulgularını "ürün ilişkisi" olarak değerlendir
- Bütünsel bir değerlendirme sun; bulgular arasındaki örüntüleri birleştir
- Türkçe yaz; sayıları her zaman bulgulardan al

ÇIKTI FORMATI (bu 6 bölümü sırayla yaz, veri yoksa bölümü atla):
📊 Genel Bakış: (Genel Tablo'dan: toplam değer, dönem, günlük ort, genel trend yönü)

🏆 Ürün/Segment Performansı: (top/bottom/pareto/BCG bulgularını değerlendir, % payları belirt)

📈 Trend & Momentum: (trend_increase/decline, high_momentum, wow_surge/drop, accelerating/decelerating — R² ve slope değerleriyle)

⚠️ Anomaliler & Değişimler: (anomaly_high/low, cusum_shift, regime_change — tarihleri ve z-score değerlerini mutlaka yaz)

📅 Sezonsallik: (seasonal_peak/trough, periodic_pattern — varsa gün adlarını ve % farkları yaz)

💡 Aksiyon Önerileri: (somut, sayıya dayalı, öncelik sıralamalı — en kritik bulgular için önce)"""

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


def _risk_badge(significance: float) -> str:
    """🔴 kritik (≥0.7) / 🟡 izle (≥0.4) / 🟢 iyi (< 0.4)."""
    if significance >= 0.7:
        return "🔴"
    if significance >= 0.4:
        return "🟡"
    return "🟢"


def _humanize_evidence(f: Finding) -> str:
    """Finding.extra'daki teknik veriyi insan diline çevirir.
    LLM'e giden promptta z_score, r_squared vb. görünmez."""
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


def _fmt_number(value: float) -> str:
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{sign}{v / 1_000:.1f}K"
    return f"{value:.2f}"


def _finding_line(f: Finding) -> str:
    line = (
        f"  [{f.type}] {f.dimension}={f.value} | {f.metric} | "
        f"değişim={f.change_pct:+.1f}% | önem={f.significance:.2f}"
    )
    if f.extra:
        line += f"\n    ↳ {f.extra}"
    return line


class LLMInterpreter:
    def __init__(self, llm):
        self._llm = llm

    def _build_general_table(self, context: AnalysisContext) -> str:
        """Katman 1: DataFrame özet istatistikleri — LLM'e bağlam sağlar."""
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

        # Katman 2: kritik bulgular
        critical = [f for f in findings if f.significance > _CRITICAL_THRESHOLD]
        critical_section = ""
        if critical:
            critical_lines = "\n".join(_finding_line(f) for f in critical)
            critical_section = (
                f"\n\n=== KRİTİK BULGULAR ({len(critical)} adet — önem > {_CRITICAL_THRESHOLD}) ===\n"
                f"{critical_lines}"
            )

        # Kilit tarihler
        date_findings = [f for f in findings if f.type in ("cusum_shift", "regime_change")]
        key_dates_text = ""
        if date_findings:
            dates = [
                f.extra.get("shift_date") or f.extra.get("changepoint_date") or f.value
                for f in date_findings
            ]
            key_dates_text = f"\nKilit Tarihler: {', '.join(filter(None, dates))}"

        # Ürün ilişkileri
        corr_findings = [f for f in findings if "correlation" in f.type]
        corr_text = ""
        if corr_findings:
            pairs = [
                f"  • {f.extra.get('product_a', '')} ↔ {f.extra.get('product_b', '')} "
                f"(r={f.extra.get('r', 0):.2f})"
                for f in corr_findings
            ]
            corr_text = "\nÜrün İlişkileri:\n" + "\n".join(pairs)

        # Katman 3: tüm bulgular kategori bazlı
        groups: dict = defaultdict(list)
        for f in findings:
            cat = _CATEGORY_MAP.get(f.type, "📊 Diğer")
            groups[cat].append(f)
        group_lines = []
        for cat in sorted(groups.keys()):
            group_lines.append(f"\n{cat}:")
            for f in groups[cat]:
                group_lines.append(_finding_line(f))
        all_findings_section = "\n".join(group_lines)

        filters_text = (
            ", ".join(f"{d['field']}={d['value']}" for d in context.active_filters)
            if context.active_filters else "Yok"
        )

        return (
            f"Kullanıcı sorusu: {context.user_query}\n"
            f"Aktif filtreler: {filters_text}\n"
            f"Dönem: {context.period_label}"
            f"{key_dates_text}"
            f"{corr_text}"
            f"{general_table}"
            f"{critical_section}"
            f"\n\n=== TÜM BULGULAR ({len(findings)} adet, kategoriye göre) ==="
            f"{all_findings_section}\n\n"
            "GENEL TABLO'daki sayıları bağlam olarak sun. "
            "Kritik Bulgular'a öncelik ver. "
            "Anomali ve değişim bulgularındaki tarihleri mutlaka belirt. "
            "Trend bulgularındaki R² ve slope değerlerini yorum metnine yansıt. "
            "Kendi hesaplama yapma — sadece verilen sayıları kullan."
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
