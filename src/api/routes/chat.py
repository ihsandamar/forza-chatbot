from fastapi import APIRouter, Depends, HTTPException
from src.api.models.requests.chat import SessionStartRequest, ChatMessageRequest
from src.api.models.responses.chat import SessionStartResponse, ChatMessageResponse, SessionHistoryResponse
from src.api.services.chat_service import ChatService
from src.api.dependencies import get_chat_service

router = APIRouter()


@router.post("/session/start", response_model=SessionStartResponse)
async def start_session(
    request: SessionStartRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> SessionStartResponse:
    """
    Start a new chat session

    Parameters:
    - **user_id** (optional): User identifier for tracking sessions

    Returns:
    - **session_id**: Unique identifier for the chat session
    - **user_id**: User identifier if provided
    - **created_at**: Timestamp when session was created
    """
    try:
        return await chat_service.start_session(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start session: {str(e)}")


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> ChatMessageResponse:
    """
    Send a message to the chatbot

    Parameters:
    - **session_id**: Session identifier from /session/start
    - **message**: User message text

    Returns:
    - **success**: Whether the request was successful
    - **timestamp**: Response timestamp
    - **session_id**: Session identifier
    - **response**: Bot response data including text, type, confidence, and action metadata
    """
    try:
        return await chat_service.send_message(request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


@router.get("/session/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    chat_service: ChatService = Depends(get_chat_service)
) -> SessionHistoryResponse:
    """
    Get chat history for a session

    Parameters:
    - **session_id**: Session identifier

    Returns:
    - **success**: Whether the request was successful
    - **session_id**: Session identifier
    - **user_id**: User identifier if provided
    - **created_at**: Session creation timestamp
    - **message_count**: Total number of messages
    - **messages**: List of messages with role and content
    """
    try:
        return await chat_service.get_session_history(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get session history: {str(e)}")
