"""
Pure Python T-SQL Generator
============================
QuerySchema + business_rules + today → T-SQL string.
LLM kullanmaz. Deterministik ve test edilebilir.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

# SQL function expression'larını tespit et — string'e quote edilmemeli
_SQL_FUNC_RE = re.compile(
    r"^\s*(DATEADD|CAST|GETDATE|GETUTCDATE|SYSDATETIME|YEAR|MONTH|DAY|DATEPART|DATEDIFF)\s*\(",
    re.IGNORECASE,
)
# Zaten tam aggregation expression'ı tespit et (SUM(...) gibi)
_AGG_EXPR_RE = re.compile(r"^\s*(SUM|COUNT|AVG|MAX|MIN)\s*\(", re.IGNORECASE)

# date_descriptor SADECE bu kolonlara uygulanır; diğer kolonlardaki date_descriptor drop edilir
_DATE_COLUMNS: frozenset[str] = frozenset({"DocumentDate", "Date"})

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _col_expr(col: str) -> str:
    """Basit kolon adını [köşeli parantez] içine al; SQL expression ise olduğu gibi bırak."""
    if any(c in col for c in ("(", ")", " ", ".")):
        return col  # YEAR(DocumentDate), CAST(...) gibi — dokunma
    return f"[{col}]"


def _resolve_date_filter(col_expr: str, descriptor: Dict[str, Any], operator: str, today: date) -> str:
    """DateDescriptor dict'ini SQL koşuluna çevir."""
    d_type = descriptor.get("type")

    if d_type == "exact":
        val = descriptor.get("value", "")
        # DocumentDate datetime kolonu — CAST ile gün seviyesinde karşılaştır
        return f"CAST({col_expr} AS DATE) {operator} '{val}'"

    elif d_type == "relative":
        unit_map = {"day": "DAY", "month": "MONTH", "year": "YEAR", "quarter": "QUARTER"}
        sql_unit = unit_map.get(descriptor.get("unit", "day"), "DAY")
        amount = descriptor.get("amount", -1)
        date_expr = f"DATEADD({sql_unit}, {amount}, '{today}')"
        # relative için "=" anlamsız — ">=" kullan
        effective_op = operator if operator not in ("=",) else ">="
        return f"{col_expr} {effective_op} {date_expr}"

    elif d_type == "current_period":
        period = descriptor.get("period", "day")
        if period == "day":
            return f"CAST({col_expr} AS DATE) = '{today}'"
        elif period == "month":
            return f"YEAR({col_expr}) = {today.year} AND MONTH({col_expr}) = {today.month}"
        elif period == "year":
            return f"YEAR({col_expr}) = {today.year}"
        elif period == "quarter":
            q = (today.month - 1) // 3 + 1
            return f"YEAR({col_expr}) = {today.year} AND DATEPART(QUARTER, {col_expr}) = {q}"

    return ""


def _resolve_filter(f: Dict[str, Any], today: date) -> Optional[str]:
    """Tek SchemaFilter dict'ini SQL koşul string'ine çevir. None = atla."""
    col_name = f["column"]
    col = _col_expr(col_name)
    op = f.get("operator", "=")

    # IS NULL / IS NOT NULL — değer gerektirmez
    if op in ("IS NULL", "IS NOT NULL"):
        return f"{col} {op}"

    # IN / NOT IN — values list (preferred) veya pre-formatted value string
    if op in ("IN", "NOT IN"):
        values_list = f.get("values", [])
        if values_list:
            escaped = [str(v).replace("'", "''") for v in values_list]
            formatted = ", ".join(f"'{v}'" for v in escaped)
            return f"{col} {op} ({formatted})"
        val = f.get("resolved_value") or f.get("value")
        if val:
            return f"{col} {op} {val}"
        return None

    # Tarih filtresi — SADECE gerçek tarih kolonlarına uygula
    # Örn: IsTableActive boolean bir kolon, date_descriptor almamalı
    date_desc = f.get("date_descriptor")
    if date_desc:
        if col_name not in _DATE_COLUMNS:
            logger.warning(
                "[SQL_BUILDER] date_descriptor on non-date column '%s' dropped — "
                "LLM hallucination guard; use value= instead",
                col_name,
            )
            return None
        result = _resolve_date_filter(col, date_desc, op, today)
        if result:
            return result

    # Normal değer filtresi
    value = f.get("resolved_value") or f.get("value")

    if not value:
        # value_hint varsa LIKE fallback
        hint = f.get("value_hint", "")
        if hint:
            clean = hint.replace("'", "''")
            return f"UPPER({col}) LIKE UPPER('%{clean}%')"
        return None  # Atla

    value_clean = value.replace("'", "''")

    if op == "LIKE":
        return f"UPPER({col}) LIKE UPPER('%{value_clean}%')"
    elif op == "BETWEEN":
        # value "val1 AND val2" formatında olmalı
        return f"{col} BETWEEN {value}"
    else:
        # SQL function expression mı? (DATEADD, CAST, vb.) — quote etme
        if _SQL_FUNC_RE.match(value):
            return f"{col} {op} {value}"
        # Sayısal mı?
        try:
            float(value_clean.replace(",", "."))
            return f"{col} {op} {value_clean}"
        except ValueError:
            return f"{col} {op} '{value_clean}'"


