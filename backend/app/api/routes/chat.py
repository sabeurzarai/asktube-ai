import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.analytics.prometheus import WEBSOCKET_CONNECTIONS, WEBSOCKET_FAILURES
from app.analytics.service import get_analytics_service
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
    WEBSOCKET_CONNECTIONS.labels("chat_stream").inc()
    service = get_rag_service()
    await websocket.send_json(RAGStreamEvent(type="ready").model_dump(mode="json"))

    try:
        while True:
            payload = await websocket.receive_json()
            stream_started_at = time.perf_counter()

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
                token_count = 0
                async for event in service.stream_answer(
                    message=request.message,
                    video_id=request.video_id,
                    session_id=request.session_id,
                    top_k=request.top_k,
                ):
                    if event.type == "token":
                        token_count += 1
                    await websocket.send_json(event.model_dump(mode="json"))
                duration_ms = (time.perf_counter() - stream_started_at) * 1000
                get_analytics_service().safe_track_background(
                    get_analytics_service().track_event_safe(
                        "streaming_response_completed",
                        session_id=request.session_id,
                        duration_ms=duration_ms,
                        metadata_json={
                            "video_id": request.video_id,
                            "streamed_tokens": token_count,
                            "tokens_per_second": round(token_count / max(duration_ms / 1000, 0.001), 2),
                        },
                    )
                )
            except Exception as exc:
                WEBSOCKET_FAILURES.labels("chat_stream").inc()
                await websocket.send_json(
                    RAGStreamEvent(type="error", error=str(exc)).model_dump(mode="json")
                )
    except WebSocketDisconnect:
        return
    finally:
        WEBSOCKET_CONNECTIONS.labels("chat_stream").dec()
