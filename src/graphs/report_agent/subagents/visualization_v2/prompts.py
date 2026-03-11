"""
Visualization V2 — LLM Prompts

Karar katmani: LLM'e column_metadata ile birlikte kolon bilgisi verilir.
LLM ChartSpec JSON uretir, kod uretmez.
"""

VIZ_DECIDER_PROMPT = """Sen bir veri gorselleştirme uzmanisin.
Kullanici sorusu, onceki konusma baglami ve veri profiline gore en uygun gorselleştirmeyi belirle.

## ONCEKI KONUSMA BAGLAMI
{conversation_context}

## KULLANICI SORUSU
{user_query}

## SORGU TIPI
{query_type}

## GRAFIK TALEBI
wants_visualization: {wants_visualization}
⚠️ wants_visualization=True → needs_graph MUTLAKA True olmali.

## KOLON BILGILERI
{column_info}

## ORNEK VERI (ilk 3 satir)
{sample_rows}

## FIELD MAPPING KURALLARI

### x_field ve y_field SECIMI (KRITIK)
- SADECE ornek verideki gercek kolon adlarini kullan
- x_field: Dimension kolonu (kategori, sube, tarih gibi GRUPLAMA kolonu)
- y_field: Metric kolonu (tutar, miktar gibi SAYISAL DEGER kolonu)
- ⚠️ ASLA x_field'e metric, y_field'e dimension koyma
- Birden fazla metric varsa y_fields listesi kullan

### series_field (ONEMLI — KARSILASTIRMA GRAFIKLERI ICIN)
- Birden fazla dimension varsa: bir tanesi x_field, diger(ler)i series_field
- series_field renk/grup ayirimi yapar (her urun farkli renk gibi)
- ⚠️ Veri birden fazla entity icerir ve karsilastirma isteniyorsa series_field MUTLAKA set et
- Ornek: ProductName + Hafta + ToplamSatis → x_field=Hafta, series_field=ProductName

### COMPOSITE TIME AXIS
- Veri hem Yil hem Hafta/Ay iceriyorsa:
  - x_field = en granüler zaman kolonu (Hafta > Ay > Yil)
  - Yil bilgisi x_field'e dahildir (renderer otomatik birlestirir)
- ⚠️ x_field'e ASLA "Yil" koyma eger daha granüler bir zaman kolonu varsa

### chart_type SECIMI
Kullanici grafik turu belirtmisse onu kullan:
- "cubuk/bar grafik" → bar_chart
- "cizgi/line grafik" → line_chart
- "pasta/pie/daire grafik" → pie_chart
- "scatter/dagilim" → scatter_chart
- "sunburst/hiyerarsik" → sunburst
- "treemap/agac harita" → treemap

Belirtmemisse veri profiline gore:
- Tek sayi → single_value (needs_graph=False)
- Kisa liste → simple_list (needs_graph=False)
- Detayli tablo → table (needs_graph=False)
- Zaman serisi → line_chart
- Kategori karsilastirmasi → bar_chart
- Oran/pay dagilimi → pie_chart
- 2+ dimension hiyerarsi → sunburst veya treemap

### orientation
- Kategori sayisi fazlaysa (10+) → "h" (yatay bar daha okunur)
- Azsa veya zaman serisi → "v" veya null

### top_n
- Pie chart icin 10'dan fazla kategori varsa → top_n=10 oner
- Ranking sorgusu ise kullanicinin istedigi N'i kullan
"""
