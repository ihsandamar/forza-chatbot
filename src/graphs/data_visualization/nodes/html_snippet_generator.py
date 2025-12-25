# data_visualization/nodes/html_snippet_generator.py

import logging
from typing import Dict, Any

from ..state import DataVisualizationState

logger = logging.getLogger(__name__)


class HTMLSnippetGenerator:
    """
    Generates embeddable HTML snippet from Plotly figure.
    No LLM - pure conversion using Plotly's to_html method.
    """

    def generate(self, state: DataVisualizationState) -> DataVisualizationState:
        """
        Generate HTML snippet from Plotly figure.

        Returns HTML snippet suitable for embedding in web pages.
        """

        plotly_figure = state.get("plotly_figure")

        if not plotly_figure:
            logger.info("No Plotly figure found, skipping HTML snippet generation")
            return {
                **state,
                "plotly_html_snippet": None
            }

        logger.info("🔧 Generating HTML snippet from Plotly figure...")

        try:
            import plotly.graph_objects as go

            # Recreate figure from JSON
            fig = go.Figure(plotly_figure)

            # Generate HTML snippet (not full HTML)
            html_snippet = fig.to_html(
                full_html=False,           # Only div + script, no <html><head><body>
                include_plotlyjs='cdn',    # Use CDN for plotly.js
                div_id='plotly-chart',     # Custom div ID
                config={
                    'responsive': True,
                    'displayModeBar': True,
                    'displaylogo': False,
                }
            )

            logger.info(f"✅ HTML snippet generated: {len(html_snippet)} chars")
            logger.info(f"Snippet preview (first 200 chars):\n{html_snippet[:200]}")

            return {
                **state,
                "plotly_html_snippet": html_snippet
            }

        except Exception as e:
            logger.error(f"❌ HTML snippet generation error: {str(e)}", exc_info=True)
            return {
                **state,
                "plotly_html_snippet": None,
                "error": f"HTML snippet generation error: {str(e)}"
            }


def html_snippet_generator_node(state: DataVisualizationState) -> Dict[str, Any]:
    """LangGraph node wrapper"""
    generator = HTMLSnippetGenerator()
    return generator.generate(state)
