# Insight Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kullanıcı "Nelere dikkat etmeliyim?" gibi bir şey yazdığında `INSIGHT_REQUEST` intent'i tetiklenir; sistem mevcut sorgu sonuçlarını matematiksel olarak analiz edip LLM ile yorumlar ve yanıtın altında insight bloğu döner.

**Architecture:** `insight_engine` modülü 4 katmandan oluşur: (1) `ComparisonDataFetcher` karşılaştırma datasını çeker, (2) `MathEngine` Open/Closed plugin mimarisiyle 5 analyzer çalıştırır ve `Finding` listesi üretir, (3) `FindingsRanker` önem sırasına göre eleme yapar, (4) `LLMInterpreter` yalnızca sayıları yorumlar, kendi hesaplama yapmaz. Tüm matematiksel hesaplama deterministik Python'da gerçekleşir.

**Tech Stack:** Python 3.11, pandas, numpy, pyodbc (mevcut connection pool), LangChain structured output, pytest

---

## File Map

```
src/graphs/report_agent/
  ├── state.py                          MODIFY — 3 yeni field
  ├── prompts.py                        MODIFY — INSIGHT_REQUEST + InsightResult model
  ├── nodes.py                          MODIFY — insight_engine_node ekle
  ├── graph.py                          MODIFY — routing + wiring
  └── insight_engine/
        ├── __init__.py                 CREATE
        ├── models.py                   CREATE — Finding, AnalysisContext
        ├── engine.py                   CREATE — MathEngine orchestrator
        ├── ranker.py                   CREATE — FindingsRanker
        ├── fetcher.py                  CREATE — ComparisonDataFetcher (Mode A + B)
        ├── llm_interpreter.py          CREATE — LLMInterpreter
        └── analyzers/
              ├── __init__.py           CREATE
              ├── base.py               CREATE — BaseAnalyzer ABC
              ├── trend.py              CREATE — TrendAnalyzer
              ├── anomaly.py            CREATE — AnomalyDetector
              ├── segment.py            CREATE — SegmentComparator
              ├── multidim.py           CREATE — MultiDimAnalyzer
              └── seasonality.py        CREATE — SeasonalityAnalyzer

tests/graphs/report/insight_engine/
  ├── __init__.py                       CREATE
  ├── test_models.py                    CREATE
  ├── test_ranker.py                    CREATE
  ├── test_fetcher.py                   CREATE
  ├── test_engine.py                    CREATE
  ├── test_llm_interpreter.py           CREATE
  └── analyzers/
        ├── __init__.py                 CREATE
        ├── test_trend.py               CREATE
        ├── test_anomaly.py             CREATE
        ├── test_segment.py             CREATE
        ├── test_multidim.py            CREATE
        └── test_seasonality.py         CREATE
```

---

## Task 1: Finding ve AnalysisContext modelleri

**Files:**
- Create: `src/graphs/report_agent/insight_engine/__init__.py`
- Create: `src/graphs/report_agent/insight_engine/models.py`
- Create: `src/graphs/report_agent/insight_engine/analyzers/__init__.py`
- Create: `tests/graphs/report/insight_engine/__init__.py`
- Create: `tests/graphs/report/insight_engine/test_models.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_models.py

def test_finding_defaults():
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="trend_decline",
        analyzer="TrendAnalyzer",
        dimension="ProductName",
        value="Burger",
        metric="RowAmount",
        current_value=1250.0,
        comparison_value=1850.0,
        change_pct=-32.5,
        significance=0.91,
        period_label="son 7 gün vs önceki 7 gün",
    )
    assert f.extra == {}
    assert f.significance == 0.91


def test_analysis_context():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    ctx = AnalysisContext(
        user_query="satışlar",
        active_filters=[{"field": "BranchName", "value": "Ankara"}],
        period_label="Ocak 2024",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )
    assert ctx.dimension_columns == ["ProductName"]


def test_finding_to_dict():
    from src.graphs.report_agent.insight_engine.models import Finding
    f = Finding(
        type="anomaly_high",
        analyzer="AnomalyDetector",
        dimension="BranchName",
        value="Ankara",
        metric="RowAmount",
        current_value=9500.0,
        comparison_value=5000.0,
        change_pct=90.0,
        significance=0.85,
        period_label="bu ay",
        extra={"z_score": 2.8},
    )
    d = f.to_dict()
    assert d["type"] == "anomaly_high"
    assert d["extra"]["z_score"] == 2.8
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_models.py -v
```
Beklenen: `ModuleNotFoundError`

- [ ] **Step 3: `__init__.py` dosyalarını ve modeli oluştur**

```python
# src/graphs/report_agent/insight_engine/__init__.py
# (boş)
```

```python
# src/graphs/report_agent/insight_engine/analyzers/__init__.py
# (boş)
```

```python
# tests/graphs/report/insight_engine/__init__.py
# (boş)
```

```python
# tests/graphs/report/insight_engine/analyzers/__init__.py
# (boş)
```

```python
# src/graphs/report_agent/insight_engine/models.py
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalysisContext:
    user_query: str
    active_filters: List[Dict[str, Any]]
    period_label: str
    dimension_columns: List[str]
    metric_columns: List[str]


@dataclass
class Finding:
    type: str
    analyzer: str
    dimension: str
    value: str
    metric: str
    current_value: float
    comparison_value: float
    change_pct: float
    significance: float
    period_label: str
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "analyzer": self.analyzer,
            "dimension": self.dimension,
            "value": self.value,
            "metric": self.metric,
            "current_value": self.current_value,
            "comparison_value": self.comparison_value,
            "change_pct": round(self.change_pct, 2),
            "significance": round(self.significance, 3),
            "period_label": self.period_label,
            "extra": self.extra,
        }
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_models.py -v
```
Beklenen: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/ tests/graphs/report/insight_engine/
git commit -m "feat(insight): add Finding and AnalysisContext models"
```

---

## Task 2: BaseAnalyzer ABC

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/base.py`
- Create: `tests/graphs/report/insight_engine/analyzers/__init__.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/analyzers/__init__.py
# (boş)
```

Aşağıdaki testi geçici olarak `test_trend.py`'ye yaz (Task 3'te genişletilecek):

```python
# tests/graphs/report/insight_engine/analyzers/test_trend.py
import pandas as pd

def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="son 7 gün vs önceki 7 gün",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )

def test_base_analyzer_interface():
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    import inspect
    assert inspect.isabstract(BaseAnalyzer)
    assert hasattr(BaseAnalyzer, "analyze")
    assert hasattr(BaseAnalyzer, "name")
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_trend.py::test_base_analyzer_interface -v
```
Beklenen: `ModuleNotFoundError`

- [ ] **Step 3: BaseAnalyzer oluştur**

```python
# src/graphs/report_agent/insight_engine/analyzers/base.py
from abc import ABC, abstractmethod
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding


class BaseAnalyzer(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        ...
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_trend.py::test_base_analyzer_interface -v
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/base.py tests/graphs/report/insight_engine/analyzers/
git commit -m "feat(insight): add BaseAnalyzer ABC"
```

---

## Task 3: TrendAnalyzer

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/trend.py`
- Modify: `tests/graphs/report/insight_engine/analyzers/test_trend.py`

**Mantık:** Her dimension değeri için `change_pct = (current - comparison) / comparison * 100`. `|change_pct| >= 5` ise bulgu üretir. Significance: `min(abs(change_pct) / 100, 1.0)`. Zaman serisi varsa (tek boyut + birden fazla satır) numpy polyfit ile slope hesaplar.

- [ ] **Step 1: Failing testleri yaz**

```python
# tests/graphs/report/insight_engine/analyzers/test_trend.py
import pandas as pd


