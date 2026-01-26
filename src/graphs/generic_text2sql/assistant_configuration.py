from typing import Optional, List, Dict, Any
from pydantic import Field
from src.models.base_assistant_configuration import BaseAssistantConfiguration


class GenericSQLAssistantConfiguration(BaseAssistantConfiguration):
    """Configuration for a generic text-to-SQL assistant."""

    report_name: str = Field(
        default="",
        description="Rapor adı"
    )

    description: str = Field(
        default="",
        description="Rapor açıklaması"
    )

    table_name: str = Field(
        default="MasterReportDocumentTable",
        description="Sorgunun uygulanacağı tablo adı"
    )

    query: str = Field(
        default="",
        description="Tablo oluşturma SQL sorgusu (runtime'da çalıştırılacak)"
    )

    column_metadata: Dict[str, str] = Field(
        default_factory=dict,
        description="Sütun metaverileri - column_name -> description mapping"
    )

    business_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="İş kuralları JSON formatında (id, description, modules, related_tables, sql, is_default)"
    )
