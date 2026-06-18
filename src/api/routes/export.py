from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.api.services import export_store

router = APIRouter()


@router.get("/export/{session_id}")
async def download_export(session_id: str) -> StreamingResponse:
    entry = export_store.get(session_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Export bulunamadı. Dosya oluşturulmamış veya oturum sona ermiş olabilir.",
        )
    buffer, filename, content_type = entry
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
