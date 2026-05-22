from collections.abc import AsyncIterator

from fastapi import HTTPException, status
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from app.core.config import Settings, settings
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
        active_session_id, retrieved_context = await self.prepare_context(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )

        if not retrieved_context:
            answer = "I cannot answer that from the transcript because no relevant context was found."
            self.memory.append_exchange(active_session_id, message, answer)
            return RAGChatResponse(
                session_id=active_session_id,
                answer=answer,
                citations=[],
                retrieved_context=[],
                memory=self.memory.get_messages(active_session_id),
            )

        chain = RAG_PROMPT | self.create_chat_model(streaming=False)
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
        answer = str(response.content).strip()
        citations = build_citations(retrieved_context)
        self.memory.append_exchange(active_session_id, message, answer)

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
        active_session_id, retrieved_context = await self.prepare_context(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )

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
        citations = build_citations(retrieved_context)
        self.memory.append_exchange(active_session_id, message, answer)
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
