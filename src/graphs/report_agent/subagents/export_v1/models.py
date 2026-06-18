from pydantic import BaseModel
from typing import Optional


class ExportSpec(BaseModel):
    format: str
    include_chart: bool = False
    include_insight: bool = False
    title: str
    sheet_name: str = "Veri"
