# data_visualization/nodes/plotly_code_generator.py

import json
import logging
from typing import Dict, Any

from src.models.llm import LLM
from ..state import (
    DataVisualizationState,
    OutputType,
    ChartConfig
)

logger = logging.getLogger(__name__)


class PlotlyCodeGenerator:
    """
    Generates and executes Plotly Python code using LLM.
    Single LLM call - generates executable Python code.
    """

    def __init__(self, llm: LLM):
        """Initialize with LLM instance"""
        self.llm = llm
        self.chat_model = llm.get_chat()

    SYSTEM_PROMPT = """Sen bir Plotly uzmanısın.
Verilen chart konfigürasyonu ve veriye göre çalışan Plotly Python kodu oluştur.

ÖNEMLİ: go, px, pd ve data değişkenleri ZATEN TANIMLI! Import etme!

KURALLAR:
1. SADECE Python kodu döndür, başka hiçbir metin yazma
2. Import satırları YAZMA (go, px, pd zaten hazır!)
3. Kod içinde 'fig' adında bir plotly figure oluştur
4. Data ve config'e göre en uygun chart'ı oluştur
5. Türkçe başlıklar ve etiketler kullan
6. autosize=True ve profesyonel görünüm sağla (responsive değil, autosize kullan!)

KULLANILABILIR DEGISKENLER:
- go: plotly.graph_objects (HAZIR!)
- px: plotly.express (HAZIR!)
- pd: pandas (HAZIR!)
- data: Chart verisi (list of dicts) (HAZIR!)

KOD FORMATI (import YOK!):
```python
# Chart oluşturma (import yok!)
fig = go.Figure(...)
# veya
fig = px.bar(...)

# Layout ayarları
fig.update_layout(
    title="...",
    autosize=True,
    ...
)
```

SADECE Python kodu döndür, açıklama ve import yazma!"""

    def generate(self, state: DataVisualizationState) -> DataVisualizationState:
        """Generate Plotly code and execute it"""

        logger.info("=" * 60)
        logger.info("PLOTLY CODE GENERATOR NODE STARTED")
        logger.info("=" * 60)

        chart_config = state.get("chart_config")
        data = state.get("raw_data", [])
        viz_decision = state.get("viz_decision")

        logger.info(f"State keys: {list(state.keys())}")
        logger.info(f"viz_decision: {viz_decision}")
        logger.info(f"chart_config: {chart_config is not None}")
        logger.info(f"data: {len(data) if data else 0} rows")

        # Skip if no visualization needed
        if not viz_decision:
            logger.warning("❌ No viz_decision found, skipping Plotly generation")
            return {
                **state,
                "plotly_code": None,
                "plotly_figure": None
            }

        needs_graph = viz_decision.get("needs_graph")
        logger.info(f"needs_graph: {needs_graph}")

        if not needs_graph:
            logger.info("❌ No graph needed, skipping Plotly generation")
            return {
                **state,
                "plotly_code": None,
                "plotly_figure": None
            }

        if not chart_config or not data:
            logger.warning(f"❌ Missing chart_config ({chart_config is not None}) or data ({len(data) if data else 0})")
            return {
                **state,
                "plotly_code": None,
                "plotly_figure": None,
                "error": "Missing chart configuration or data for visualization"
            }

        output_type = chart_config.get("type")
        logger.info(f"Output type: {output_type}")

        # Skip non-chart types
        if output_type in [OutputType.SINGLE_VALUE, OutputType.SIMPLE_LIST, OutputType.TABLE]:
            logger.info(f"❌ Output type {output_type} doesn't need Plotly chart")
            return {
                **state,
                "plotly_code": None,
                "plotly_figure": None
            }

        logger.info(f"✅ GENERATING PLOTLY CODE for {output_type}")
        logger.info(f"Data sample: {data[0] if data else 'empty'}")

        try:
            # Prepare prompt
            prompt = self._create_prompt(chart_config, data, output_type)

            # Get LLM response
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]

            response = self.chat_model.invoke(messages)
            code = response.content.strip()

            logger.info(f"LLM response received: {len(code)} chars")
            logger.info(f"Raw code (first 300 chars):\n{code[:300]}")

            # Clean code (remove markdown if present)
            code = self._clean_code(code)

            logger.info("✅ Plotly code generated successfully")
            logger.info(f"Cleaned code (first 500 chars):\n{code[:500]}")
            logger.info(f"Full code:\n{code}")

            # Execute code
            logger.info("Executing Plotly code...")
            plotly_figure = self._execute_code(code, data)

            if plotly_figure:
                logger.info("✅✅✅ Plotly figure created successfully!")
                logger.info(f"Figure type: {type(plotly_figure)}")
                logger.info(f"Figure keys: {plotly_figure.keys() if isinstance(plotly_figure, dict) else 'N/A'}")
                return {
                    **state,
                    "plotly_code": code,
                    "plotly_figure": plotly_figure
                }
            else:
                logger.error("❌ Code execution failed to create figure")
                return {
                    **state,
                    "plotly_code": code,
                    "plotly_figure": None,
                    "error": "Failed to create Plotly figure"
                }

        except Exception as e:
            logger.error(f"Plotly generation error: {str(e)}", exc_info=True)
            return {
                **state,
                "plotly_code": None,
                "plotly_figure": None,
                "error": f"Plotly generation error: {str(e)}"
            }

    def _create_prompt(self, chart_config: ChartConfig, data: list, output_type: OutputType) -> str:
        """Create prompt for LLM"""

        # Sample data (first 5 rows)
        sample_data = data[:5] if len(data) > 5 else data

        prompt_parts = [
            f"Chart Tipi: {output_type}",
            f"",
            f"Veri (ilk {len(sample_data)} satır):",
            f"```json",
            json.dumps(sample_data, ensure_ascii=False, indent=2),
            f"```",
            f"",
            f"Toplam satır: {len(data)}",
        ]

        # Add chart config details
        if chart_config.get("x_axis"):
            x_axis = chart_config["x_axis"]
            prompt_parts.append(f"X Ekseni: {x_axis.get('field')} ({x_axis.get('label')})")

        if chart_config.get("y_axis"):
            y_axis = chart_config["y_axis"]
            prompt_parts.append(f"Y Ekseni: {y_axis.get('field')} ({y_axis.get('label')})")

        if chart_config.get("label_field"):
            prompt_parts.append(f"Etiket: {chart_config['label_field']}")

        if chart_config.get("value_field"):
            prompt_parts.append(f"Değer: {chart_config['value_field']}")

        if chart_config.get("series_field"):
            prompt_parts.append(f"Series: {chart_config['series_field']}")

        options = chart_config.get("options", {})
        if options.get("title"):
            prompt_parts.append(f"Başlık: {options['title']}")

        prompt_parts.extend([
            f"",
            f"Bu veriye göre {output_type} tipinde bir Plotly chart oluştur.",
            f"Sadece Python kodu döndür, açıklama yazma!"
        ])

        return "\n".join(prompt_parts)

    def _clean_code(self, code: str) -> str:
        """Clean generated code"""

        # Remove markdown code blocks
        if code.startswith("```"):
            lines = code.split("\n")
            # Remove first line (```python or ```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove last line (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        return code.strip()

    def _execute_code(self, code: str, data: list) -> Dict[str, Any]:
        """
        Execute generated code and return Plotly figure as JSON.

        Returns:
            Plotly figure as JSON dict, or None if execution fails
        """

        try:
            logger.info("🔧 Importing plotly modules...")
            # Import plotly modules for exec environment
            import plotly.graph_objects as go
            import plotly.express as px
            import pandas as pd

            logger.info("✅ Plotly modules imported successfully")

            # Prepare execution environment with plotly modules pre-loaded
            exec_globals = {
                "__builtins__": __builtins__,
                "data": data,  # Make data available to code
                "go": go,      # plotly.graph_objects
                "px": px,      # plotly.express
                "pd": pd,      # pandas (for data manipulation)
            }
            exec_locals = {}

            logger.info(f"🔧 Executing code with {len(data)} data rows...")
            logger.info(f"Available in exec: go={go is not None}, px={px is not None}, pd={pd is not None}")

            # Execute code
            exec(code, exec_globals, exec_locals)

            logger.info("✅ Code executed without errors")
            logger.info(f"exec_locals keys: {list(exec_locals.keys())}")
            logger.info(f"exec_globals keys (custom): {[k for k in exec_globals.keys() if not k.startswith('__')]}")

            # Get figure
            fig = exec_locals.get("fig")

            if fig is None:
                # Try to get from globals
                logger.warning("fig not in locals, checking globals...")
                fig = exec_globals.get("fig")

            if fig is None:
                logger.error("❌ Code did not create 'fig' variable")
                logger.error(f"Available variables: locals={list(exec_locals.keys())}, globals={[k for k in exec_globals.keys() if not k.startswith('__')]}")
                return None

            logger.info(f"✅ Figure found! Type: {type(fig)}")

            # Convert to JSON
            try:
                logger.info("🔧 Converting figure to JSON...")
                fig_json = fig.to_json()
                logger.info(f"✅ Figure converted to JSON string: {len(fig_json)} chars")

                fig_dict = json.loads(fig_json)
                logger.info(f"✅ JSON parsed to dict")
                logger.info(f"Figure JSON keys: {list(fig_dict.keys())}")

                return fig_dict
            except Exception as e:
                logger.error(f"❌ Failed to convert figure to JSON: {e}", exc_info=True)
                # Try to return figure as-is
                return {"error": "Could not serialize figure", "type": str(type(fig))}

        except Exception as e:
            logger.error(f"❌❌❌ Code execution error: {str(e)}", exc_info=True)
            return None


def create_plotly_code_generator_node(llm: LLM):
    """Factory function to create plotly code generator node with LLM"""
    def plotly_code_generator_node(state: DataVisualizationState) -> Dict[str, Any]:
        """LangGraph node wrapper"""
        generator = PlotlyCodeGenerator(llm)
        return generator.generate(state)
    return plotly_code_generator_node
