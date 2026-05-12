from typing import Optional

NODE_PROGRESS_MESSAGES: dict[str, tuple[str, int]] = {
    # Report Agent level
    "classify_intent":    ("Sorgu analiz ediliyor...",          0),
    "modify_sql":         ("Sorgu güncelleniyor...",            0),
    "report_chat":        ("Sorgu netleştiriliyor...",          0),
    # Text2SQL subgraph
    "create_table":       ("Çalışma tablosu oluşturuluyor...", 1),
    "business_rules":     ("İş kuralları yükleniyor...",        2),
    "semantic_extractor": ("Sorgu anlamı çıkarılıyor...",       3),
    "term_resolver":      ("Terimler çözümleniyor...",          4),
    "term_validator":     ("Terimler doğrulanıyor...",          5),
    "schema_builder":     ("Sorgu şeması oluşturuluyor...",     6),
    "value_resolver":     ("Değerler çözümleniyor...",          7),
    "sql_generator":      ("SQL oluşturuluyor...",              8),
    "sql_executor":       ("Veriler çekiliyor...",              9),
    # Visualization subgraph
    "data_analyzer":      ("Veri analiz ediliyor...",          10),
    "template_renderer":  ("Grafik oluşturuluyor...",          11),
    # Final
    "build_response":     ("Yanıt hazırlanıyor...",            12),
}

TOTAL_STEPS = 13


def normalize_node_name(raw_name: str) -> str:
    """Strip subgraph prefix: 'text2sql:sql_executor' → 'sql_executor'."""
    return raw_name.split(":")[-1] if ":" in raw_name else raw_name


def get_progress_info(
    raw_name: str,
    occurrence_count: int = 1,
) -> Optional[tuple[str, str, int]]:
    """
    Return (node_name, message, index) for the given node, or None if unknown.
    occurrence_count > 1 signals a retry — message changes accordingly.
    """
    node_name = normalize_node_name(raw_name)
    entry = NODE_PROGRESS_MESSAGES.get(node_name)
    if entry is None:
        return None
    message, index = entry
    if occurrence_count > 1:
        message = f"Sorgu yeniden deneniyor... ({occurrence_count}/2)"
    return (node_name, message, index)
