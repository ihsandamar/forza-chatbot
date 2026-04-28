import pytest


def test_nlu_error_is_app_base_exception():
    from src.core.exceptions.exceptions import AppBaseException
    from src.graphs.report_agent.subagents.text2sql.exceptions import NLUError
    err = NLUError("test", error_code="NLU_ERROR")
    assert isinstance(err, AppBaseException)
    assert err.error_code == "NLU_ERROR"


def test_subclasses_are_nlu_error():
    from src.graphs.report_agent.subagents.text2sql.exceptions import (
        SemanticExtractionError, TermResolutionError,
        SchemaBuilderError, ValueGroundingError, SQLGenerationError, NLUError,
    )
    for cls in [SemanticExtractionError, TermResolutionError, SchemaBuilderError,
                ValueGroundingError, SQLGenerationError]:
        err = cls("test")
        assert isinstance(err, NLUError), f"{cls.__name__} must be NLUError subclass"
