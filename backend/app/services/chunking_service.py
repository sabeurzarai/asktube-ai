import hashlib
from dataclasses import dataclass

from fastapi import HTTPException, status
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings, settings
from app.schemas.chunks import TranscriptChunk
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


@dataclass(frozen=True)
class ChunkingOptions:
    max_chunk_chars: int
    overlap_segments: int
    include_embeddings: bool = False


class ChunkingService:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def chunk_transcript(
        self,
        transcript: TranscriptResponse,
        options: ChunkingOptions,
    ) -> tuple[list[TranscriptChunk], str | None]:
        chunks = build_semantic_chunks(
            transcript=transcript,
            max_chunk_chars=options.max_chunk_chars,
            overlap_segments=options.overlap_segments,
        )

        embedding_model = None
        if options.include_embeddings:
            if not self.config.openai_api_key:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OPENAI_API_KEY is required for embedding generation.",
                )

            embedding_model = self.config.embedding_model
            embeddings = OpenAIEmbeddings(
                model=self.config.embedding_model,
                api_key=self.config.openai_api_key,
            )
            vectors = await embeddings.aembed_documents([chunk.text for chunk in chunks])

            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector

        return chunks, embedding_model


def build_semantic_chunks(
    transcript: TranscriptResponse,
    max_chunk_chars: int,
    overlap_segments: int,
) -> list[TranscriptChunk]:
    """Build timestamp-preserving chunks from transcript segments.

    LangChain's text splitter is used as a guardrail for unusually long individual
    transcript segments, while the primary grouping preserves timestamp boundaries.
    """

    chunks: list[TranscriptChunk] = []
    active_segments: list[TranscriptSegment] = []
    active_length = 0

    for segment in transcript.segments:
        segment_text = segment.text.strip()
        if not segment_text:
            continue

        if len(segment_text) > max_chunk_chars:
            flush_active_chunk(chunks, transcript, active_segments)
            active_segments = []
            active_length = 0
            chunks.extend(split_large_segment(transcript, segment, max_chunk_chars))
            continue

        projected_length = active_length + len(segment_text) + (1 if active_segments else 0)
        if active_segments and projected_length > max_chunk_chars:
            flush_active_chunk(chunks, transcript, active_segments)
            active_segments = active_segments[-overlap_segments:] if overlap_segments else []
            active_length = sum(len(item.text) for item in active_segments)

        active_segments.append(segment)
        active_length += len(segment_text) + 1

    flush_active_chunk(chunks, transcript, active_segments)
    normalize_chunk_indexes(chunks, transcript)
    return chunks


def flush_active_chunk(
    chunks: list[TranscriptChunk],
    transcript: TranscriptResponse,
    segments: list[TranscriptSegment],
) -> None:
    if not segments:
        return

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    if not text:
        return

    chunks.append(
        create_chunk(
            transcript=transcript,
            text=text,
            index=len(chunks),
            start_seconds=segments[0].start_seconds,
            end_seconds=segments[-1].end_seconds,
            segment_indices=[segment.index for segment in segments],
        )
    )


def split_large_segment(
    transcript: TranscriptResponse,
    segment: TranscriptSegment,
    max_chunk_chars: int,
) -> list[TranscriptChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chunk_chars,
        chunk_overlap=min(160, max_chunk_chars // 5),
        separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
    )
    document = Document(
        page_content=segment.text,
        metadata={
            "video_id": transcript.video_id,
            "segment_index": segment.index,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
        },
    )
    split_documents = splitter.split_documents([document])
    chunks: list[TranscriptChunk] = []

    for split_document in split_documents:
        chunks.append(
            create_chunk(
                transcript=transcript,
                text=split_document.page_content,
                index=0,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                segment_indices=[segment.index],
            )
        )

    return chunks


def normalize_chunk_indexes(chunks: list[TranscriptChunk], transcript: TranscriptResponse) -> None:
    for index, chunk in enumerate(chunks):
        chunk.index = index
        chunk.chunk_id = create_chunk_id(
            video_id=transcript.video_id,
            index=index,
            start_seconds=chunk.start_seconds,
            end_seconds=chunk.end_seconds,
            text=chunk.text,
        )
        chunk.metadata["chunk_index"] = index


def create_chunk(
    transcript: TranscriptResponse,
    text: str,
    index: int,
    start_seconds: float,
    end_seconds: float,
    segment_indices: list[int],
) -> TranscriptChunk:
    chunk_id = create_chunk_id(transcript.video_id, index, start_seconds, end_seconds, text)

    return TranscriptChunk(
        chunk_id=chunk_id,
        index=index,
        video_id=transcript.video_id,
        text=text,
        start_seconds=round(start_seconds, 3),
        end_seconds=round(end_seconds, 3),
        segment_indices=segment_indices,
        token_estimate=estimate_tokens(text),
        metadata={
            "video_id": transcript.video_id,
            "source": transcript.source,
            "language": transcript.language or "",
            "chunk_index": index,
            "start_seconds": round(start_seconds, 3),
            "end_seconds": round(end_seconds, 3),
            "segment_indices": segment_indices,
        },
    )


def create_chunk_id(
    video_id: str,
    index: int,
    start_seconds: float,
    end_seconds: float,
    text: str,
) -> str:
    digest = hashlib.sha1(f"{video_id}:{index}:{start_seconds}:{end_seconds}:{text}".encode()).hexdigest()
    return f"{video_id}:{index}:{digest[:12]}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()) * 4 // 3)


def get_chunking_service() -> ChunkingService:
    return ChunkingService(settings)
