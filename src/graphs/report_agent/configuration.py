from typing import Any, Dict

from pydantic import BaseModel, Field


class ReportAgentConfiguration(BaseModel):
    """
    LangGraph Studio'dan runtime'da configure edilebilen alanlar.

    StateGraph(config_schema=ReportAgentConfiguration) ile kayıt edilir;
    Studio UI'da "Configurable" panelinde görünür.
    """

    table_name: str = Field(
        default="MasterReportDocumentTable",
        description="Sorgunun uygulanacağı tablo adı",
    )

    column_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Kolon metaverileri — {kolon_adı: açıklama} formatında",
    )
