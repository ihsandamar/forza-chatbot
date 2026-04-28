def test_semantic_extractor_prompt_importable():
    from src.graphs.report_agent.subagents.text2sql.prompts import SEMANTIC_EXTRACTOR_PROMPT
    assert "{user_query}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{query_type}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{column_names}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{conversation_context}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "{sql_error}" in SEMANTIC_EXTRACTOR_PROMPT
    assert "SQL" not in SEMANTIC_EXTRACTOR_PROMPT.upper() or "YAZMA" in SEMANTIC_EXTRACTOR_PROMPT
