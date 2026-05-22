from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.schemas.vectorstore import (
    IngestTranscriptRequest,
    IngestVideoResponse,
    VectorSearchResponse,
)
from app.services.chunking_service import ChunkingOptions, ChunkingService, get_chunking_service
from app.services.transcript_service import (
    TranscriptFetchOptions,
    TranscriptService,
    get_transcript_service,
)
from app.services.vectorstore_service import (
    ChromaVectorStoreService,
    get_vectorstore_service,
)

router = APIRouter()


@router.post("/vectorstore/transcripts", response_model=IngestVideoResponse)
async def ingest_transcript_chunks(
    request: IngestTranscriptRequest,
    chunking_service: ChunkingService = Depends(get_chunking_service),
    vectorstore_service: ChromaVectorStoreService = Depends(get_vectorstore_service),
) -> IngestVideoResponse:
    chunks, embedding_model = await chunking_service.chunk_transcript(
        transcript=request.transcript,
        options=ChunkingOptions(
            max_chunk_chars=request.max_chunk_chars or settings.chunk_max_chars,
            overlap_segments=(
                request.overlap_segments
                if request.overlap_segments is not None
                else settings.chunk_overlap_segments
            ),
            include_embeddings=True,
        ),
    )
    stored_chunk_ids = await vectorstore_service.upsert_chunks(chunks)

    return IngestVideoResponse(
        video_id=request.transcript.video_id,
        collection_name=settings.chroma_collection_name,
        chunk_count=len(stored_chunk_ids),
        embedding_model=embedding_model or settings.embedding_model,
        stored_chunk_ids=stored_chunk_ids,
    )


@router.post("/videos/{video_id}/ingest", response_model=IngestVideoResponse)
async def ingest_video_transcript(
    video_id: Annotated[
        str,
        Path(
            min_length=6,
            max_length=32,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="YouTube video id.",
        ),
    ],
    language: Annotated[str, Query(min_length=2, max_length=10)] = "en",
    max_chunk_chars: int = Query(default=1200, ge=300, le=4000),
    overlap_segments: int = Query(default=1, ge=0, le=5),
    transcript_service: TranscriptService = Depends(get_transcript_service),
    chunking_service: ChunkingService = Depends(get_chunking_service),
    vectorstore_service: ChromaVectorStoreService = Depends(get_vectorstore_service),
) -> IngestVideoResponse:
    transcript = await transcript_service.get_transcript(
        video_id=video_id,
        options=TranscriptFetchOptions(language=language, use_whisper_fallback=True),
    )
    chunks, embedding_model = await chunking_service.chunk_transcript(
        transcript=transcript,
        options=ChunkingOptions(
            max_chunk_chars=max_chunk_chars,
            overlap_segments=overlap_segments,
            include_embeddings=True,
        ),
    )
    stored_chunk_ids = await vectorstore_service.upsert_chunks(chunks)

    return IngestVideoResponse(
        video_id=video_id,
        collection_name=settings.chroma_collection_name,
        chunk_count=len(stored_chunk_ids),
        embedding_model=embedding_model or settings.embedding_model,
        stored_chunk_ids=stored_chunk_ids,
    )


@router.websocket("/videos/{video_id}/ingest/stream")
async def ingest_video_stream(
    websocket: WebSocket,
    video_id: Annotated[
        str,
        Path(
            min_length=6,
            max_length=32,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="YouTube video ID.",
        ),
    ],
    transcript_service: TranscriptService = Depends(get_transcript_service),
    chunking_service: ChunkingService = Depends(get_chunking_service),
    vectorstore_service: ChromaVectorStoreService = Depends(get_vectorstore_service),
) -> None:
    """WebSocket endpoint that streams real ingestion progress events.

    Event schema: {"type": str, "step": str, "label": str, "progress": int, ...extra}
    Types: "step" | "ready" | "error"
    """
    await websocket.accept()

    async def send(payload: dict) -> None:
        with suppress(Exception):
            await websocket.send_json(payload)

    try:
        await send({"type": "step", "step": "transcript", "label": "Extracting transcript", "progress": 12})
        transcript = await transcript_service.get_transcript(
            video_id=video_id,
            options=TranscriptFetchOptions(language="en", use_whisper_fallback=True),
        )

        await send({"type": "step", "step": "cleaning", "label": "Cleaning timestamp segments", "progress": 30})

        await send({"type": "step", "step": "chunking", "label": "Creating semantic chunks", "progress": 45})
        chunks, _ = await chunking_service.chunk_transcript(
            transcript=transcript,
            options=ChunkingOptions(
                max_chunk_chars=settings.chunk_max_chars,
                overlap_segments=settings.chunk_overlap_segments,
                include_embeddings=False,
            ),
        )

        await send({"type": "step", "step": "embeddings", "label": "Generating embeddings", "progress": 62})
        stored_ids = await vectorstore_service.upsert_chunks(chunks)

        await send({"type": "step", "step": "storing", "label": "Indexing vector store", "progress": 85})

        await send({"type": "step", "step": "memory", "label": "Initializing AI memory", "progress": 93})

        await send({
            "type": "ready",
            "step": "ready",
            "label": "Ready",
            "progress": 100,
            "chunk_count": len(stored_ids),
            "embedding_model": settings.embedding_model,
        })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await send({"type": "error", "step": "error", "label": "Processing failed", "error": str(exc), "progress": 0})
    finally:
        with suppress(Exception):
            await websocket.close()


@router.get("/vectorstore/search", response_model=VectorSearchResponse)
async def search_vectorstore(
    q: Annotated[str, Query(min_length=2, max_length=500)],
    video_id: str | None = Query(default=None, min_length=6, max_length=32),
    limit: int = Query(default=5, ge=1, le=20),
    vectorstore_service: ChromaVectorStoreService = Depends(get_vectorstore_service),
) -> VectorSearchResponse:
    results = await vectorstore_service.similarity_search(
        query=q,
        limit=limit,
        video_id=video_id,
    )

    return VectorSearchResponse(
        query=q,
        video_id=video_id,
        collection_name=settings.chroma_collection_name,
        result_count=len(results),
        results=results,
    )
