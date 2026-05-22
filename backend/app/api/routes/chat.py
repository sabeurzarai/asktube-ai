from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.rag import RAGChatRequest, RAGChatResponse, RAGStreamEvent, RAGStreamRequest
from app.services.rag_service import RAGService, get_rag_service

router = APIRouter()


@router.post("/chat", response_model=RAGChatResponse)
async def chat_with_video(
    request: RAGChatRequest,
    service: RAGService = Depends(get_rag_service),
) -> RAGChatResponse:
    return await service.answer(
        message=request.message,
        video_id=request.video_id,
        session_id=request.session_id,
        top_k=request.top_k,
    )


@router.websocket("/chat/stream")
async def stream_chat_with_video(websocket: WebSocket) -> None:
    await websocket.accept()
    service = get_rag_service()
    await websocket.send_json(RAGStreamEvent(type="ready").model_dump(mode="json"))

    try:
        while True:
            payload = await websocket.receive_json()

            try:
                request = RAGStreamRequest.model_validate(payload)
            except ValidationError as exc:
                await websocket.send_json(
                    RAGStreamEvent(type="error", error=exc.errors()[0]["msg"]).model_dump(
                        mode="json"
                    )
                )
                continue

            try:
                async for event in service.stream_answer(
                    message=request.message,
                    video_id=request.video_id,
                    session_id=request.session_id,
                    top_k=request.top_k,
                ):
                    await websocket.send_json(event.model_dump(mode="json"))
            except Exception as exc:
                await websocket.send_json(
                    RAGStreamEvent(type="error", error=str(exc)).model_dump(mode="json")
                )
    except WebSocketDisconnect:
        return