def _build_select_parts(schema_dict: Dict[str, Any], applied_rules: List[Dict[str, Any]]) -> List[str]:
    """SELECT cümlesi için parça listesi oluştur."""
    aggregations = schema_dict.get("aggregations", [])
    select_columns = schema_dict.get("select_columns", [])
    group_by = schema_dict.get("group_by", [])

    if aggregations:
        parts: List[str] = []

        # GROUP BY kolonlarını önce ekle (display için)
        for col in group_by:
            parts.append(_col_expr(col))

        # Aggregation ifadelerini ekle
        agg_rule_modifier = next(
            (r["sql"].get("aggregation", "") for r in applied_rules if r.get("sql", {}).get("aggregation")),
            None,
        )

        for agg in aggregations:
            func = agg["function"]
            col_expr = _col_expr(agg["column"])
            alias = agg["alias"]

            if agg_rule_modifier and func == "SUM":
                # Business rule aggregation içeriğini kullan
                inner = agg_rule_modifier.replace("{col}", agg["column"]).replace("{column}", agg["column"])
                # Rule modifier zaten tam aggregation expression'ı ise (SUM/COUNT/AVG...) — double-wrap etme
                if _AGG_EXPR_RE.match(inner):
                    parts.append(f"{inner} AS [{alias}]")
                else:
                    parts.append(f"{func}({inner}) AS [{alias}]")
            else:
                parts.append(f"{func}({col_expr}) AS [{alias}]")

        return parts

    elif select_columns:
        return [_col_expr(col) for col in select_columns]
    else:
        return ["*"]


def _build_where(
    filters: List[Dict[str, Any]],
    applied_rules: List[Dict[str, Any]],
    today: date,
) -> str:
    """WHERE cümlesi oluştur. Boş string döner = WHERE yok."""
    conditions: List[tuple[str, str]] = []  # (logical_op, condition)
    seen_conditions: set = set()            # exact duplicate önleme

    for f in filters:
        condition = _resolve_filter(f, today)
        if condition and condition not in seen_conditions:
            conditions.append((f.get("logical_operator", "AND"), condition))
            seen_conditions.add(condition)

    # Business rule WHERE bileşenleri
    for rule in applied_rules:
        sql_filter = rule.get("sql", {}).get("filter", "")
        if sql_filter and sql_filter not in seen_conditions:
            conditions.append(("AND", sql_filter))
            seen_conditions.add(sql_filter)

    if not conditions:
        return ""

    parts = [conditions[0][1]]
    for logical_op, condition in conditions[1:]:
        parts.append(f"{logical_op} {condition}")

    return "WHERE " + "\n    ".join(parts)


def _build_group_by(schema_dict: Dict[str, Any], applied_rules: List[Dict[str, Any]]) -> str:
    """GROUP BY cümlesi oluştur."""
    group_by = schema_dict.get("group_by", [])
    if not group_by:
        return ""

    cols = [_col_expr(col) for col in group_by]

    # Business rule group_by eklemesi
    for rule in applied_rules:
        extra = rule.get("sql", {}).get("group_by", "")
        if extra:
            cols.append(extra)

    return "GROUP BY " + ", ".join(cols)


def _build_order_by(schema_dict: Dict[str, Any]) -> str:
    """ORDER BY cümlesi oluştur."""
    order_col = schema_dict.get("order_by_column")
    direction = schema_dict.get("order_by_direction", "DESC")

    if order_col:
        return f"ORDER BY {_col_expr(order_col)} {direction}"

    # Periyodik gruplama varsa otomatik ORDER BY
    group_by = schema_dict.get("group_by", [])
    time_indicators = ("YEAR(", "MONTH(", "CAST(", "DATEPART(")
    time_cols = [col for col in group_by if any(col.upper().startswith(t) for t in time_indicators)]
    if time_cols:
        return "ORDER BY " + ", ".join(time_cols) + " ASC"

    # RANKING: aggregation + limit varsa birinci aggregation'a göre sırala
    aggregations = schema_dict.get("aggregations", [])
    if aggregations and schema_dict.get("limit"):
        alias = aggregations[0].get("alias", "")
        if alias:
            return f"ORDER BY [{alias}] {direction}"

    return ""


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_sql(
    schema_dict: Dict[str, Any],
    table_name: str,
    auto_rules: List[Dict[str, Any]],
    today: date,
) -> str:
    """
    QuerySchema dict + auto_rules + bugünün tarihi → T-SQL string.

    Args:
        schema_dict: QuerySchema.model_dump() çıktısı
        table_name:  Hedef tablo adı (runtime config'ten gelir)
        auto_rules:  business_rules_node'dan gelen resolved rule listesi (direkt uygulanır)
        today:       Bugünün tarihi (tarih çözme için)

    Returns:
        Executable T-SQL string
    """
    # auto_rules direkt applied_rules olarak kullan (ID lookup yok)
    applied_rules = auto_rules

    if applied_rules:
        logger.info(f"[SQL_GENERATOR] Applying {len(applied_rules)} auto rules: {[r.get('id') for r in applied_rules]}")

    # TOP N
    limit = schema_dict.get("limit")
    top_clause = f"TOP {limit} " if limit else ""

    # SELECT
    select_parts = _build_select_parts(schema_dict, applied_rules)
    select_clause = ",\n       ".join(select_parts)

    # FROM
    from_clause = f"[{table_name}]"

    # WHERE
    where_clause = _build_where(schema_dict.get("filters", []), applied_rules, today)

    # GROUP BY
    group_by_clause = _build_group_by(schema_dict, applied_rules)

    # ORDER BY
    order_by_clause = _build_order_by(schema_dict)

    # Birleştir
    lines = [f"SELECT {top_clause}{select_clause}", f"FROM {from_clause}"]
    if where_clause:
        lines.append(where_clause)
    if group_by_clause:
        lines.append(group_by_clause)
    if order_by_clause:
        lines.append(order_by_clause)

    sql = "\n".join(lines)
    logger.info(f"[SQL_GENERATOR] Generated ({len(sql)} chars): {sql[:200]}")
    return sql
