from src.core.exceptions.exceptions import AppBaseException


class NLUError(AppBaseException):
    pass


class SemanticExtractionError(NLUError):
    pass


class TermResolutionError(NLUError):
    pass


class SchemaBuilderError(NLUError):
    pass


class ValueGroundingError(NLUError):
    pass


class SQLGenerationError(NLUError):
    pass
