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

    query: str = Field(
        default="",
        description="Tabloyu oluşturan SQL scripti (GO ile ayrılmış batch'ler desteklenir)",
    )

    column_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Kolon metaverileri — {kolon_adı: açıklama} formatında",
    )

    business_rules_path: str = Field(
        default="./src/graphs/generic_text2sql/business_rules.json",
        description="Business rules JSON dosya yolu. LangGraph Studio'dan runtime'da override edilebilir.",
    )
