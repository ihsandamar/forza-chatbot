from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graphs.report_agent.prompts import FilterDelta, SqlDelta


class SqlDeltaApplicator:
    """LLM SqlDelta'sını active_sql'e deterministik uygular."""

    _DATE_CAST_RE = re.compile(
        r"\[DocumentDate\]\s*(>=?|<=?|=)\s*'([^']+)'",
        re.IGNORECASE,
    )
    _TAIL_RE = re.compile(r"\b(ORDER\s+BY|GROUP\s+BY|HAVING)\b", re.IGNORECASE)
    _WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)

    def apply(self, original_sql: str, delta: "SqlDelta") -> str:
        sql = original_sql
        if delta.remove_filter_columns:
            sql = self._remove_filters(sql, delta.remove_filter_columns)
        if delta.add_filters:
            sql = self._add_filters(sql, delta.add_filters)
        if delta.change_select is not None:
            sql = self._change_select(sql, delta.change_select)
        if delta.change_limit is not None:
            sql = self._change_limit(sql, delta.change_limit)
        if delta.change_groupby is not None:
            sql = self._change_groupby(sql, delta.change_groupby)
        if delta.change_orderby is not None:
            sql = self._change_orderby(sql, delta.change_orderby)
        return self._ensure_date_cast(sql)

    def _add_filters(self, sql: str, filters: list["FilterDelta"]) -> str:
        new_clause = " AND ".join(
            f"[{f.column}] {f.operator} {f.value}" for f in filters
        )
        tail_match = self._TAIL_RE.search(sql)
        insert_pos = tail_match.start() if tail_match else len(sql)

        if self._WHERE_RE.search(sql):
            return sql[:insert_pos].rstrip() + f" AND {new_clause} " + sql[insert_pos:]
        return sql[:insert_pos].rstrip() + f" WHERE {new_clause} " + sql[insert_pos:]

    def _remove_filters(self, sql: str, columns: list[str]) -> str:
        for col in columns:
            esc = re.escape(col)
            cond = (
                r"(?:CAST\s*\(\s*)?"
                rf"\[{esc}\][^)]*\)?"
                r"\s*(?:NOT\s+)?(?:LIKE|=|!=|>=|<=|>|<)\s*"
                r"(?:CAST\s*\([^)]+\)|'[^']*'|[\w.(),-]+)"
            )
            sql = re.sub(r"\s+AND\s+" + cond, "", sql, flags=re.IGNORECASE)
            sql = re.sub(cond + r"\s+AND\s+", "", sql, flags=re.IGNORECASE)
            sql = re.sub(
                r"\bWHERE\s+" + cond + r"(?=\s+(?:ORDER|GROUP|HAVING)|\s*$)",
                "",
                sql,
                flags=re.IGNORECASE,
            )
        return sql.strip()

    def _change_limit(self, sql: str, n: int) -> str:
        return re.sub(r"\bTOP\s+\d+\b", f"TOP {n}", sql, flags=re.IGNORECASE)

    def _change_orderby(self, sql: str, orderby: str) -> str:
        return re.sub(
            r"\bORDER\s+BY\b.*$",
            f"ORDER BY {orderby}",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _change_groupby(self, sql: str, groupby: str) -> str:
        return re.sub(
            r"\bGROUP\s+BY\b.*?(?=\s+(?:ORDER\s+BY|HAVING)|\s*$)",
            f"GROUP BY {groupby} ",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _change_select(self, sql: str, select_list: str) -> str:
        def replacer(m: re.Match) -> str:
            top_clause = m.group(1) or ""
            return f"SELECT{top_clause} {select_list} FROM"

        return re.sub(
            r"\bSELECT\b(\s+TOP\s+\d+)?\s+.+?\s+\bFROM\b",
            replacer,
            sql,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _ensure_date_cast(self, sql: str) -> str:
        return self._DATE_CAST_RE.sub(
            r"CAST([DocumentDate] AS DATE) \1 CAST('\2' AS DATE)",
            sql,
        )
