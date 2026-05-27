import json
import time
from typing import Any

from fastapi import HTTPException, status
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langsmith import traceable

from app.core.config import Settings, settings
from app.analytics.service import get_analytics_service
from app.schemas.agent import AgentChatResponse
from app.schemas.rag import TimestampCitation
from app.services.chunking_service import get_chunking_service
from app.services.memory_service import ConversationMemoryService, memory_service
from app.services.rag_service import get_rag_service
from app.services.transcript_service import get_transcript_service
from app.services.vectorstore_service import get_vectorstore_service
from app.services.youtube_service import get_youtube_service
from app.tools.answer_question import make_answer_question_tool
from app.tools.ingest_video import make_ingest_video_tool
from app.tools.retrieve_context import make_retrieve_context_tool
from app.tools.search_youtube_videos import make_search_youtube_videos_tool


_SYSTEM_PROMPT = """\
You are AskTube AI, an intelligent YouTube learning assistant.

You have tools to search YouTube, ingest video transcripts into a vector store, \
retrieve relevant context, and answer questions grounded in transcript content.

RULES - follow these strictly:
1. Only answer using information from video transcripts. Never invent facts.
2. Always use the answer_question tool to produce the final answer; it handles \
   retrieval and citation automatically.
3. Before calling answer_question for a video that may not yet be in the store, \
   call ingest_video first.
4. When no video_id is provided, use search_youtube_videos to find candidates, \
   then proceed with the most relevant one.
5. Keep the pipeline efficient - do not repeat tool calls unnecessarily.

WORKFLOW:
  Known video  ->  ingest_video (if needed)  ->  answer_question
  Unknown topic ->  search_youtube_videos  ->  ingest_video  ->  answer_question
  Follow-up    ->  answer_question  (memory is already populated)
"""

_MAX_ITERATIONS = 8


