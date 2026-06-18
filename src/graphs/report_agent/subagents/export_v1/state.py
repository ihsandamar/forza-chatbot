from typing import Any, Dict, List, Optional, TypedDict


class ExportState(TypedDict, total=False):
    # ReportState overlap (auto-sync)
    results: Optional[List[Dict[str, Any]]]
    active_results: Optional[List[Dict[str, Any]]]
    wants_export: Optional[bool]
    export_format: Optional[str]
    export_output: Optional[Dict[str, Any]]
    visualization_output: Optional[Dict[str, Any]]
    insight_output: Optional[str]
    session_id: Optional[str]
    error: Optional[str]
    user_query: str

    # Internal
    export_spec: Optional[Dict[str, Any]]
