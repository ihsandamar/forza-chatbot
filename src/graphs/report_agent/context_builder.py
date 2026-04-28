from __future__ import annotations


def build_query_context_summary(
    active_results: list[dict] | None,
    active_filters: list[dict] | None,
    max_rows: int = 10,
    max_values_per_col: int = 5,
) -> str:
    """active_results + active_filters → LLM-readable context string."""
    parts: list[str] = []

    if active_filters:
        filter_strs = [
            f"{f['field']} = '{f['value']}'"
            for f in active_filters
            if f.get("field") and f.get("value")
        ]
        if filter_strs:
            parts.append(f"Aktif filtreler: {', '.join(filter_strs)}")

    if active_results:
        col_values: dict[str, list] = {}
        for row in active_results[:max_rows]:
            for col, val in row.items():
                if isinstance(val, str) and val:
                    col_values.setdefault(col, [])
                    if val not in col_values[col]:
                        col_values[col].append(val)

        entity_lines = [
            f"  - {col}: {vals[:max_values_per_col]}"
            for col, vals in col_values.items()
        ]
        if entity_lines:
            parts.append("Önceki sonuçlardaki değerler:\n" + "\n".join(entity_lines))

    return "\n".join(parts) if parts else "Önceki bağlam yok."
