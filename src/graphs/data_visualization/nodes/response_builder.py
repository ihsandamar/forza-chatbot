# data_visualization/nodes/response_builder.py

from typing import Dict, Any, List
from datetime import datetime

from ..state import (
    DataVisualizationState,
    VisualizationOutput,
    OutputType
)


class ResponseBuilder:
    """
    Builds final visualization response.
    No LLM - pure data transformation.
    """
    
    def build(self, state: DataVisualizationState) -> DataVisualizationState:
        """Build final response"""

        viz_decision = state.get("viz_decision")
        chart_config = state.get("chart_config")
        raw_data = state.get("raw_data", [])
        data_profile = state.get("data_profile")
        user_query = state.get("user_query", "")

        if not viz_decision:
            return {
                **state,
                "error": "No visualization decision made"
            }

        output_type = viz_decision["output_type"]
        needs_graph = viz_decision["needs_graph"]

        # Get Plotly output if available
        plotly_code = state.get("plotly_code")
        plotly_figure = state.get("plotly_figure")

        # Prepare data based on output type
        prepared_data = self._prepare_data(raw_data, output_type, chart_config)

        # Generate summary with markdown formatting for lists
        summary = self._generate_summary(
            output_type,
            prepared_data,
            data_profile,
            user_query,
            needs_graph,
            chart_config
        )

        # Build final output
        visualization_output = VisualizationOutput(
            output_type=output_type,
            needs_graph=needs_graph,
            chart_config=chart_config,
            data=prepared_data,
            summary=summary
        )

        # Add Plotly outputs to state
        return {
            **state,
            "visualization_output": visualization_output,
            "plotly_code": plotly_code,
            "plotly_figure": plotly_figure
        }
    
    def _prepare_data(
        self, 
        raw_data: List[Dict[str, Any]], 
        output_type: OutputType,
        chart_config: Dict
    ) -> List[Dict[str, Any]]:
        """Prepare data based on output type"""
        
        if not raw_data:
            return []
        
        # Get limit from config
        limit = None
        if chart_config and "options" in chart_config:
            limit = chart_config["options"].get("limit_rows")
        
        # Apply limit
        if limit and len(raw_data) > limit:
            return raw_data[:limit]
        
        return raw_data
    
    def _generate_summary(
        self,
        output_type: OutputType,
        data: List[Dict[str, Any]],
        profile: Dict,
        user_query: str = "",
        needs_graph: bool = False,
        chart_config: Dict = None
    ) -> str:
        """Generate summary with smart formatting based on query type"""

        if not data:
            return "Sonuç bulunamadı."

        row_count = len(data)

        if output_type == OutputType.SINGLE_VALUE:
            # Single value - show the value
            first_row = data[0]
            value = list(first_row.values())[0]
            return f"{value}"

        elif output_type == OutputType.SIMPLE_LIST:
            # For simple list queries, return data as markdown list
            return self._format_as_markdown_list(data, user_query)

        elif output_type == OutputType.TABLE:
            col_count = len(data[0]) if data else 0
            return f"{row_count} satır, {col_count} kolon içeren tablo"

        elif output_type in [OutputType.BAR_CHART, OutputType.LINE_CHART, OutputType.PIE_CHART]:
            # For graphs, add brief explanation about the data
            return self._generate_graph_explanation(output_type, data, chart_config)

        elif output_type == OutputType.COMPARISON:
            return self._generate_comparison_explanation(data)

        return f"{row_count} kayıt"

    def _format_as_markdown_list(self, data: List[Dict[str, Any]], query: str = "") -> str:
        """Format data as markdown list for simple queries"""
        if not data:
            return "Sonuç bulunamadı."

        # Check if it's a simple list (1-2 columns)
        first_row = data[0]
        columns = list(first_row.keys())

        if len(columns) == 1:
            # Single column - simple bullet list
            items = [str(list(row.values())[0]) for row in data[:20]]  # Limit to 20
            result = "\n".join([f"- {item}" for item in items])
            if len(data) > 20:
                result += f"\n\n*({len(data)} kayıttan ilk 20'si gösteriliyor)*"
            return result

        elif len(columns) == 2:
            # Two columns - formatted list with key: value
            result_lines = []
            for row in data[:20]:  # Limit to 20
                key = str(list(row.values())[0])
                value = str(list(row.values())[1])
                result_lines.append(f"- **{key}**: {value}")

            result = "\n".join(result_lines)
            if len(data) > 20:
                result += f"\n\n*({len(data)} kayıttan ilk 20'si gösteriliyor)*"
            return result

        else:
            # More columns - just return count
            return f"{len(data)} kayıt listelendi."

    def _generate_graph_explanation(
        self,
        output_type: OutputType,
        data: List[Dict[str, Any]],
        chart_config: Dict = None
    ) -> str:
        """Generate brief explanation for graphs"""
        row_count = len(data)

        # Get column info if available
        columns = list(data[0].keys()) if data else []

        chart_type_names = {
            OutputType.BAR_CHART: "Bar grafiği",
            OutputType.LINE_CHART: "Çizgi grafiği",
            OutputType.PIE_CHART: "Pasta grafiği"
        }

        chart_name = chart_type_names.get(output_type, "Grafik")

        # Build explanation
        explanation = f"{chart_name}: {row_count} veri noktası"

        # Add info about what's being visualized
        if chart_config and "x_axis" in chart_config and "y_axis" in chart_config:
            x_axis = chart_config["x_axis"]
            y_axis = chart_config["y_axis"]
            explanation += f" ({x_axis} - {y_axis})"

        return explanation

    def _generate_comparison_explanation(self, data: List[Dict[str, Any]]) -> str:
        """Generate brief explanation for comparisons"""
        if not data:
            return "Karşılaştırma verisi bulunamadı."

        return f"{len(data)} öğe karşılaştırılıyor."


def response_builder_node(state: DataVisualizationState) -> Dict[str, Any]:
    """LangGraph node wrapper"""
    builder = ResponseBuilder()
    return builder.build(state)