def _make_ctx(dims=None, metrics=None):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="son 7 gün vs önceki 7 gün",
        dimension_columns=dims or ["ProductName"],
        metric_columns=metrics or ["RowAmount"],
    )


def test_base_analyzer_interface():
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    import inspect
    assert inspect.isabstract(BaseAnalyzer)


def test_trend_decline_detected():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger", "Pizza"], "RowAmount": [1250.0, 2000.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger", "Pizza"], "RowAmount": [1850.0, 1900.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    declines = [f for f in findings if f.type == "trend_decline" and f.value == "Burger"]
    assert len(declines) == 1
    assert declines[0].change_pct < 0
    assert declines[0].significance > 0


def test_trend_increase_detected():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [2500.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    increases = [f for f in findings if f.type == "trend_increase"]
    assert len(increases) == 1
    assert increases[0].change_pct > 0


def test_small_change_ignored():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1020.0]})
    comparison = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, comparison, _make_ctx())
    assert len(findings) == 0  # %2 değişim — eşik altı


def test_empty_comparison_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({"ProductName": ["Burger"], "RowAmount": [1000.0]})
    findings = TrendAnalyzer().analyze(current, pd.DataFrame(), _make_ctx())
    assert findings == []


def test_time_series_slope():
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    current = pd.DataFrame({
        "DocumentDate": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        "RowAmount": [1000.0, 800.0, 600.0, 400.0, 200.0],
    })
    ctx = _make_ctx(dims=["DocumentDate"], metrics=["RowAmount"])
    findings = TrendAnalyzer().analyze(current, pd.DataFrame(), ctx)
    time_findings = [f for f in findings if f.type == "trend_decline"]
    assert len(time_findings) >= 1
    assert time_findings[0].extra.get("slope") is not None
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_trend.py -v
```
Beklenen: `ModuleNotFoundError: trend`

- [ ] **Step 3: TrendAnalyzer implement et**

```python
# src/graphs/report_agent/insight_engine/analyzers/trend.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

CHANGE_PCT_THRESHOLD = 5.0  # % — bu eşiğin altındaki değişimler görmezden gelinir


class TrendAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "TrendAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty:
            return findings

        # Zaman serisi tespiti: dimension tek bir date kolonu, birden fazla satır
        if (
            len(context.dimension_columns) == 1
            and comparison_df.empty
            and len(current_df) > 2
        ):
            findings.extend(self._analyze_time_series(current_df, context))
            return findings

        # Segment bazlı dönemsel karşılaştırma
        if comparison_df.empty:
            return findings
        findings.extend(self._analyze_segment_change(current_df, comparison_df, context))
        return findings

    def _analyze_segment_change(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        dim_cols = [c for c in context.dimension_columns if c in current_df.columns and c in comparison_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns and c in comparison_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]

        merged = current_df[[dim, metric]].merge(
            comparison_df[[dim, metric]].rename(columns={metric: f"{metric}_prev"}),
            on=dim,
            how="inner",
        )
        for _, row in merged.iterrows():
            cur = float(row[metric])
            prev = float(row[f"{metric}_prev"])
            if prev == 0:
                continue
            change_pct = (cur - prev) / prev * 100
            if abs(change_pct) < CHANGE_PCT_THRESHOLD:
                continue
            significance = min(abs(change_pct) / 100, 1.0)
            finding_type = "trend_increase" if change_pct > 0 else "trend_decline"
            findings.append(Finding(
                type=finding_type,
                analyzer=self.name,
                dimension=dim,
                value=str(row[dim]),
                metric=metric,
                current_value=cur,
                comparison_value=prev,
                change_pct=round(change_pct, 2),
                significance=round(significance, 3),
                period_label=context.period_label,
            ))
        return findings

    def _analyze_time_series(
        self,
        df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        metric_cols = [c for c in context.metric_columns if c in df.columns]
        if not metric_cols:
            return findings

        metric = metric_cols[0]
        values = df[metric].astype(float).values
        if len(values) < 3:
            return findings

        x = np.arange(len(values))
        slope, _ = np.polyfit(x, values, 1)
        # r_squared: korelasyon katsayısının karesi
        corr = np.corrcoef(x, values)[0, 1]
        r_squared = float(corr ** 2) if not np.isnan(corr) else 0.0

        # Slope anlamlı mı? Değer aralığına göre normalize et
        value_range = float(values.max() - values.min())
        if value_range == 0:
            return findings
        normalized_slope = abs(slope) / value_range
        if normalized_slope < 0.05:
            return findings

        significance = round(min(normalized_slope * r_squared, 1.0), 3)
        finding_type = "trend_decline" if slope < 0 else "trend_increase"
        findings.append(Finding(
            type=finding_type,
            analyzer=self.name,
            dimension=context.dimension_columns[0],
            value="zaman serisi",
            metric=metric,
            current_value=float(values[-1]),
            comparison_value=float(values[0]),
            change_pct=round((values[-1] - values[0]) / values[0] * 100, 2) if values[0] != 0 else 0.0,
            significance=significance,
            period_label=context.period_label,
            extra={"slope": round(float(slope), 4), "r_squared": round(r_squared, 4)},
        ))
        return findings
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_trend.py -v
```
Beklenen: 6 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/trend.py tests/graphs/report/insight_engine/analyzers/test_trend.py
git commit -m "feat(insight): add TrendAnalyzer"
```

---

## Task 4: AnomalyDetector

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/anomaly.py`
- Create: `tests/graphs/report/insight_engine/analyzers/test_anomaly.py`

**Mantık:** `current_df`'teki her dimension segmentinin metric değerini tüm segmentlerin ortalaması ve std'siyle karşılaştırır. Z-score: `(value - mean) / std`. `|z| >= 1.5` → bulgu üretir. Significance: `min(|z| / 4, 1.0)`.

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/analyzers/test_anomaly.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="şube performansı",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["BranchName"],
        metric_columns=["RowAmount"],
    )


def test_outlier_low_detected():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya"],
        "RowAmount": [1000.0, 9000.0, 8500.0, 9200.0, 8800.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    lows = [f for f in findings if f.type == "anomaly_low" and f.value == "Ankara"]
    assert len(lows) == 1
    assert lows[0].extra.get("z_score") is not None
    assert lows[0].extra["z_score"] < 0


def test_outlier_high_detected():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["Ankara", "İstanbul", "İzmir", "Bursa", "Antalya"],
        "RowAmount": [15000.0, 1000.0, 1200.0, 900.0, 1100.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    highs = [f for f in findings if f.type == "anomaly_high" and f.value == "Ankara"]
    assert len(highs) == 1


def test_no_anomaly_when_homogeneous():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({
        "BranchName": ["A", "B", "C", "D"],
        "RowAmount": [1000.0, 1010.0, 990.0, 1005.0],
    })
    findings = AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx())
    assert len(findings) == 0


def test_too_few_rows_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    df = pd.DataFrame({"BranchName": ["Ankara"], "RowAmount": [1000.0]})
    assert AnomalyDetector().analyze(df, pd.DataFrame(), _make_ctx()) == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_anomaly.py -v
```

- [ ] **Step 3: AnomalyDetector implement et**

```python
# src/graphs/report_agent/insight_engine/analyzers/anomaly.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

Z_SCORE_THRESHOLD = 1.5  # bu eşiğin üzerindeki z-score'lar anomali sayılır


class AnomalyDetector(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "AnomalyDetector"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty or len(current_df) < 3:
            return findings

        dim_cols = [c for c in context.dimension_columns if c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]
        values = current_df[metric].astype(float)
        mean = float(values.mean())
        std = float(values.std())
        if std == 0:
            return findings

        for _, row in current_df.iterrows():
            val = float(row[metric])
            z = (val - mean) / std
            if abs(z) < Z_SCORE_THRESHOLD:
                continue
            finding_type = "anomaly_high" if z > 0 else "anomaly_low"
            significance = round(min(abs(z) / 4, 1.0), 3)
            vs_avg_pct = round((val - mean) / mean * 100, 2) if mean != 0 else 0.0
            findings.append(Finding(
                type=finding_type,
                analyzer=self.name,
                dimension=dim,
                value=str(row[dim]),
                metric=metric,
                current_value=val,
                comparison_value=mean,
                change_pct=vs_avg_pct,
                significance=significance,
                period_label=context.period_label,
                extra={"z_score": round(z, 3), "mean": round(mean, 2), "std": round(std, 2)},
            ))
        return findings
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_anomaly.py -v
```
Beklenen: 4 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/anomaly.py tests/graphs/report/insight_engine/analyzers/test_anomaly.py
git commit -m "feat(insight): add AnomalyDetector"
```

---

## Task 5: SegmentComparator

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/segment.py`
- Create: `tests/graphs/report/insight_engine/analyzers/test_segment.py`

**Mantık:** Segment'leri kendi arasında sıralar. Top performer (en yüksek), bottom performer (en düşük), ve Pareto dominant (top-20% segmentin toplam içindeki payı %80'i geçiyorsa) bulgularını üretir. `vs_avg_pct = (value - mean) / mean * 100`.

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/analyzers/test_segment.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="kategori satışları",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["CategoryName"],
        metric_columns=["RowAmount"],
    )


