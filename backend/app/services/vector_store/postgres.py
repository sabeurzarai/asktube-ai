from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.chunks import TranscriptChunk
from app.schemas.vectorstore import VectorSearchResult


class PgVectorStore:
    """Transcript chunk storage backed by Postgres + pgvector."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_dimensions: int = 1536,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_dimensions = embedding_dimensions

    async def replace_video_chunks(
        self,
        video_id: str,
        chunks: list[TranscriptChunk],
    ) -> list[str]:
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"chunk {chunk.chunk_id} has no embedding")
            if len(chunk.embedding) != self._embedding_dimensions:
                raise ValueError(
                    f"embedding dimension mismatch for {chunk.chunk_id}: "
                    f"{len(chunk.embedding)} != {self._embedding_dimensions}"
                )

        async with self._session_factory() as session:
            # One transaction: a failure part-way leaves the previous chunks intact
            # rather than a video with nothing retrievable.
            async with session.begin():
                await session.execute(
                    text("delete from transcript_chunks where video_id = :video_id"),
                    {"video_id": video_id},
                )
                if chunks:
                    await session.execute(
                        text(
                            "insert into transcript_chunks "
                            "(chunk_id, video_id, chunk_index, text, start_seconds, "
                            " end_seconds, segment_indices, token_estimate, source, "
                            " language, embedding) "
                            "values (:chunk_id, :video_id, :chunk_index, :text, "
                            " :start_seconds, :end_seconds, :segment_indices, "
                            " :token_estimate, :source, :language, "
                            # asyncpg has no codec for the custom `vector` OID unless
                            # pgvector.asyncpg.register_vector() runs on the connection,
                            # which this store cannot force (the session factory/engine
                            # is injected). Binding straight to `:embedding` would make
                            # Postgres resolve the parameter's type as `vector`, and
                            # asyncpg would fail to encode the Python str for it. Casting
                            # through `text` first keeps the bind parameter on a core
                            # type asyncpg already knows how to encode; the `::vector`
                            # cast then happens server-side on the resulting text value.
                            "cast(:embedding as text)::vector)"
                        ),
                        [
                            {
                                "chunk_id": chunk.chunk_id,
                                "video_id": chunk.video_id,
                                "chunk_index": chunk.index,
                                "text": chunk.text,
                                "start_seconds": chunk.start_seconds,
                                "end_seconds": chunk.end_seconds,
                                "segment_indices": chunk.segment_indices,
                                "token_estimate": chunk.token_estimate,
                                "source": str(chunk.metadata.get("source", "")) or None,
                                "language": str(chunk.metadata.get("language", "")) or None,
                                "embedding": str(chunk.embedding),
                            }
                            for chunk in chunks
                        ],
                    )

        return [chunk.chunk_id for chunk in chunks]

    async def similarity_search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        video_id: str | None = None,
    ) -> list[VectorSearchResult]:
        # Both `<=>` operands below cast the bind parameter through `text` before
        # `::vector` for the same reason as the INSERT in replace_video_chunks:
        # asyncpg only has codecs for core types. A bare `:query_embedding::vector`
        # does NOT dodge this — Postgres assigns the parameter the cast's *target*
        # type, so the parameter is still typed `vector` and asyncpg fails to encode
        # the Python str. Routing it through `text` first keeps asyncpg's inferred
        # parameter type on something it already knows how to send.
        statement = text(
            "select chunk_id, video_id, text, start_seconds, end_seconds, "
            "       segment_indices, source, language, "
            "       embedding <=> cast(:query_embedding as text)::vector as distance "
            "from transcript_chunks "
            # cast(... as text), NOT :video_id::text — SQLAlchemy's text() ignores a
            # :name immediately followed by another colon so it does not mangle
            # PostgreSQL's :: cast operator. The bind is then never substituted and
            # Postgres receives a literal ':', failing with "syntax error at or near".
            "where (cast(:video_id as text) is null or video_id = :video_id) "
            "order by embedding <=> cast(:query_embedding as text)::vector "
            "limit :limit"
        )

        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {
                        "query_embedding": str(query_embedding),
                        "video_id": video_id,
                        "limit": limit,
                    },
                )
            ).mappings().all()

        return [
            VectorSearchResult(
                chunk_id=row["chunk_id"],
                video_id=row["video_id"],
                text=row["text"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                segment_indices=list(row["segment_indices"] or []),
                distance=float(row["distance"]),
                metadata={
                    key: value
                    for key, value in (
                        ("source", row["source"]),
                        ("language", row["language"]),
                    )
                    if value is not None
                },
            )
            for row in rows
        ]

    async def list_video_chunks(self, video_id: str) -> list[TranscriptChunk]:
        # `embedding` is deliberately not selected: the caller wants text and
        # timestamps, and a whole video's worth of 1536-float vectors would be
        # transferred and parsed for nothing.
        statement = text(
            "select chunk_id, video_id, chunk_index, text, start_seconds, "
            "       end_seconds, segment_indices, token_estimate, source, language "
            "from transcript_chunks "
            "where video_id = :video_id "
            "order by chunk_index asc"
        )

        async with self._session_factory() as session:
            rows = (
                await session.execute(statement, {"video_id": video_id})
            ).mappings().all()

        return [
            TranscriptChunk(
                chunk_id=row["chunk_id"],
                index=row["chunk_index"],
                video_id=row["video_id"],
                text=row["text"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                segment_indices=list(row["segment_indices"] or []),
                token_estimate=row["token_estimate"] or 0,
                metadata={
                    key: value
                    for key, value in (
                        ("source", row["source"]),
                        ("language", row["language"]),
                    )
                    if value is not None
                },
                embedding=None,
            )
            for row in rows
        ]
