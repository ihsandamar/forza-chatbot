from typing import Literal, Optional

from pydantic import BaseModel


# =============================================================================
# PYDANTIC MODEL
# =============================================================================

class VizDecision(BaseModel):
    """viz_decider node'unun structured output'u."""

    needs_graph: bool
    chart_type: Literal[
        "bar_chart", "line_chart", "pie_chart",
        "scatter_chart", "single_value", "simple_list",
        "table", "comparison", "sunburst", "treemap"
    ]
    x_field: Optional[str] = None       # x ekseninde hangi kolon
    y_field: Optional[str] = None       # y ekseninde hangi kolon
    series_field: Optional[str] = None  # Renk/seri kolonu (karşılaştırma için)
    title: Optional[str] = None         # Grafik başlığı
    reason: str                          # Karar gerekçesi


# =============================================================================
# PROMPTS
# =============================================================================

VIZ_DECIDER_PROMPT = """Sen bir veri görselleştirme uzmanısın.
Kullanıcı sorusu ve veri profiline göre en uygun görselleştirme tipini belirle.

## KULLANICI SORUSU
{user_query}

## SORGU TİPİ
{query_type}

## VERİ PROFİLİ
- Satır sayısı: {row_count}
- Dimension kolonları: {dimension_columns}
- Metric kolonları: {metric_columns}
- Zaman kolonu: {time_column}
- Çoklu dimension: {has_multiple_dimensions}

## ÖRNEK VERİ (ilk 3 satır)
{sample_rows}

## KARAR KURALLARI

### Kullanıcı grafik türü belirtmişse MUTLAKA o türü kullan:
- "çubuk grafik", "bar grafik" → bar_chart
- "çizgi grafik", "line chart" → line_chart
- "pasta grafik", "pie chart", "daire grafik" → pie_chart
- "scatter", "dağılım grafik" → scatter_chart
- "sunburst", "hiyerarşik" → sunburst
- "treemap", "ağaç harita" → treemap

### Grafik türü belirtilmemişse veri profiline göre:
- Tek sayı (1 satır + 1 kolon) → single_value, needs_graph=False
- 1-2 kolon kısa liste → simple_list, needs_graph=False
- Çok kolonlu detaylı veri → table, needs_graph=False
- Zaman serisi → line_chart
- Kategori karşılaştırması (az kategori) → bar_chart
- Oran/dağılım → pie_chart
- 2+ dimension birlikte → sunburst veya treemap
- İki dönem karşılaştırması → comparison veya bar_chart

### x_field ve y_field
- Gerçek kolon adlarını yaz (örnek veriden al)
- x_field: genelde dimension kolon (kategori, şube, tarih)
- y_field: genelde metric kolon (tutar, miktar, toplam)
"""

CHART_GENERATOR_PROMPT = """Sen bir Plotly uzmanısın. Verilen karar ve veriye göre Plotly Python kodu oluştur.

## GÖRSELLEŞTIRME KARARI
{viz_decision}

## VERİ (tüm satırlar)
{data}

## KURALLAR
1. SADECE Python kodu döndür, açıklama veya import yazma
2. `go`, `px`, `pd` ve `data` değişkenleri ZATEN TANIMLI — import etme!
3. `fig` adında bir Plotly figure oluştur
4. Türkçe başlık ve etiketler kullan
5. `autosize=True` kullan (responsive değil)
6. x_field ve y_field olarak karar'daki kolon adlarını kullan

## ÇIKTI FORMATI
Sadece Python kodu:
```python
fig = px.bar(pd.DataFrame(data), x='kolon1', y='kolon2', ...)
fig.update_layout(title="...", autosize=True)
```
"""