class AgentService:
    def __init__(
        self,
        config: Settings,
        tools: list[StructuredTool],
        memory: ConversationMemoryService,
    ) -> None:
        self.config = config
        self.tools = tools
        self._tool_map = {t.name: t for t in tools}
        self.memory = memory

    @traceable(name="agent_chat", run_type="chain", project_name=settings.langsmith_project)
    async def chat(
        self,
        message: str,
        video_id: str | None,
        session_id: str | None,
    ) -> AgentChatResponse:
        agent_started_at = time.perf_counter()
        if not self.config.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for the agent.",
            )

        active_session_id = session_id or self.memory.create_session_id()
        model = ChatOpenAI(
            model=self.config.chat_model,
            api_key=self.config.openai_api_key,
            temperature=0.1,
        ).bind_tools(self.tools)

        messages: list = [SystemMessage(content=_build_system_prompt(video_id))]
        for msg in self.memory.get_messages(active_session_id):
            messages.append(
                HumanMessage(content=msg.content)
                if msg.role == "user"
                else AIMessage(content=msg.content)
            )
        messages.append(HumanMessage(content=message))

        tool_steps_used: list[str] = []
        citations: list[TimestampCitation] = []
        answer = ""
        answer_question_called = False

        for _ in range(_MAX_ITERATIONS):
            response = await model.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                # Only take the LLM's prose content if answer_question hasn't
                # already set a grounded answer from the transcript.
                if not answer:
                    answer = str(response.content).strip()
                break

            for tool_call in response.tool_calls:
                tool_name: str = tool_call["name"]
                tool_args: dict = tool_call["args"]
                tool_call_id: str = tool_call["id"]

                tool = self._tool_map.get(tool_name)
                tool_started_at = time.perf_counter()
                tool_failed = False
                if tool is None:
                    tool_result: Any = {"error": f"Unknown tool: {tool_name}"}
                    tool_failed = True
                else:
                    try:
                        tool_result = await tool.ainvoke(tool_args)
                    except Exception as exc:  # noqa: BLE001
                        tool_result = {"error": str(exc)}
                        tool_failed = True

                tool_steps_used.append(tool_name)
                get_analytics_service().safe_track_background(
                    get_analytics_service().track_event_safe(
                        "langchain_tool_executed",
                        session_id=active_session_id,
                        duration_ms=(time.perf_counter() - tool_started_at) * 1000,
                        metadata_json={
                            "tool_name": tool_name,
                            "success": not tool_failed,
                            "agent": "AskTube Agent",
                        },
                    )
                )

                if tool_name == "answer_question" and isinstance(tool_result, dict):
                    answer_question_called = True
                    answer = tool_result.get("answer", "")
                    citations = [
                        TimestampCitation(**c)
                        for c in tool_result.get("citations", [])
                    ]

                messages.append(
                    ToolMessage(
                        content=_format_for_context(tool_name, tool_result),
                        tool_call_id=tool_call_id,
                    )
                )

        if not answer:
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = str(msg.content).strip()
                    break

        # answer_question (via RAGService) already appended the exchange to memory;
        # only append here when the agent answered without that tool.
        if not answer_question_called:
            self.memory.append_exchange(active_session_id, message, answer)

        get_analytics_service().safe_track_background(
            get_analytics_service().track_event_safe(
                "agent_execution_completed",
                session_id=active_session_id,
                duration_ms=(time.perf_counter() - agent_started_at) * 1000,
                metadata_json={
                    "tool_steps_used": tool_steps_used,
                    "tool_count": len(tool_steps_used),
                    "success": bool(answer),
                },
            )
        )

        return AgentChatResponse(
            session_id=active_session_id,
            answer=answer,
            citations=citations,
            tool_steps_used=tool_steps_used,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_system_prompt(video_id: str | None) -> str:
    prompt = _SYSTEM_PROMPT
    if video_id:
        prompt += f"\n\nThe user is asking about video_id: {video_id}. Focus on this video."
    return prompt


def _format_for_context(tool_name: str, result: Any) -> str:
    """Produce a compact string representation of a tool result for LLM context."""
    if not isinstance(result, dict):
        return str(result)[:500]

    if tool_name == "search_youtube_videos":
        videos = result.get("videos", [])
        return json.dumps({
            "count": result.get("count", 0),
            "videos": [
                {"video_id": v["video_id"], "title": v["title"], "channel_title": v.get("channel_title", "")}
                for v in videos[:10]
            ],
        })

    if tool_name in {"ingest_video", "store_video_vectors"}:
        return json.dumps({
            "status": result.get("status", "ok"),
            "video_id": result.get("video_id"),
            "chunk_count": result.get("chunk_count") or result.get("count"),
            "embedding_model": result.get("embedding_model"),
        })

    if tool_name in {"extract_transcript", "chunk_transcript"}:
        return json.dumps({
            "status": "success",
            "video_id": result.get("video_id"),
            "segment_count": result.get("segment_count"),
            "chunk_count": result.get("chunk_count"),
        })

    if tool_name == "retrieve_context":
        return json.dumps({
            "result_count": result.get("result_count", 0),
            "results": [
                {
                    "chunk_id": r["chunk_id"],
                    "text_preview": r.get("text", "")[:120],
                    "start_seconds": r.get("start_seconds"),
                    "end_seconds": r.get("end_seconds"),
                }
                for r in result.get("results", [])[:5]
            ],
        })

    if tool_name == "answer_question":
        return json.dumps({
            "answer": result.get("answer"),
            "citation_count": len(result.get("citations", [])),
            "session_id": result.get("session_id"),
        })

    return json.dumps(result)[:1500]


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


def get_agent_service() -> AgentService:
    vectorstore = get_vectorstore_service()
    tools: list[StructuredTool] = [
        make_search_youtube_videos_tool(get_youtube_service()),
        make_ingest_video_tool(get_transcript_service(), get_chunking_service(), vectorstore),
        make_retrieve_context_tool(vectorstore),
        make_answer_question_tool(get_rag_service()),
    ]
    return AgentService(config=settings, tools=tools, memory=memory_service)
