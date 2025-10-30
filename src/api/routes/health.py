from fastapi import APIRouter
from src.api.models.base import BaseResponse

router = APIRouter()


@router.get("/", response_model=BaseResponse)
async def health_check():
    """
    Health check endpoint

    Returns:
    - Status of the API service
    """
    return BaseResponse(success=True, message="API is running")
