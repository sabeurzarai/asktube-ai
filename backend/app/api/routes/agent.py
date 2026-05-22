from fastapi import APIRouter, Depends

from app.schemas.agent import AgentChatRequest, AgentChatResponse
from app.services.agent_service import AgentService, get_agent_service

router = APIRouter()


@router.post("/agent/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentChatResponse:
    return await agent_service.chat(
        message=request.message,
        video_id=request.video_id,
        session_id=request.session_id,
    )
