from pydantic import BaseModel, Field

from app.schemas.vectorstore import VectorSearchResult


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class TimestampCitation(BaseModel):
    chunk_id: str
    video_id: str
    start_seconds: float
    end_seconds: float
    timestamp: str
    text: str


class RAGChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    video_id: str | None = Field(default=None, min_length=6, max_length=32)
    session_id: str | None = Field(default=None, min_length=3, max_length=120)
    top_k: int = Field(default=5, ge=1, le=12)


class RAGStreamRequest(RAGChatRequest):
    pass


class RAGChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[TimestampCitation]
    retrieved_context: list[VectorSearchResult]
    memory: list[ChatMessage]


class RAGStreamEvent(BaseModel):
    type: str
    session_id: str | None = None
    token: str | None = None
    answer: str | None = None
    citations: list[TimestampCitation] | None = None
    retrieved_context: list[VectorSearchResult] | None = None
    memory: list[ChatMessage] | None = None
    error: str | None = None
