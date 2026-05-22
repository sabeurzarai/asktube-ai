from pydantic import BaseModel, Field

from app.schemas.rag import TimestampCitation


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    video_id: str | None = Field(default=None, min_length=6, max_length=32)
    session_id: str | None = Field(default=None, min_length=3, max_length=120)


class AgentChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[TimestampCitation]
    tool_steps_used: list[str]