def test_top_performer_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["İçecek", "Yiyecek", "Tatlı", "Atıştırmalık"],
        "RowAmount": [5000.0, 1000.0, 800.0, 700.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    tops = [f for f in findings if f.type == "top_performer" and f.value == "İçecek"]
    assert len(tops) == 1
    assert tops[0].significance > 0


def test_bottom_performer_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["A", "B", "C", "D"],
        "RowAmount": [5000.0, 4800.0, 4900.0, 100.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    bottoms = [f for f in findings if f.type == "bottom_performer" and f.value == "D"]
    assert len(bottoms) == 1


def test_pareto_dominant_detected():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({
        "CategoryName": ["A", "B", "C", "D", "E"],
        "RowAmount": [8000.0, 1000.0, 500.0, 300.0, 200.0],
    })
    findings = SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx())
    pareto = [f for f in findings if f.type == "pareto_dominant"]
    assert len(pareto) >= 1


def test_single_row_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    df = pd.DataFrame({"CategoryName": ["A"], "RowAmount": [5000.0]})
    assert SegmentComparator().analyze(df, pd.DataFrame(), _make_ctx()) == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_segment.py -v
```

- [ ] **Step 3: SegmentComparator implement et**

```python
# src/graphs/report_agent/insight_engine/analyzers/segment.py
import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

PARETO_THRESHOLD = 0.80   # top-20% bu oranı geçerse pareto_dominant
VS_AVG_THRESHOLD = 30.0   # % — ortalamanın bu kadar üstünde/altında olanlar raporlanır


class SegmentComparator(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "SegmentComparator"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty or len(current_df) < 2:
            return findings

        dim_cols = [c for c in context.dimension_columns if c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not dim_cols or not metric_cols:
            return findings

        dim = dim_cols[0]
        metric = metric_cols[0]
        df = current_df[[dim, metric]].copy()
        df[metric] = df[metric].astype(float)
        df = df.sort_values(metric, ascending=False).reset_index(drop=True)

        mean = float(df[metric].mean())
        total = float(df[metric].sum())
        if mean == 0 or total == 0:
            return findings

        # Top performer
        top_row = df.iloc[0]
        top_val = float(top_row[metric])
        top_vs_avg = (top_val - mean) / mean * 100
        if top_vs_avg >= VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="top_performer",
                analyzer=self.name,
                dimension=dim,
                value=str(top_row[dim]),
                metric=metric,
                current_value=top_val,
                comparison_value=mean,
                change_pct=round(top_vs_avg, 2),
                significance=round(min(top_vs_avg / 200, 1.0), 3),
                period_label=context.period_label,
                extra={"rank": 1, "total_segments": len(df)},
            ))

        # Bottom performer
        bottom_row = df.iloc[-1]
        bottom_val = float(bottom_row[metric])
        bottom_vs_avg = (bottom_val - mean) / mean * 100
        if bottom_vs_avg <= -VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="bottom_performer",
                analyzer=self.name,
                dimension=dim,
                value=str(bottom_row[dim]),
                metric=metric,
                current_value=bottom_val,
                comparison_value=mean,
                change_pct=round(bottom_vs_avg, 2),
                significance=round(min(abs(bottom_vs_avg) / 200, 1.0), 3),
                period_label=context.period_label,
                extra={"rank": len(df), "total_segments": len(df)},
            ))

        # Pareto: top-20% segmentin katkı payı
        top_n = max(1, len(df) // 5)
        top_share = float(df.iloc[:top_n][metric].sum()) / total
        if top_share >= PARETO_THRESHOLD:
            top_names = ", ".join(str(v) for v in df.iloc[:top_n][dim].tolist())
            findings.append(Finding(
                type="pareto_dominant",
                analyzer=self.name,
                dimension=dim,
                value=top_names,
                metric=metric,
                current_value=float(df.iloc[:top_n][metric].sum()),
                comparison_value=total,
                change_pct=round(top_share * 100, 2),
                significance=round(min((top_share - 0.5) * 2, 1.0), 3),
                period_label=context.period_label,
                extra={"top_n": top_n, "share_pct": round(top_share * 100, 2)},
            ))

        return findings
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_segment.py -v
```
Beklenen: 4 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/segment.py tests/graphs/report/insight_engine/analyzers/test_segment.py
git commit -m "feat(insight): add SegmentComparator"
```

---

## Task 6: MultiDimAnalyzer

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/multidim.py`
- Create: `tests/graphs/report/insight_engine/analyzers/test_multidim.py`

**Mantık:** `DayOfWeek` veya `Hour` kolonları varsa peak/weak period tespiti yapar. Her gün/saat için ortalamadan sapma hesaplar; en yüksek ve en düşük periyotları raporlar. İki veya daha fazla dimension kolonu varsa cross-analiz (segment1 × segment2 kombinasyonu) yapar.

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/analyzers/test_multidim.py
import pandas as pd


def _make_ctx(dims):
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="haftalık satışlar",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=dims,
        metric_columns=["RowAmount"],
    )


def test_peak_day_detected():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({
        "DayOfWeek": [1, 2, 3, 4, 5, 6, 7],
        "RowAmount": [1000.0, 900.0, 850.0, 800.0, 750.0, 5000.0, 300.0],
    })
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["DayOfWeek"]))
    peaks = [f for f in findings if f.type == "peak_period"]
    assert len(peaks) >= 1
    assert peaks[0].value == "6"


def test_weak_period_detected():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({
        "Hour": list(range(8, 22)),
        "RowAmount": [100.0 if h != 14 else 5000.0 for h in range(8, 22)],
    })
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["Hour"]))
    weaks = [f for f in findings if f.type == "weak_period"]
    assert len(weaks) >= 1


def test_no_time_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    df = pd.DataFrame({"ProductName": ["A", "B"], "RowAmount": [1000.0, 2000.0]})
    findings = MultiDimAnalyzer().analyze(df, pd.DataFrame(), _make_ctx(["ProductName"]))
    assert findings == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_multidim.py -v
```

- [ ] **Step 3: MultiDimAnalyzer implement et**

```python
# src/graphs/report_agent/insight_engine/analyzers/multidim.py
import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

TIME_DIM_COLUMNS = {"DayOfWeek", "Hour"}
VS_AVG_THRESHOLD = 40.0  # % — bu eşiğin üstünde/altında olanlar raporlanır


class MultiDimAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "MultiDimAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        if current_df.empty:
            return findings

        time_cols = [c for c in context.dimension_columns if c in TIME_DIM_COLUMNS and c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not time_cols or not metric_cols:
            return findings

        dim = time_cols[0]
        metric = metric_cols[0]
        df = current_df[[dim, metric]].copy()
        df[metric] = df[metric].astype(float)
        mean = float(df[metric].mean())
        if mean == 0:
            return findings

        peak_row = df.loc[df[metric].idxmax()]
        peak_val = float(peak_row[metric])
        peak_vs_avg = (peak_val - mean) / mean * 100
        if peak_vs_avg >= VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="peak_period",
                analyzer=self.name,
                dimension=dim,
                value=str(peak_row[dim]),
                metric=metric,
                current_value=peak_val,
                comparison_value=mean,
                change_pct=round(peak_vs_avg, 2),
                significance=round(min(peak_vs_avg / 200, 1.0), 3),
                period_label=context.period_label,
            ))

        weak_row = df.loc[df[metric].idxmin()]
        weak_val = float(weak_row[metric])
        weak_vs_avg = (weak_val - mean) / mean * 100
        if weak_vs_avg <= -VS_AVG_THRESHOLD:
            findings.append(Finding(
                type="weak_period",
                analyzer=self.name,
                dimension=dim,
                value=str(weak_row[dim]),
                metric=metric,
                current_value=weak_val,
                comparison_value=mean,
                change_pct=round(weak_vs_avg, 2),
                significance=round(min(abs(weak_vs_avg) / 200, 1.0), 3),
                period_label=context.period_label,
            ))

        return findings
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_multidim.py -v
```
Beklenen: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/multidim.py tests/graphs/report/insight_engine/analyzers/test_multidim.py
git commit -m "feat(insight): add MultiDimAnalyzer"
```

---

## Task 7: SeasonalityAnalyzer

**Files:**
- Create: `src/graphs/report_agent/insight_engine/analyzers/seasonality.py`
- Create: `tests/graphs/report/insight_engine/analyzers/test_seasonality.py`

**Mantık:** `DocumentDate` kolonu varsa ve yeterli satır varsa (≥14), günlük toplamların 7-lag autocorrelation'ını hesaplar. Yüksek autocorrelation (> 0.5) varsa `seasonal_peak` / `seasonal_trough` üretir.

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/analyzers/test_seasonality.py
import pandas as pd
import numpy as np


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="aylık satışlar",
        active_filters=[],
        period_label="son 30 gün",
        dimension_columns=["DocumentDate"],
        metric_columns=["RowAmount"],
    )


def test_weekly_seasonality_detected():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    # Haftalık tekrar: 7 günde bir yüksek
    dates = pd.date_range("2024-01-01", periods=28, freq="D").strftime("%Y-%m-%d").tolist()
    amounts = [5000.0 if i % 7 == 5 else 1000.0 for i in range(28)]  # Her 6. gün (cumartesi) yüksek
    df = pd.DataFrame({"DocumentDate": dates, "RowAmount": amounts})
    findings = SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx())
    assert len(findings) >= 1
    seasonal = [f for f in findings if f.type in ("seasonal_peak", "seasonal_trough")]
    assert len(seasonal) >= 1


def test_too_few_rows_skipped():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    df = pd.DataFrame({"DocumentDate": ["2024-01-01", "2024-01-02"], "RowAmount": [100.0, 200.0]})
    assert SeasonalityAnalyzer().analyze(df, pd.DataFrame(), _make_ctx()) == []


def test_no_date_column_returns_empty():
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    df = pd.DataFrame({"ProductName": ["A"], "RowAmount": [1000.0]})
    ctx = AnalysisContext("q", [], "p", ["ProductName"], ["RowAmount"])
    assert SeasonalityAnalyzer().analyze(df, pd.DataFrame(), ctx) == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_seasonality.py -v
```

- [ ] **Step 3: SeasonalityAnalyzer implement et**

```python
# src/graphs/report_agent/insight_engine/analyzers/seasonality.py
import logging
from typing import List

import numpy as np
import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)

MIN_ROWS = 14
AUTOCORR_THRESHOLD = 0.45
DATE_COLUMNS = {"DocumentDate"}


class SeasonalityAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        return "SeasonalityAnalyzer"

    def analyze(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        findings: List[Finding] = []
        date_cols = [c for c in context.dimension_columns if c in DATE_COLUMNS and c in current_df.columns]
        metric_cols = [c for c in context.metric_columns if c in current_df.columns]
        if not date_cols or not metric_cols:
            return findings

        date_col = date_cols[0]
        metric = metric_cols[0]
        df = current_df[[date_col, metric]].copy()
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.groupby(date_col)[metric].sum().reset_index().sort_values(date_col)

        if len(df) < MIN_ROWS:
            return findings

        values = df[metric].astype(float).values
        lag = 7
        if len(values) <= lag:
            return findings

        # Autocorrelation at lag 7
        v1 = values[:-lag]
        v2 = values[lag:]
        corr_matrix = np.corrcoef(v1, v2)
        autocorr = float(corr_matrix[0, 1]) if not np.isnan(corr_matrix[0, 1]) else 0.0

        if abs(autocorr) < AUTOCORR_THRESHOLD:
            return findings

        significance = round(min(abs(autocorr), 1.0), 3)

        # Peak: en yüksek 3 günün DayOfWeek'i
        df["dow"] = df[date_col].dt.dayofweek
        dow_avg = df.groupby("dow")[metric].mean()
        peak_dow = int(dow_avg.idxmax())
        trough_dow = int(dow_avg.idxmin())
        dow_names = {0: "Pazartesi", 1: "Salı", 2: "Çarşamba", 3: "Perşembe",
                     4: "Cuma", 5: "Cumartesi", 6: "Pazar"}

        findings.append(Finding(
            type="seasonal_peak",
            analyzer=self.name,
            dimension="DayOfWeek",
            value=dow_names.get(peak_dow, str(peak_dow)),
            metric=metric,
            current_value=float(dow_avg.max()),
            comparison_value=float(dow_avg.mean()),
            change_pct=round((dow_avg.max() - dow_avg.mean()) / dow_avg.mean() * 100, 2),
            significance=significance,
            period_label=context.period_label,
            extra={"autocorr_lag7": round(autocorr, 3)},
        ))

        if float(dow_avg.min()) < float(dow_avg.mean()) * 0.7:
            findings.append(Finding(
                type="seasonal_trough",
                analyzer=self.name,
                dimension="DayOfWeek",
                value=dow_names.get(trough_dow, str(trough_dow)),
                metric=metric,
                current_value=float(dow_avg.min()),
                comparison_value=float(dow_avg.mean()),
                change_pct=round((dow_avg.min() - dow_avg.mean()) / dow_avg.mean() * 100, 2),
                significance=round(significance * 0.8, 3),
                period_label=context.period_label,
                extra={"autocorr_lag7": round(autocorr, 3)},
            ))

        return findings
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/analyzers/test_seasonality.py -v
```
Beklenen: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/analyzers/seasonality.py tests/graphs/report/insight_engine/analyzers/test_seasonality.py
git commit -m "feat(insight): add SeasonalityAnalyzer"
```

---

## Task 8: MathEngine orchestrator

**Files:**
- Create: `src/graphs/report_agent/insight_engine/engine.py`
- Create: `tests/graphs/report/insight_engine/test_engine.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_engine.py
import pandas as pd


def _make_ctx():
    from src.graphs.report_agent.insight_engine.models import AnalysisContext
    return AnalysisContext(
        user_query="satışlar",
        active_filters=[],
        period_label="bu ay",
        dimension_columns=["ProductName"],
        metric_columns=["RowAmount"],
    )


def test_engine_runs_all_analyzers():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector

    current = pd.DataFrame({
        "ProductName": ["A", "B", "C", "D", "E"],
        "RowAmount": [5000.0, 1000.0, 900.0, 950.0, 920.0],
    })
    comparison = pd.DataFrame({
        "ProductName": ["A", "B", "C", "D", "E"],
        "RowAmount": [2000.0, 1000.0, 900.0, 950.0, 920.0],
    })
    engine = MathEngine(analyzers=[TrendAnalyzer(), AnomalyDetector()])
    findings = engine.run(current, comparison, _make_ctx())
    # TrendAnalyzer + AnomalyDetector en az bir bulgu üretmeli
    assert len(findings) >= 1


def test_engine_skips_failing_analyzer():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
    from src.graphs.report_agent.insight_engine.models import Finding

    class BrokenAnalyzer(BaseAnalyzer):
        @property
        def name(self):
            return "BrokenAnalyzer"
        def analyze(self, current_df, comparison_df, context):
            raise RuntimeError("broken")

    class GoodAnalyzer(BaseAnalyzer):
        @property
        def name(self):
            return "GoodAnalyzer"
        def analyze(self, current_df, comparison_df, context):
            return [Finding("t", "GoodAnalyzer", "d", "v", "m", 1.0, 0.0, 100.0, 0.9, "p")]

    engine = MathEngine(analyzers=[BrokenAnalyzer(), GoodAnalyzer()])
    findings = engine.run(pd.DataFrame(), pd.DataFrame(), _make_ctx())
    # BrokenAnalyzer hata verse bile GoodAnalyzer çalışmalı
    assert len(findings) == 1
    assert findings[0].analyzer == "GoodAnalyzer"


def test_engine_empty_df_returns_empty():
    from src.graphs.report_agent.insight_engine.engine import MathEngine
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    engine = MathEngine(analyzers=[TrendAnalyzer()])
    findings = engine.run(pd.DataFrame(), pd.DataFrame(), _make_ctx())
    assert findings == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_engine.py -v
```

- [ ] **Step 3: MathEngine implement et**

```python
# src/graphs/report_agent/insight_engine/engine.py
import logging
from typing import List

import pandas as pd

from src.graphs.report_agent.insight_engine.analyzers.base import BaseAnalyzer
from src.graphs.report_agent.insight_engine.models import AnalysisContext, Finding

logger = logging.getLogger(__name__)


class MathEngine:
    def __init__(self, analyzers: List[BaseAnalyzer]):
        self.analyzers = analyzers

    def run(
        self,
        current_df: pd.DataFrame,
        comparison_df: pd.DataFrame,
        context: AnalysisContext,
    ) -> List[Finding]:
        all_findings: List[Finding] = []
        for analyzer in self.analyzers:
            try:
                findings = analyzer.analyze(current_df, comparison_df, context)
                all_findings.extend(findings)
                logger.debug(f"[MATH_ENGINE] {analyzer.name}: {len(findings)} findings")
            except Exception as exc:
                logger.warning(f"[MATH_ENGINE] {analyzer.name} failed: {exc}")
        return all_findings


def build_default_engine() -> MathEngine:
    from src.graphs.report_agent.insight_engine.analyzers.trend import TrendAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.anomaly import AnomalyDetector
    from src.graphs.report_agent.insight_engine.analyzers.segment import SegmentComparator
    from src.graphs.report_agent.insight_engine.analyzers.multidim import MultiDimAnalyzer
    from src.graphs.report_agent.insight_engine.analyzers.seasonality import SeasonalityAnalyzer

    return MathEngine(analyzers=[
        TrendAnalyzer(),
        AnomalyDetector(),
        SegmentComparator(),
        MultiDimAnalyzer(),
        SeasonalityAnalyzer(),
    ])
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_engine.py -v
```
Beklenen: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/engine.py tests/graphs/report/insight_engine/test_engine.py
git commit -m "feat(insight): add MathEngine orchestrator with default engine factory"
```

---

## Task 9: FindingsRanker

**Files:**
- Create: `src/graphs/report_agent/insight_engine/ranker.py`
- Create: `tests/graphs/report/insight_engine/test_ranker.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_ranker.py
from src.graphs.report_agent.insight_engine.models import Finding


def _make_finding(sig: float, type_: str = "trend_decline") -> Finding:
    return Finding(
        type=type_, analyzer="A", dimension="D", value="V",
        metric="M", current_value=1.0, comparison_value=2.0,
        change_pct=-50.0, significance=sig, period_label="p",
    )


def test_ranker_sorts_by_significance():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    findings = [_make_finding(0.3), _make_finding(0.9), _make_finding(0.6)]
    ranked = FindingsRanker().rank(findings)
    sigs = [f.significance for f in ranked]
    assert sigs == sorted(sigs, reverse=True)


def test_ranker_filters_below_threshold():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    findings = [_make_finding(0.1), _make_finding(0.2), _make_finding(0.9)]
    ranked = FindingsRanker().rank(findings)
    assert all(f.significance >= 0.40 for f in ranked)
    assert len(ranked) == 1


def test_ranker_caps_at_top_n():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker, TOP_N
    findings = [_make_finding(float(i) / 10) for i in range(5, 15)]
    ranked = FindingsRanker().rank(findings)
    assert len(ranked) <= TOP_N


def test_ranker_empty_input():
    from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
    assert FindingsRanker().rank([]) == []
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_ranker.py -v
```

- [ ] **Step 3: FindingsRanker implement et**

```python
# src/graphs/report_agent/insight_engine/ranker.py
from typing import List

from src.graphs.report_agent.insight_engine.models import Finding

SIGNIFICANCE_THRESHOLD = 0.40
TOP_N = 8


class FindingsRanker:
    def rank(self, findings: List[Finding]) -> List[Finding]:
        filtered = [f for f in findings if f.significance >= SIGNIFICANCE_THRESHOLD]
        return sorted(filtered, key=lambda f: f.significance, reverse=True)[:TOP_N]
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_ranker.py -v
```
Beklenen: 4 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/ranker.py tests/graphs/report/insight_engine/test_ranker.py
git commit -m "feat(insight): add FindingsRanker"
```

---

## Task 10: ComparisonDataFetcher

**Files:**
- Create: `src/graphs/report_agent/insight_engine/fetcher.py`
- Create: `tests/graphs/report/insight_engine/test_fetcher.py`

**Mantık:**
- **Mode A:** `active_sql`'deki `BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'` pattern'ını regex ile bulur. Tarih farkını hesaplar (delta gün). Her iki tarihi de delta gün geri kaydırır ve yeni SQL üretir. DB'den çalıştırır.
- **Mode B:** `comparison_sql` state'te varsa direkt onu çalıştırır.
- Her iki moddan dönen sonuç `pd.DataFrame`'e dönüştürülür.

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_fetcher.py
import pandas as pd
from unittest.mock import AsyncMock, patch


def test_mode_a_shifts_dates():
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    sql = "SELECT ProductName, SUM(RowAmount) FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31' GROUP BY ProductName"
    shifted = ComparisonDataFetcher._shift_sql_dates(sql)
    # 31 günlük fark → Aralık 2023
    assert "2023-12-01" in shifted
    assert "2023-12-31" in shifted


def test_mode_a_no_date_returns_none():
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    sql = "SELECT * FROM T WHERE BranchName = 'Ankara'"
    assert ComparisonDataFetcher._shift_sql_dates(sql) is None


def test_mode_b_uses_comparison_sql():
    """Mode B: comparison_sql varsa onu kullan."""
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    state = {
        "active_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31'",
        "comparison_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2023-01-01' AND '2023-01-31'",
    }
    fetcher = ComparisonDataFetcher(connection_string="mssql+pyodbc://test")
    # comparison_sql varsa _shift_sql_dates çağrılmamalı
    sql = fetcher._resolve_comparison_sql(state)
    assert sql == state["comparison_sql"]


def test_mode_a_selected_when_no_comparison_sql():
    from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
    state = {
        "active_sql": "SELECT * FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31'",
    }
    fetcher = ComparisonDataFetcher(connection_string="mssql+pyodbc://test")
    sql = fetcher._resolve_comparison_sql(state)
    assert sql is not None
    assert "2023-12-01" in sql
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_fetcher.py -v
```

- [ ] **Step 3: ComparisonDataFetcher implement et**

```python
# src/graphs/report_agent/insight_engine/fetcher.py
import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DATE_BETWEEN_RE = re.compile(
    r"BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'",
    re.IGNORECASE,
)


class ComparisonDataFetcher:
    def __init__(self, connection_string: str):
        self._connection_string = connection_string

    @staticmethod
    def _shift_sql_dates(sql: str) -> Optional[str]:
        match = _DATE_BETWEEN_RE.search(sql)
        if not match:
            return None
        start_str, end_str = match.group(1), match.group(2)
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        delta = (end - start) + timedelta(days=1)
        new_end = start - timedelta(days=1)
        new_start = new_end - delta + timedelta(days=1)
        shifted = sql.replace(
            match.group(0),
            f"BETWEEN '{new_start.isoformat()}' AND '{new_end.isoformat()}'",
        )
        logger.debug(f"[FETCHER] Mode A: {start_str}–{end_str} → {new_start}–{new_end}")
        return shifted

    def _resolve_comparison_sql(self, state: Dict[str, Any]) -> Optional[str]:
        comparison_sql = state.get("comparison_sql")
        if comparison_sql:
            logger.info("[FETCHER] Mode B: using user-provided comparison_sql")
            return comparison_sql
        active_sql = state.get("active_sql", "")
        shifted = self._shift_sql_dates(active_sql)
        if shifted:
            logger.info("[FETCHER] Mode A: shifted date range from active_sql")
        return shifted

    async def fetch(self, state: Dict[str, Any]) -> pd.DataFrame:
        from src.graphs.report_agent.subagents.text2sql.nodes import _execute_sql_async
        comparison_sql = self._resolve_comparison_sql(state)
        if not comparison_sql:
            logger.info("[FETCHER] No comparison SQL resolved — skipping comparison fetch")
            return pd.DataFrame()
        try:
            rows: List[Dict[str, Any]] = await _execute_sql_async(
                self._connection_string, comparison_sql
            )
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception as exc:
            logger.warning(f"[FETCHER] Comparison fetch failed: {exc}")
            return pd.DataFrame()
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_fetcher.py -v
```
Beklenen: 4 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/fetcher.py tests/graphs/report/insight_engine/test_fetcher.py
git commit -m "feat(insight): add ComparisonDataFetcher (Mode A auto-shift + Mode B user SQL)"
```

---

## Task 11: LLMInterpreter

**Files:**
- Create: `src/graphs/report_agent/insight_engine/llm_interpreter.py`
- Create: `tests/graphs/report/insight_engine/test_llm_interpreter.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_llm_interpreter.py
from unittest.mock import AsyncMock, MagicMock
from src.graphs.report_agent.insight_engine.models import Finding, AnalysisContext


def _make_finding(type_="trend_decline", value="Burger", sig=0.9) -> Finding:
    return Finding(
        type=type_, analyzer="TrendAnalyzer", dimension="ProductName",
        value=value, metric="RowAmount", current_value=1250.0,
        comparison_value=1850.0, change_pct=-32.5, significance=sig,
        period_label="son 7 gün vs önceki 7 gün",
    )


def test_build_prompt_contains_findings():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("nelere dikkat etmeliyim", [], "bu ay", ["ProductName"], ["RowAmount"])
    findings = [_make_finding()]
    llm_mock = MagicMock()
    interpreter = LLMInterpreter(llm_mock)
    prompt = interpreter._build_prompt(findings, ctx)
    assert "trend_decline" in prompt
    assert "Burger" in prompt
    assert "-32.5" in prompt
    assert "hesaplama yapma" in prompt.lower() or "kendi hesaplama" in prompt.lower()


def test_build_prompt_no_findings():
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("nelere dikkat", [], "bu ay", ["ProductName"], ["RowAmount"])
    llm_mock = MagicMock()
    interpreter = LLMInterpreter(llm_mock)
    prompt = interpreter._build_prompt([], ctx)
    assert "bulgu" in prompt.lower() or "bulunamadı" in prompt.lower()


def test_interpret_returns_string():
    import asyncio
    from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
    ctx = AnalysisContext("insight ver", [], "bu ay", ["ProductName"], ["RowAmount"])
    findings = [_make_finding()]
    llm_mock = MagicMock()
    llm_mock.ainvoke = AsyncMock(return_value=MagicMock(content="Burger satışları düştü. Kampanya öneririm."))
    interpreter = LLMInterpreter(llm_mock)
    result = asyncio.run(interpreter.interpret(findings, ctx))
    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_llm_interpreter.py -v
```

- [ ] **Step 3: LLMInterpreter implement et**

```python
# src/graphs/report_agent/insight_engine/llm_interpreter.py
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
    def __init__(self, llm):
        self._llm = llm

    def _build_prompt(self, findings: List[Finding], context: AnalysisContext) -> str:
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
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_llm_interpreter.py -v
```
Beklenen: 3 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/insight_engine/llm_interpreter.py tests/graphs/report/insight_engine/test_llm_interpreter.py
git commit -m "feat(insight): add LLMInterpreter — findings JSON → natural language + action recommendations"
```

---

## Task 12: State değişiklikleri

**Files:**
- Modify: `src/graphs/report_agent/state.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_state_fields.py

def test_insight_fields_in_report_state():
    from src.graphs.report_agent.state import ReportState, create_initial_state
    state = create_initial_state()
    assert "comparison_sql" in state
    assert "insight_findings" in state
    assert "insight_output" in state
    assert state["comparison_sql"] is None
    assert state["insight_findings"] is None
    assert state["insight_output"] is None
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_state_fields.py -v
```
Beklenen: `AssertionError: 'comparison_sql' not in state`

- [ ] **Step 3: state.py'yi güncelle**

`src/graphs/report_agent/state.py` dosyasında `# Response` bloğunun üzerine şu satırları ekle:

```python
    # Insight Engine
    comparison_sql: Optional[str]           # Mode B: kullanıcının verdiği karşılaştırma SQL'i
    insight_findings: Optional[List[Dict[str, Any]]]  # Ranker çıktısı (debug için)
    insight_output: Optional[str]           # LLM Interpreter çıktısı
```

`create_initial_state()` fonksiyonuna şunları ekle:

```python
        comparison_sql=None,
        insight_findings=None,
        insight_output=None,
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_state_fields.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/state.py tests/graphs/report/insight_engine/test_state_fields.py
git commit -m "feat(insight): add comparison_sql, insight_findings, insight_output to ReportState"
```

---

## Task 13: INSIGHT_REQUEST intent — prompts.py

**Files:**
- Modify: `src/graphs/report_agent/prompts.py`

**Yapılacaklar:**
1. `IntentClassificationResult.intent_type` Literal'ine `"INSIGHT_REQUEST"` ekle
2. `INTENT_CLASSIFIER_PROMPT`'a `INSIGHT_REQUEST` açıklamasını ekle

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_insight_intent.py

def test_intent_type_includes_insight_request():
    from src.graphs.report_agent.prompts import IntentClassificationResult
    import typing
    hints = typing.get_type_hints(IntentClassificationResult)
    # Pydantic v2 Literal annotation'ı kontrol et
    from pydantic.fields import FieldInfo
    field = IntentClassificationResult.model_fields["intent_type"]
    annotation_str = str(field.annotation)
    assert "INSIGHT_REQUEST" in annotation_str
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_insight_intent.py -v
```

- [ ] **Step 3: prompts.py'yi güncelle**

`IntentClassificationResult.intent_type` alanını şu şekilde güncelle:

```python
    intent_type: Literal["NEW_QUERY", "MODIFY_QUERY", "USE_RESULT", "VAGUE_QUERY", "INSIGHT_REQUEST"]
```

`INTENT_CLASSIFIER_PROMPT` içinde intent açıklamalarının bulunduğu bölüme şunu ekle (mevcut intent listesinin sonuna):

```
- INSIGHT_REQUEST: Kullanıcı mevcut veriden içgörü, trend analizi, anomali veya aksiyon önerisi istiyor.
  Örnek: "nelere dikkat etmeliyim", "bu veriden ne çıkarabilirim", "hangi ürün/şube sorunlu", "insight ver", "analiz et"
  SADECE aktif sonuç varsa (has_active_sql=Evet) bu intent'i kullan.
  Aktif sonuç yoksa VAGUE_QUERY kullan.
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_insight_intent.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/prompts.py tests/graphs/report/insight_engine/test_insight_intent.py
git commit -m "feat(insight): add INSIGHT_REQUEST to IntentClassificationResult and classifier prompt"
```

---

## Task 14: insight_engine_node — nodes.py

**Files:**
- Modify: `src/graphs/report_agent/nodes.py`

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_insight_node.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_insight_node_returns_insight_output():
    import pandas as pd
    from src.graphs.report_agent.nodes import create_insight_engine_node

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Test insight çıktısı."))

    state = {
        "user_query": "insight ver",
        "active_results": [
            {"ProductName": "Burger", "RowAmount": 1250.0},
            {"ProductName": "Pizza", "RowAmount": 2000.0},
            {"ProductName": "Salad", "RowAmount": 500.0},
            {"ProductName": "Wrap", "RowAmount": 100.0},
            {"ProductName": "Soup", "RowAmount": 4500.0},
        ],
        "active_sql": "SELECT ProductName, SUM(RowAmount) FROM T WHERE DocumentDate BETWEEN '2024-01-01' AND '2024-01-31' GROUP BY ProductName",
        "active_filters": [],
        "comparison_sql": None,
        "semantic_intent": {"time": {"granularity": "monthly"}},
        "visualization_output": None,
    }

    with patch(
        "src.graphs.report_agent.insight_engine.fetcher.ComparisonDataFetcher.fetch",
        new=AsyncMock(return_value=pd.DataFrame()),
    ):
        node = create_insight_engine_node(mock_llm, "mssql+pyodbc://test")
        result = asyncio.run(node(state))

    assert "insight_output" in result
    assert isinstance(result["insight_output"], str)
    assert len(result["insight_output"]) > 0
    assert "insight_findings" in result


def test_insight_node_no_active_results():
    import asyncio
    from src.graphs.report_agent.nodes import create_insight_engine_node
    mock_llm = MagicMock()
    state = {
        "user_query": "insight ver",
        "active_results": None,
        "active_sql": None,
        "active_filters": [],
        "comparison_sql": None,
        "semantic_intent": None,
        "visualization_output": None,
    }
    node = create_insight_engine_node(mock_llm, "mssql+pyodbc://test")
    result = asyncio.run(node(state))
    assert "insight_output" in result
    # Sonuç yoksa açıklayıcı mesaj dönmeli
    assert result["insight_output"] is not None
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_insight_node.py -v
```

- [ ] **Step 3: nodes.py'ye insight_engine_node ekle**

`nodes.py` dosyasının en üstüne import'ları ekle:

```python
from src.graphs.report_agent.insight_engine.engine import build_default_engine
from src.graphs.report_agent.insight_engine.fetcher import ComparisonDataFetcher
from src.graphs.report_agent.insight_engine.llm_interpreter import LLMInterpreter
from src.graphs.report_agent.insight_engine.models import AnalysisContext
from src.graphs.report_agent.insight_engine.ranker import FindingsRanker
```

Dosyanın sonuna şu factory fonksiyonu ekle:

```python
def create_insight_engine_node(llm, connection_string: str):
    math_engine = build_default_engine()
    ranker = FindingsRanker()
    interpreter = LLMInterpreter(llm)
    fetcher = ComparisonDataFetcher(connection_string)

    @debug_node("insight_engine")
    async def insight_engine_node(state: dict) -> dict:
        import pandas as pd

        active_results = state.get("active_results") or []
        if not active_results:
            logger.info("[INSIGHT_ENGINE] No active_results — skipping analysis")
            return {
                "insight_output": "Analiz yapılacak mevcut sorgu sonucu yok. Önce bir rapor sorusu sorun.",
                "insight_findings": [],
            }

        current_df = pd.DataFrame(active_results)
        comparison_df = await fetcher.fetch(state)

        semantic_intent = state.get("semantic_intent") or {}
        viz_output = state.get("visualization_output") or {}

        dim_columns = _detect_columns(current_df, viz_output, role="dimension")
        metric_columns = _detect_columns(current_df, viz_output, role="metric")
        period_label = _build_period_label(state)

        context = AnalysisContext(
            user_query=state.get("user_query", ""),
            active_filters=state.get("active_filters") or [],
            period_label=period_label,
            dimension_columns=dim_columns,
            metric_columns=metric_columns,
        )

        all_findings = math_engine.run(current_df, comparison_df, context)
        ranked = ranker.rank(all_findings)

        logger.info(f"[INSIGHT_ENGINE] {len(all_findings)} findings → {len(ranked)} ranked")

        insight_text = await interpreter.interpret(ranked, context)

        return {
            "insight_output": insight_text,
            "insight_findings": [f.to_dict() for f in ranked],
        }

    return insight_engine_node


def _detect_columns(df, viz_output: dict, role: str):
    """viz_output'tan dim/metric kolonlarını al; yoksa df'ten tahmin et."""
    import pandas as pd

    if role == "dimension":
        if viz_output.get("x_field") and viz_output["x_field"] in df.columns:
            return [viz_output["x_field"]]
        return [c for c in df.columns if df[c].dtype == object or str(df[c].dtype) == "category"]

    if role == "metric":
        if viz_output.get("y_field") and viz_output["y_field"] in df.columns:
            return [viz_output["y_field"]]
        return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]

    return []


def _build_period_label(state: dict) -> str:
    """active_sql'den tarih aralığını oku ve okunabilir label üret."""
    import re
    sql = state.get("active_sql", "")
    match = re.search(r"BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'", sql, re.IGNORECASE)
    if match:
        return f"{match.group(1)} – {match.group(2)}"
    return "mevcut dönem"
```

- [ ] **Step 4: Testi çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_insight_node.py -v
```
Beklenen: 2 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/graphs/report_agent/nodes.py tests/graphs/report/insight_engine/test_insight_node.py
git commit -m "feat(insight): add insight_engine_node to nodes.py"
```

---

## Task 15: Graph wiring — routing + build_response entegrasyonu

**Files:**
- Modify: `src/graphs/report_agent/graph.py`
- Modify: `src/graphs/report_agent/nodes.py` — `classify_intent_node` return_dict'e insight reset ekle

**Yapılacaklar:**
1. `_intent_router`'a `INSIGHT_REQUEST` dalı ekle
2. Graph'a `insight_engine` node'u ekle
3. `insight_engine → build_response` edge'i ekle
4. `build_report_agent_graph` factory'ye `create_insight_engine_node` çağrısı ekle
5. `classify_intent_node` return_dict'ine `"insight_output": None, "insight_findings": None` ekle
6. `build_response_node`'un insight_output'u yanıta dahil etmesini sağla

- [ ] **Step 1: Failing testi yaz**

```python
# tests/graphs/report/insight_engine/test_graph_routing.py

def test_intent_router_insight_request():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "INSIGHT_REQUEST"}) == "insight_engine"


def test_intent_router_existing_routes_unchanged():
    from src.graphs.report_agent.graph import _intent_router
    assert _intent_router({"intent_type": "NEW_QUERY"}) == "text2sql"
    assert _intent_router({"intent_type": "MODIFY_QUERY"}) == "modify_sql"
    assert _intent_router({"intent_type": "VAGUE_QUERY"}) == "report_chat"
```

- [ ] **Step 2: Testi çalıştır — FAIL bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_graph_routing.py -v
```
Beklenen: `AssertionError: 'text2sql' != 'insight_engine'`

- [ ] **Step 3: graph.py'yi güncelle**

`_intent_router` fonksiyonuna `INSIGHT_REQUEST` dalını ekle:

```python
def _intent_router(state: dict) -> str:
    intent = state.get("intent_type", "NEW_QUERY")
    if intent == "MODIFY_QUERY":
        return "modify_sql"
    if intent == "VAGUE_QUERY":
        return "report_chat"
    if intent == "INSIGHT_REQUEST":
        return "insight_engine"
    if intent == "USE_RESULT":
        use_result = state.get("use_result_type")
        if use_result == "revisualize":
            return "visualization"
        if use_result == "compute":
            return "compute_results"
        return "extract_entity"
    return "text2sql"
```

`build_report_agent_graph` fonksiyonuna `insight_engine_node` ekle:

```python
# import ekle (fonksiyon başında diğer import'larla birlikte)
from src.graphs.report_agent.nodes import (
    ...
    create_insight_engine_node,
)

# graph.add_node satırlarına ekle:
graph.add_node("insight_engine", create_insight_engine_node(llm, connection_string))

# conditional_edges'e "insight_engine" dalını ekle:
graph.add_conditional_edges(
    "classify_intent",
    _intent_router,
    {
        "text2sql":        "text2sql",
        "modify_sql":      "modify_sql",
        "extract_entity":  "extract_entity",
        "visualization":   "visualization",
        "compute_results": "compute_results",
        "report_chat":     "report_chat",
        "insight_engine":  "insight_engine",   # YENİ
    },
)

# Edge ekle:
graph.add_edge("insight_engine", "build_response")
```

- [ ] **Step 4: `classify_intent_node` return_dict'ini güncelle**

`nodes.py`'deki `classify_intent_node`'un `return_dict` kısmına şunları ekle:

```python
        return_dict = {
            ...
            "insight_output": None,
            "insight_findings": None,
            "comparison_sql": None,
        }
```

- [ ] **Step 5: `build_response_node`'u insight için güncelle**

`nodes.py`'deki `create_build_response_node` içinde, `build_response_node` async fonksiyonunun en başına şu bloğu ekle (`error = state.get("error")` satırından önce):

```python
        # INSIGHT_REQUEST: insight_engine_node çıktısını doğrudan döndür
        if state.get("intent_type") == "INSIGHT_REQUEST":
            insight_output = state.get("insight_output") or "Analiz tamamlandı ancak sonuç üretilemedi."
            return {
                "final_response": insight_output,
                "messages": [AIMessage(content=insight_output)],
            }
```

Dosyada tam konum: `src/graphs/report_agent/nodes.py` satır ~595 (build_response_node async fonksiyonunun hemen içi, `error = state.get("error")` satırından önce).

- [ ] **Step 6: Tüm routing testlerini çalıştır — PASS bekleniyor**

```
pytest tests/graphs/report/insight_engine/test_graph_routing.py tests/graphs/report/test_graph_routing.py -v
```
Beklenen: Tüm mevcut testler PASS, yeni test de PASS

- [ ] **Step 7: Tüm insight testlerini çalıştır**

```
pytest tests/graphs/report/insight_engine/ -v
```
Beklenen: Tüm testler PASS

- [ ] **Step 8: Commit**

```bash
git add src/graphs/report_agent/graph.py src/graphs/report_agent/nodes.py
git commit -m "feat(insight): wire insight_engine node into report_agent graph — INSIGHT_REQUEST routing complete"
```

---

## Son Doğrulama

- [ ] Tüm testleri çalıştır

```
pytest tests/graphs/report/insight_engine/ tests/graphs/report/test_graph_routing.py -v
```

- [ ] Smoke test — mevcut testlerde regresyon yok mu?

```
pytest tests/graphs/report/ -v --tb=short
```

---

## Kapsam Özeti

| Bileşen | Dosya | Test |
|---------|-------|------|
| Finding + AnalysisContext | `insight_engine/models.py` | `test_models.py` |
| BaseAnalyzer | `analyzers/base.py` | `test_trend.py`'de |
| TrendAnalyzer | `analyzers/trend.py` | `test_trend.py` |
| AnomalyDetector | `analyzers/anomaly.py` | `test_anomaly.py` |
| SegmentComparator | `analyzers/segment.py` | `test_segment.py` |
| MultiDimAnalyzer | `analyzers/multidim.py` | `test_multidim.py` |
| SeasonalityAnalyzer | `analyzers/seasonality.py` | `test_seasonality.py` |
| MathEngine | `insight_engine/engine.py` | `test_engine.py` |
| FindingsRanker | `insight_engine/ranker.py` | `test_ranker.py` |
| ComparisonDataFetcher | `insight_engine/fetcher.py` | `test_fetcher.py` |
| LLMInterpreter | `insight_engine/llm_interpreter.py` | `test_llm_interpreter.py` |
| State | `state.py` | `test_state_fields.py` |
| INSIGHT_REQUEST intent | `prompts.py` | `test_insight_intent.py` |
| insight_engine_node | `nodes.py` | `test_insight_node.py` |
| Graph wiring | `graph.py` | `test_graph_routing.py` |
