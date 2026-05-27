import json
import time
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from fastapi import HTTPException, status
from langchain_openai import OpenAIEmbeddings

from app.core.config import Settings, settings
from app.analytics.prometheus import EMBEDDING_DURATION, VECTOR_QUERY_DURATION
from app.analytics.service import get_analytics_service
from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult


class ChromaVectorStoreService:
    def __init__(self, config: Settings) -> None:
        self.config = config

    def get_collection(self) -> Collection:
        try:
            if self.config.chroma_use_http:
                client = chromadb.HttpClient(
                    host=self.config.chroma_host,
                    port=self.config.chroma_port,
                )
            else:
                client = chromadb.PersistentClient(path=self.config.chroma_persist_dir)
            return client.get_or_create_collection(
                name=self.config.chroma_collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to connect to ChromaDB.",
            ) from exc

    async def upsert_chunks(self, chunks: list[TranscriptChunk]) -> list[str]:
        if not chunks:
            return []

        if not self.config.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for vector storage.",
            )

        missing_embeddings = [chunk for chunk in chunks if chunk.embedding is None]
        if missing_embeddings:
            embedding_start = time.perf_counter()
            embeddings = OpenAIEmbeddings(
                model=self.config.embedding_model,
                api_key=self.config.openai_api_key,
            )
            vectors = await embeddings.aembed_documents([chunk.text for chunk in missing_embeddings])
            embedding_ms = (time.perf_counter() - embedding_start) * 1000
            EMBEDDING_DURATION.observe(embedding_ms / 1000)
            get_analytics_service().safe_track_background(
                get_analytics_service().track_event_safe(
                    "embedding_generated",
                    duration_ms=embedding_ms,
                    metadata_json={
                        "chunk_count": len(missing_embeddings),
                        "embedding_model": self.config.embedding_model,
                    },
                )
            )
            for chunk, vector in zip(missing_embeddings, vectors, strict=True):
                chunk.embedding = vector

        collection = self.get_collection()
        ids = [chunk.chunk_id for chunk in chunks]

        try:
            insert_start = time.perf_counter()
            collection.upsert(
                ids=ids,
                documents=[chunk.text for chunk in chunks],
                embeddings=[chunk.embedding for chunk in chunks if chunk.embedding is not None],
                metadatas=[to_chroma_metadata(chunk) for chunk in chunks],
            )
            insert_ms = (time.perf_counter() - insert_start) * 1000
            get_analytics_service().safe_track_background(
                get_analytics_service().track_event_safe(
                    "vector_insert_completed",
                    duration_ms=insert_ms,
                    metadata_json={"chunk_count": len(chunks), "collection": self.config.chroma_collection_name},
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to store transcript chunks in ChromaDB.",
            ) from exc

        return ids

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        if not self.config.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for vector search.",
            )

        embeddings = OpenAIEmbeddings(
            model=self.config.embedding_model,
            api_key=self.config.openai_api_key,
        )
        embedding_start = time.perf_counter()
        query_embedding = await embeddings.aembed_query(query)
        EMBEDDING_DURATION.observe(time.perf_counter() - embedding_start)
        where = {"video_id": video_id} if video_id else None

        try:
            query_start = time.perf_counter()
            result = self.get_collection().query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            query_ms = (time.perf_counter() - query_start) * 1000
            VECTOR_QUERY_DURATION.observe(query_ms / 1000)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to query ChromaDB.",
            ) from exc

        parsed = parse_chroma_query_result(result)
        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "vector_query_completed",
                duration_ms=query_ms,
                metadata_json={
                    "video_id": video_id,
                    "limit": limit,
                    "returned_documents_count": len(parsed),
                },
            )
        )
        return parsed


def to_chroma_metadata(chunk: TranscriptChunk) -> dict[str, str | int | float]:
    return {
        "video_id": chunk.video_id,
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.index,
        "start_seconds": chunk.start_seconds,
        "end_seconds": chunk.end_seconds,
        "segment_indices": json.dumps(chunk.segment_indices),
        "token_estimate": chunk.token_estimate,
        "source": str(chunk.metadata.get("source", "")),
        "language": str(chunk.metadata.get("language", "")),
    }


def parse_chroma_query_result(result: dict[str, Any]) -> list[VectorSearchResult]:
    ids = first_result_list(result.get("ids"))
    documents = first_result_list(result.get("documents"))
    metadatas = first_result_list(result.get("metadatas"))
    distances = first_result_list(result.get("distances"))
    parsed_results: list[VectorSearchResult] = []

    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        parsed_results.append(
            VectorSearchResult(
                chunk_id=str(chunk_id),
                video_id=str(metadata.get("video_id", "")),
                text=str(documents[index]) if index < len(documents) else "",
                start_seconds=float(metadata.get("start_seconds", 0.0)),
                end_seconds=float(metadata.get("end_seconds", 0.0)),
                segment_indices=parse_segment_indices(metadata.get("segment_indices")),
                distance=(
                    float(distances[index])
                    if index < len(distances) and distances[index] is not None
                    else None
                ),
                metadata={
                    key: value
                    for key, value in metadata.items()
                    if isinstance(value, str | int | float)
                },
            )
        )

    return parsed_results


def first_result_list(value: Any) -> list[Any]:
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]

    if isinstance(value, list):
        return value

    return []


def parse_segment_indices(value: Any) -> list[int]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, list):
            return [int(item) for item in parsed if isinstance(item, int | float | str)]

    return []


def get_vectorstore_service() -> ChromaVectorStoreService:
    return ChromaVectorStoreService(settings)
