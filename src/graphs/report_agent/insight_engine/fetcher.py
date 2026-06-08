"""
ComparisonDataFetcher — Auto-shift or user-provided comparison SQL.

Mode A (default): Parse BETWEEN dates from active_sql, compute delta, shift backward.
Mode B: Use user-provided comparison_sql directly.
"""
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
    """Fetch comparison data using Mode A (auto-shift) or Mode B (user SQL)."""

    def __init__(self, connection_string: str):
        """
        Args:
            connection_string: SQLAlchemy connection string (e.g., mssql+pyodbc://...)
        """
        self._connection_string = connection_string

    @staticmethod
    def _shift_sql_dates(sql: str) -> Optional[str]:
        """
        Mode A: Parse BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' from SQL.
        Compute delta = (end - start) + 1 day.
        Shift: new_end = start - 1 day, new_start = new_end - delta + 1 day.
        Replace in SQL and return shifted SQL, or None if no date found.
        """
        match = _DATE_BETWEEN_RE.search(sql)
        if not match:
            return None

        start_str, end_str = match.group(1), match.group(2)
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)

        # Delta = inclusive range
        delta = (end - start) + timedelta(days=1)

        # Shift backward: new_end = start - 1, new_start = new_end - delta + 1
        new_end = start - timedelta(days=1)
        new_start = new_end - delta + timedelta(days=1)

        shifted = sql.replace(
            match.group(0),
            f"BETWEEN '{new_start.isoformat()}' AND '{new_end.isoformat()}'",
        )

        logger.debug(
            f"[FETCHER] Mode A: {start_str}–{end_str} → {new_start}–{new_end}"
        )
        return shifted

    def _resolve_comparison_sql(self, state: Dict[str, Any]) -> Optional[str]:
        """
        Mode B: Return comparison_sql if present.
        Mode A: Shift active_sql dates and return shifted SQL.
        Returns None if neither mode succeeds.
        """
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
        """
        Fetch comparison data using Mode B (if available) or Mode A (auto-shift).
        Returns empty DataFrame if no comparison SQL is resolved or fetch fails.
        """
        from src.graphs.report_agent.subagents.text2sql.nodes import _execute_sql_async

        comparison_sql = self._resolve_comparison_sql(state)
        if not comparison_sql:
            logger.info(
                "[FETCHER] No comparison SQL resolved — skipping comparison fetch"
            )
            return pd.DataFrame()

        try:
            rows: List[Dict[str, Any]] = await _execute_sql_async(
                self._connection_string, comparison_sql
            )
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Exception as exc:
            logger.warning(f"[FETCHER] Comparison fetch failed: {exc}")
            return pd.DataFrame()
