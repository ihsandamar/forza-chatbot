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

        # Generate summary
        summary = self._generate_summary(output_type, prepared_data, data_profile)

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
        profile: Dict
    ) -> str:
        """Generate simple summary text"""
        
        if not data:
            return "Sonuç bulunamadı."
        
        row_count = len(data)
        
        if output_type == OutputType.SINGLE_VALUE:
            # Single value - show the value
            first_row = data[0]
            value = list(first_row.values())[0]
            return f"{value}"
        
        elif output_type == OutputType.SIMPLE_LIST:
            return f"{row_count} kayıt listelendi."
        
        elif output_type == OutputType.TABLE:
            col_count = len(data[0]) if data else 0
            return f"{row_count} satır, {col_count} kolon"
        
        elif output_type in [OutputType.BAR_CHART, OutputType.LINE_CHART, OutputType.PIE_CHART]:
            return f"{row_count} veri noktası görselleştirildi."
        
        elif output_type == OutputType.COMPARISON:
            return "Karşılaştırma görüntüleniyor."
        
        return f"{row_count} kayıt"


def response_builder_node(state: DataVisualizationState) -> Dict[str, Any]:
    """LangGraph node wrapper"""
    builder = ResponseBuilder()
    return builder.build(state)