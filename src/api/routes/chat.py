from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
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
        err = str(e)
        if "429" in err or "quota" in err.lower() or "RateLimitError" in type(e).__name__:
            raise HTTPException(status_code=429, detail="LLM API kotası aşıldı. Lütfen API anahtarınızı veya planınızı kontrol edin.")
        raise HTTPException(status_code=500, detail=f"Failed to send message: {err}")


@router.post("/stream")
async def stream_message(
    request: ChatMessageRequest,
    chat_service: ChatService = Depends(get_chat_service)
) -> EventSourceResponse:
    """
    Stream progress events and final result for a chat message via SSE.

    Returns text/event-stream with events:
    - event: progress  data: {"step", "message", "index", "total"}
    - event: result    data: {"text", "type", "confidence", "action"}
    - event: error     data: {"message"}
    """
    async def event_generator():
        try:
            async for stream_event in chat_service.stream_message(request):
                yield {
                    "event": stream_event.event_type,
                    "data": stream_event.model_dump_json(
                        exclude={"event_type"},
                        exclude_none=True,
                    ),
                }
        except ValueError as e:
            yield {
                "event": "error",
                "data": f'{{"message": "{str(e)}"}}',
            }
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                yield {
                    "event": "error",
                    "data": '{"message": "LLM API kotası aşıldı."}',
                }
            else:
                yield {
                    "event": "error",
                    "data": f'{{"message": "Bir hata oluştu: {err[:100]}"}}',
                }

    return EventSourceResponse(event_generator())


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
