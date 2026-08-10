from collections.abc import AsyncIterator
import logging
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable

from app.core.config import Settings, settings
from app.analytics.prometheus import RAG_LATENCY
from app.analytics.schemas import ChatMetricCreate, RAGMetricCreate
from app.analytics.service import get_analytics_service
from app.schemas.rag import ChatMessage, RAGChatResponse, RAGStreamEvent, TimestampCitation
from app.schemas.vectorstore import VectorSearchResult
from app.services.conversation_store import ConversationStore
from app.services.llm_provider import create_chat_model, require_chat_credentials
from app.services.memory_service import get_memory_service
from app.services.question_kind import is_broad_question
from app.services.vectorstore_service import VectorStoreService, get_vectorstore_service


logger = logging.getLogger(__name__)


# Above this the transcript will not fit alongside the prompt and the answer.
# A judgement, not a measurement: far above both evaluation videos (10k and 14k)
# and far below the model's context limit.
SUMMARY_MAX_CHARS = 40_000


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


CONTEXTUALIZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "Rewrite the user's latest question into a standalone search query for a "
                "video transcript, resolving pronouns and references using the conversation. "
                "Use ONLY information present in the conversation - never invent topics, "
                "names or details that were not mentioned. If the question is already "
                "self-contained, return it unchanged. Reply with the query and nothing else."
            ),
        ),
        ("human", "Conversation:\n{history}\n\nLatest question:\n{question}"),
    ]
)


