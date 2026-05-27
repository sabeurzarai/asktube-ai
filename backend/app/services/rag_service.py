from collections.abc import AsyncIterator
import time

from fastapi import HTTPException, status
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from app.core.config import Settings, settings
from app.analytics.prometheus import RAG_LATENCY
from app.analytics.schemas import ChatMetricCreate, RAGMetricCreate
from app.analytics.service import get_analytics_service
from app.schemas.rag import ChatMessage, RAGChatResponse, RAGStreamEvent, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult
from app.services.memory_service import ConversationMemoryService, memory_service
from app.services.vectorstore_service import ChromaVectorStoreService, get_vectorstore_service


RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "You are AskTube AI, a transcript-grounded YouTube learning assistant. "
                "Answer using only the provided transcript context. If the context does not "
                "contain the answer, say you cannot answer from the transcript. Include "
                "timestamp references naturally when useful. Do not invent facts."
            ),
        ),
        (
            "human",
            (
                "Conversation memory:\n{memory}\n\n"
                "Transcript context:\n{context}\n\n"
                "User question:\n{question}"
            ),
        ),
    ]
)


class RAGService:
    def __init__(
        self,
        config: Settings,
        vectorstore: ChromaVectorStoreService,
        memory: ConversationMemoryService,
    ) -> None:
        self.config = config
        self.vectorstore = vectorstore
        self.memory = memory

    @traceable(name="rag_answer", run_type="chain", project_name=settings.langsmith_project)
    async def answer(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
        top_k: int,
    ) -> RAGChatResponse:
        answer_start = time.perf_counter()
        retrieval_start = time.perf_counter()
        active_session_id, retrieved_context = await self.prepare_context(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000

        if not retrieved_context:
            answer = "I cannot answer that from the transcript because no relevant context was found."
            self.memory.append_exchange(active_session_id, message, answer)
            await self._record_rag_metrics(
                message=message,
                session_id=active_session_id,
                retrieved_context=[],
                citations=[],
                answer=answer,
                retrieval_ms=retrieval_ms,
                generation_ms=0,
                started_at=answer_start,
            )
            return RAGChatResponse(
                session_id=active_session_id,
                answer=answer,
                citations=[],
                retrieved_context=[],
                memory=self.memory.get_messages(active_session_id),
            )

        chain = RAG_PROMPT | self.create_chat_model(streaming=False)
        generation_start = time.perf_counter()
        response = await chain.ainvoke(
            {
                "memory": format_memory(self.memory.get_messages(active_session_id)),
                "context": format_context(retrieved_context),
                "question": message,
            },
            config={
                "run_name": "transcript_grounded_answer",
                "tags": ["rag", "answer", "transcript-only"],
                "metadata": {
                    "video_id": video_id,
                    "session_id": active_session_id,
                    "top_k": top_k,
                    "context_chunks": len(retrieved_context),
                },
            },
        )
        generation_ms = (time.perf_counter() - generation_start) * 1000
        answer = str(response.content).strip()
        citations = build_citations(retrieved_context)
        self.memory.append_exchange(active_session_id, message, answer)
        await self._record_rag_metrics(
            message=message,
            session_id=active_session_id,
            retrieved_context=retrieved_context,
            citations=citations,
            answer=answer,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started_at=answer_start,
        )

        return RAGChatResponse(
            session_id=active_session_id,
            answer=answer,
            citations=citations,
            retrieved_context=retrieved_context,
            memory=self.memory.get_messages(active_session_id),
        )

    @traceable(name="rag_stream_answer", run_type="chain", project_name=settings.langsmith_project)
    async def stream_answer(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
        top_k: int,
    ) -> AsyncIterator[RAGStreamEvent]:
        answer_start = time.perf_counter()
        retrieval_start = time.perf_counter()
        active_session_id, retrieved_context = await self.prepare_context(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000

        yield RAGStreamEvent(
            type="context",
            session_id=active_session_id,
            citations=build_citations(retrieved_context),
            retrieved_context=retrieved_context,
            memory=self.memory.get_messages(active_session_id),
        )

        if not retrieved_context:
            answer = "I cannot answer that from the transcript because no relevant context was found."
            self.memory.append_exchange(active_session_id, message, answer)
            await self._record_rag_metrics(
                message=message,
                session_id=active_session_id,
                retrieved_context=[],
                citations=[],
                answer=answer,
                retrieval_ms=retrieval_ms,
                generation_ms=0,
                started_at=answer_start,
            )
            yield RAGStreamEvent(
                type="done",
                session_id=active_session_id,
                answer=answer,
                citations=[],
                retrieved_context=[],
                memory=self.memory.get_messages(active_session_id),
            )
            return

        chain = RAG_PROMPT | self.create_chat_model(streaming=True)
        answer_parts: list[str] = []
        generation_start = time.perf_counter()

        async for chunk in chain.astream(
            {
                "memory": format_memory(self.memory.get_messages(active_session_id)),
                "context": format_context(retrieved_context),
                "question": message,
            },
            config={
                "run_name": "transcript_grounded_stream",
                "tags": ["rag", "streaming", "transcript-only"],
                "metadata": {
                    "video_id": video_id,
                    "session_id": active_session_id,
                    "top_k": top_k,
                    "context_chunks": len(retrieved_context),
                },
            },
        ):
            token = str(chunk.content)
            if not token:
                continue

            answer_parts.append(token)
            yield RAGStreamEvent(type="token", session_id=active_session_id, token=token)

        answer = "".join(answer_parts).strip()
        generation_ms = (time.perf_counter() - generation_start) * 1000
        citations = build_citations(retrieved_context)
        self.memory.append_exchange(active_session_id, message, answer)
        await self._record_rag_metrics(
            message=message,
            session_id=active_session_id,
            retrieved_context=retrieved_context,
            citations=citations,
            answer=answer,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started_at=answer_start,
        )
        yield RAGStreamEvent(
            type="done",
            session_id=active_session_id,
            answer=answer,
            citations=citations,
            retrieved_context=retrieved_context,
            memory=self.memory.get_messages(active_session_id),
        )

    @traceable(name="rag_prepare_context", run_type="retriever", project_name=settings.langsmith_project)
    async def prepare_context(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
        top_k: int,
    ) -> tuple[str, list[VectorSearchResult]]:
        if not self.config.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for RAG answers.",
            )

        active_session_id = session_id or self.memory.create_session_id()
        retrieved_context = await self.vectorstore.similarity_search(
            query=message,
            limit=top_k,
            video_id=video_id,
        )

        return active_session_id, retrieved_context

    def create_chat_model(self, streaming: bool) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.config.chat_model,
            api_key=self.config.openai_api_key,
            temperature=0.1,
            streaming=streaming,
        )

    async def _record_rag_metrics(
        self,
        *,
        message: str,
        session_id: str,
        retrieved_context: list[VectorSearchResult],
        citations: list[TimestampCitation],
        answer: str,
        retrieval_ms: float,
        generation_ms: float,
        started_at: float,
    ) -> None:
        total_ms = (time.perf_counter() - started_at) * 1000
        RAG_LATENCY.observe(total_ms / 1000)
        context_tokens = sum(int(result.metadata.get("token_estimate", 0) or 0) for result in retrieved_context)
        if not context_tokens:
            context_tokens = sum(max(1, len(result.text.split()) * 4 // 3) for result in retrieved_context)
        citation_coverage = (
            len({citation.chunk_id for citation in citations}) / len({r.chunk_id for r in retrieved_context}) * 100
            if retrieved_context
            else 100.0
        )
        followups = max(0, len([m for m in self.memory.get_messages(session_id) if m.role == "user"]) - 1)
        analytics = get_analytics_service()
        await analytics.safe_track(
            analytics.track_rag_metric(
                RAGMetricCreate(
                    query=message,
                    retrieval_latency=retrieval_ms,
                    generation_latency=generation_ms,
                    chunks_retrieved=len(retrieved_context),
                    embedding_model=self.config.embedding_model,
                    citation_coverage=round(citation_coverage, 2),
                    context_tokens=int(context_tokens),
                    prompt_tokens=int(context_tokens + len(message.split()) * 4 // 3),
                    completion_tokens=max(1, len(answer.split()) * 4 // 3),
                    response_length=len(answer),
                    hallucination_warning=("cannot answer" in answer.lower() and not retrieved_context),
                    metadata_json={"session_id": session_id},
                )
            )
        )
        await analytics.safe_track(
            analytics.track_chat_metric(
                ChatMetricCreate(
                    session_id=session_id,
                    questions_count=1,
                    avg_response_time=round(total_ms, 2),
                    tokens_used=int(context_tokens + len(answer.split()) * 4 // 3),
                    followup_questions=followups,
                    metadata_json={"citation_count": len(citations)},
                )
            )
        )


def format_context(results: list[VectorSearchResult]) -> str:
    return "\n\n".join(
        (
            f"[{index + 1}] {format_timestamp(result.start_seconds)}-"
            f"{format_timestamp(result.end_seconds)} "
            f"(chunk_id={result.chunk_id})\n{result.text}"
        )
        for index, result in enumerate(results)
    )


def format_memory(messages: list[ChatMessage]) -> str:
    if not messages:
        return "No prior messages."

    return "\n".join(f"{message.role}: {message.content}" for message in messages[-8:])


def build_citations(results: list[VectorSearchResult]) -> list[TimestampCitation]:
    citations: list[TimestampCitation] = []
    seen: set[str] = set()

    for result in results:
        if result.chunk_id in seen:
            continue

        seen.add(result.chunk_id)
        citations.append(
            TimestampCitation(
                chunk_id=result.chunk_id,
                video_id=result.video_id,
                start_seconds=result.start_seconds,
                end_seconds=result.end_seconds,
                timestamp=(
                    f"{format_timestamp(result.start_seconds)}-"
                    f"{format_timestamp(result.end_seconds)}"
                ),
                text=result.text,
            )
        )

    return citations


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"

    return f"{minutes:02d}:{remaining_seconds:02d}"


def get_rag_service() -> RAGService:
    return RAGService(
        config=settings,
        vectorstore=get_vectorstore_service(),
        memory=memory_service,
    )
