from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from src.api.models.base import ErrorResponse


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handle validation errors
    """
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error="Validation Error",
            details=str(exc.errors())
        ).model_dump()
    )


async def general_exception_handler(request: Request, exc: Exception):
    """
    Handle general exceptions
    """
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal Server Error",
            details=str(exc)
        ).model_dump()
    )