class RAGService:
    def __init__(
        self,
        config: Settings,
        vectorstore: VectorStoreService,
        memory: ConversationStore,
    ) -> None:
        self.config = config
        self.vectorstore = vectorstore
        self.memory = memory

    async def _get_history(self, session_id: str) -> list[ChatMessage]:
        """Read conversation history, degrading to an empty history on outage.

        Memory is an enhancement, not the product: an answer without prior
        follow-up context is a mild quality regression, whereas refusing to
        answer because the store is unreachable would be an outage. Only
        connection-level failures are swallowed here; a bug in the store must
        still surface as a 500.
        """
        try:
            return await self.memory.get_messages(session_id)
        except (OSError, ConnectionError):
            logger.warning(
                "Conversation store unreachable reading history for session %s; "
                "continuing with empty memory.",
                session_id,
                exc_info=True,
            )
            return []

    async def _append_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        """Persist the exchange, tolerating a store outage.

        By the time this runs, retrieval and generation have already
        succeeded; discarding that work because the history write failed
        would waste it for nothing.
        """
        try:
            await self.memory.append_exchange(session_id, user_message, assistant_message)
        except (OSError, ConnectionError):
            logger.warning(
                "Conversation store unreachable appending exchange for session %s; "
                "answer will be returned without being remembered.",
                session_id,
                exc_info=True,
            )

    async def _contextualize(self, message: str, history: list[ChatMessage]) -> str:
        """Rewrite a follow-up into a standalone search query.

        A question like "and what did you just say it uses?" carries no
        information about the video, so embedding it verbatim points at generic
        conversational language and the nearest neighbours are effectively
        arbitrary. Resolving it against the history first is what makes the
        search find what the user actually means.

        Returns `message` unchanged when there is no history to resolve against,
        and falls back to it if the rewrite fails or comes back empty: retrieval
        quality is an enhancement, and it must never prevent an answer.
        """
        if not history:
            return message

        try:
            chain = CONTEXTUALIZE_PROMPT | self.create_chat_model(streaming=False)
            response = await chain.ainvoke(
                {"history": format_memory(history), "question": message},
                config={"run_name": "contextualize_query", "tags": ["rag", "query-rewrite"]},
            )
            rewritten = str(response.content).strip()
        except Exception as exc:  # noqa: BLE001 - deliberately broad: the call goes to a
            # third-party provider through LangChain and can raise almost anything
            # (timeouts, rate limits, provider-specific errors, parsing failures). The
            # fallback is the exact behaviour that existed before this method, so no
            # failure mode is made worse by catching broadly, and every catch is logged.
            logger.warning(
                "Query contextualization failed; searching with the raw message instead: %s",
                exc,
            )
            return message

        if not rewritten:
            logger.warning("Query contextualization returned empty text; using the raw message.")
            return message

        logger.info("Contextualized query: %r -> %r", message, rewritten)
        return rewritten

    async def summarize_video(
        self,
        message: str,
        video_id: str,
    ) -> tuple[str, list[TimestampCitation], int, float] | None:
        """Summarise a whole video, or return None to fall through to retrieval.

        None is not an error signal - it means "this path cannot help here", and
        every such case is one the retrieval path already handles. The
        summarisation path is an enhancement, so it degrades rather than failing,
        the same way conversation memory and the query rewrite do.

        Returns a 4-tuple of the answer text, the timestamp citations extracted
        from it, the character length of the rebuilt transcript that was sent to
        the model, and the milliseconds spent in `list_video_chunks`. The third
        item is not cosmetic: the summary path sends up to `SUMMARY_MAX_CHARS`
        of transcript in a single call while the response's `retrieved_context`
        stays empty on purpose (see `answer`), so callers need it to record the
        true cost of the call rather than recording it as free. The fourth item
        exists for the same reason: `list_video_chunks` is a full per-video table
        read, not free either, and folding its cost into generation_ms would
        report `retrieval_ms=0` for every summary answer and drag
        `avg_retrieval_latency` in analytics toward zero.
        """
        # Imported here, not at module scope: summary.py imports format_timestamp
        # from this module, so a top-level import would be circular.
        from app.services.summary import (
            SUMMARY_PROMPT,
            citations_for_timestamps,
            extract_timestamps,
            rebuild_transcript,
        )

        chunk_read_start = time.perf_counter()
        try:
            chunks = await self.vectorstore.list_video_chunks(video_id)
        except (OSError, ConnectionError):
            logger.warning(
                "Could not read chunks for %s; falling back to retrieval.",
                video_id,
                exc_info=True,
            )
            return None
        retrieval_ms = (time.perf_counter() - chunk_read_start) * 1000

        if not chunks:
            logger.info("No chunks stored for %s; not summarising.", video_id)
            return None

        transcript = rebuild_transcript(chunks)
        if len(transcript) > SUMMARY_MAX_CHARS:
            logger.warning(
                "Transcript for %s is %d characters, over the %d limit; "
                "answering by retrieval instead.",
                video_id, len(transcript), SUMMARY_MAX_CHARS,
            )
            return None

        try:
            chain = SUMMARY_PROMPT | self.create_chat_model(streaming=False)
            response = await chain.ainvoke(
                {"transcript": transcript, "question": message},
                config={
                    "run_name": "video_summary",
                    "tags": ["rag", "summary"],
                    # Without these, a summary trace could not be attributed to a
                    # video at all - the retrieval chain has carried video_id
                    # since it was written, and this one is the path where the
                    # call is LARGEST, so it is the one worth being able to find.
                    # session_id is deliberately absent: it is not resolved until
                    # after this call returns, and the enclosing `rag_answer` run
                    # already records it, so duplicating it here would mean
                    # creating a session id for an answer that may never exist.
                    "metadata": {
                        "video_id": video_id,
                        "chunk_count": len(chunks),
                        "transcript_chars": len(transcript),
                    },
                },
            )
            answer = str(response.content).strip()
        except Exception as exc:  # noqa: BLE001 - deliberately broad: the call goes to a
            # third-party provider through LangChain and can raise almost anything
            # (timeouts, rate limits, provider-specific errors, parsing failures). The
            # fallback degrades to the retrieval path, so no failure mode is made
            # worse by catching broadly, and every catch is logged.
            logger.warning("Summarisation failed for %s: %s", video_id, exc, exc_info=True)
            return None

        if not answer:
            logger.warning("Summarisation returned empty text for %s.", video_id)
            return None

        citations = citations_for_timestamps(extract_timestamps(answer), chunks)
        return answer, citations, len(transcript), retrieval_ms

    @traceable(name="rag_answer", run_type="chain", project_name=settings.langsmith_project)
    async def answer(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
        top_k: int,
    ) -> RAGChatResponse:
        answer_start = time.perf_counter()

        # Checked before the summary branch, not only inside prepare_context: without
        # it, a missing API key would do a full chunk read and a doomed model call
        # before failing, and log a misleading "Summarisation failed" warning along
        # the way. Idempotent and identical for narrow questions, since
        # prepare_context calls it again below.
        require_chat_credentials(self.config)

        if is_broad_question(message) and video_id is not None:
            summary = await self.summarize_video(message=message, video_id=video_id)
            if summary is not None:
                summary_answer, summary_citations, transcript_chars, summary_retrieval_ms = summary
                active_session_id = session_id or self.memory.create_session_id()
                await self._append_exchange(active_session_id, message, summary_answer)
                messages = await self._get_history(active_session_id)
                # generation_ms is the elapsed time MINUS the chunk read
                # summarize_video already timed, so the two do not double-count
                # the same wall-clock time under different labels.
                summary_generation_ms = max(
                    0.0, (time.perf_counter() - answer_start) * 1000 - summary_retrieval_ms
                )
                await self._record_rag_metrics(
                    message=message,
                    session_id=active_session_id,
                    retrieved_context=[],
                    citations=summary_citations,
                    answer=summary_answer,
                    retrieval_ms=summary_retrieval_ms,
                    generation_ms=summary_generation_ms,
                    started_at=answer_start,
                    messages=messages,
                    context_chars=transcript_chars,
                )
                return RAGChatResponse(
                    session_id=active_session_id,
                    answer=summary_answer,
                    citations=summary_citations,
                    # Empty on purpose: no chunk selection took place, and listing
                    # the chunks that fed the summary would misrepresent that.
                    retrieved_context=[],
                    memory=messages,
                )

        retrieval_start = time.perf_counter()
        active_session_id, retrieved_context, history = await self.prepare_context(
            message=message,
            video_id=video_id,
            session_id=session_id,
            top_k=top_k,
        )
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000

        if not retrieved_context:
            answer = "I cannot answer that from the transcript because no relevant context was found."
            await self._append_exchange(active_session_id, message, answer)
            messages = await self._get_history(active_session_id)
            await self._record_rag_metrics(
                message=message,
                session_id=active_session_id,
                retrieved_context=[],
                citations=[],
                answer=answer,
                retrieval_ms=retrieval_ms,
                generation_ms=0,
                started_at=answer_start,
                messages=messages,
            )
            return RAGChatResponse(
                session_id=active_session_id,
                answer=answer,
                citations=[],
                retrieved_context=[],
                memory=messages,
            )

        chain = RAG_PROMPT | self.create_chat_model(streaming=False)
        generation_start = time.perf_counter()
        response = await chain.ainvoke(
            {
                "memory": format_memory(history),
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
        await self._append_exchange(active_session_id, message, answer)
        messages = await self._get_history(active_session_id)
        await self._record_rag_metrics(
            message=message,
            session_id=active_session_id,
            retrieved_context=retrieved_context,
            citations=citations,
            answer=answer,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started_at=answer_start,
            messages=messages,
        )

        return RAGChatResponse(
            session_id=active_session_id,
            answer=answer,
            citations=citations,
            retrieved_context=retrieved_context,
            memory=messages,
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

        # Checked before the summary branch, not only inside prepare_context: without
        # it, a missing API key would do a full chunk read and a doomed model call
        # before failing, and log a misleading "Summarisation failed" warning along
        # the way. Mirrors the same check in `answer` - streaming must not skip it.
        require_chat_credentials(self.config)

        if is_broad_question(message) and video_id is not None:
            summary = await self.summarize_video(message=message, video_id=video_id)
            if summary is not None:
                summary_answer, summary_citations, transcript_chars, summary_retrieval_ms = summary
                active_session_id = session_id or self.memory.create_session_id()
                history = await self._get_history(active_session_id)
                yield RAGStreamEvent(
                    type="context",
                    session_id=active_session_id,
                    citations=summary_citations,
                    retrieved_context=[],
                    memory=history,
                )
                yield RAGStreamEvent(
                    type="token", session_id=active_session_id, token=summary_answer
                )
                await self._append_exchange(active_session_id, message, summary_answer)
                messages = await self._get_history(active_session_id)
                # generation_ms is the elapsed time MINUS the chunk read
                # summarize_video already timed, so the two do not double-count
                # the same wall-clock time under different labels.
                summary_generation_ms = max(
                    0.0, (time.perf_counter() - answer_start) * 1000 - summary_retrieval_ms
                )
                await self._record_rag_metrics(
                    message=message,
                    session_id=active_session_id,
                    retrieved_context=[],
                    citations=summary_citations,
                    answer=summary_answer,
                    retrieval_ms=summary_retrieval_ms,
                    generation_ms=summary_generation_ms,
                    started_at=answer_start,
                    messages=messages,
                    context_chars=transcript_chars,
                )
                yield RAGStreamEvent(
                    type="done",
                    session_id=active_session_id,
                    answer=summary_answer,
                    citations=summary_citations,
                    retrieved_context=[],
                    memory=messages,
                )
                return

        retrieval_start = time.perf_counter()
        active_session_id, retrieved_context, history = await self.prepare_context(
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
            memory=history,
        )

        if not retrieved_context:
            answer = "I cannot answer that from the transcript because no relevant context was found."
            await self._append_exchange(active_session_id, message, answer)
            messages = await self._get_history(active_session_id)
            await self._record_rag_metrics(
                message=message,
                session_id=active_session_id,
                retrieved_context=[],
                citations=[],
                answer=answer,
                retrieval_ms=retrieval_ms,
                generation_ms=0,
                started_at=answer_start,
                messages=messages,
            )
            yield RAGStreamEvent(
                type="done",
                session_id=active_session_id,
                answer=answer,
                citations=[],
                retrieved_context=[],
                memory=messages,
            )
            return

        chain = RAG_PROMPT | self.create_chat_model(streaming=True)
        answer_parts: list[str] = []
        generation_start = time.perf_counter()

        async for chunk in chain.astream(
            {
                "memory": format_memory(history),
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
        await self._append_exchange(active_session_id, message, answer)
        messages = await self._get_history(active_session_id)
        await self._record_rag_metrics(
            message=message,
            session_id=active_session_id,
            retrieved_context=retrieved_context,
            citations=citations,
            answer=answer,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
            started_at=answer_start,
            messages=messages,
        )
        yield RAGStreamEvent(
            type="done",
            session_id=active_session_id,
            answer=answer,
            citations=citations,
            retrieved_context=retrieved_context,
            memory=messages,
        )

    @traceable(name="rag_prepare_context", run_type="retriever", project_name=settings.langsmith_project)
    async def prepare_context(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
        top_k: int,
    ) -> tuple[str, list[VectorSearchResult], list[ChatMessage]]:
        """Resolve the session, search, and hand back the history that was used.

        The history is returned rather than re-read by the caller: it is needed
        twice - once to contextualize the search query and once to build the
        generation prompt - and against Postgres each read is a network round
        trip on the answer path.
        """
        require_chat_credentials(self.config)

        active_session_id = session_id or self.memory.create_session_id()
        history = await self._get_history(active_session_id)
        search_query = await self._contextualize(message, history)
        retrieved_context = await self.vectorstore.similarity_search(
            query=search_query,
            limit=top_k,
            video_id=video_id,
        )

        return active_session_id, retrieved_context, history

    def create_chat_model(self, streaming: bool) -> ChatOpenAI:
        # Delegate to the shared factory so chat-model construction lives in
        # exactly one place (supports OpenAI and NVIDIA providers).
        return create_chat_model(self.config, streaming=streaming, temperature=0.1)

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
        messages: list[ChatMessage],
        context_chars: int | None = None,
    ) -> None:
        """Record retrieval/generation metrics for one answer.

        `context_chars` is for the summary path only: `retrieved_context` is
        deliberately empty there (see `answer`), so the usual token/coverage
        derivation from it would record the most expensive call - up to
        `SUMMARY_MAX_CHARS` of transcript in one prompt - as the cheapest.
        When it is not None it overrides `context_tokens`, and it also
        switches `citation_coverage` and `hallucination_warning` to be judged
        against the citations instead of the (empty) retrieved context.
        """
        total_ms = (time.perf_counter() - started_at) * 1000
        RAG_LATENCY.observe(total_ms / 1000)
        if context_chars is not None:
            # `context_chars` is a CHARACTER count (len(transcript)), so the
            # characters-to-tokens ratio is `// 4` (~4 chars/token). This must
            # not be confused with the `* 4 // 3` used elsewhere in this
            # method, which is a WORDS-to-tokens ratio applied to
            # `len(text.split())` - mixing the two overestimates tokens by
            # roughly 5.3x: applying `* 4 // 3` to a CHARACTER count instead of
            # `// 4` scales it by (4/3) / (1/4) = 16/3 ≈ 5.3x, not 5.7x.
            context_tokens = max(1, context_chars // 4)
        else:
            context_tokens = sum(
                int(result.metadata.get("token_estimate", 0) or 0) for result in retrieved_context
            )
            if not context_tokens:
                context_tokens = sum(max(1, len(result.text.split()) * 4 // 3) for result in retrieved_context)
        if context_chars is not None:
            citation_coverage = 100.0 if citations else 0.0
        else:
            citation_coverage = (
                len({citation.chunk_id for citation in citations})
                / len({r.chunk_id for r in retrieved_context})
                * 100
                if retrieved_context
                else 100.0
            )
        followups = max(0, len([m for m in messages if m.role == "user"]) - 1)
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
                    hallucination_warning=(
                        ("cannot answer" in answer.lower() and not citations)
                        if context_chars is not None
                        else ("cannot answer" in answer.lower() and not retrieved_context)
                    ),
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
        memory=get_memory_service(),
    )
