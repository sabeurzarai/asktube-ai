from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.speech import router as speech_router
from app.api.routes.chat import router as chat_router
from app.api.routes.chunks import router as chunks_router
from app.api.routes.evaluations import router as evaluations_router
from app.api.routes.search import router as search_router
from app.api.routes.transcripts import router as transcripts_router
from app.api.routes.vectorstore import router as vectorstore_router

api_router = APIRouter()
api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(transcripts_router, prefix="/videos", tags=["transcripts"])
api_router.include_router(chunks_router, tags=["chunking"])
api_router.include_router(vectorstore_router, tags=["vectorstore"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(evaluations_router, tags=["evaluations"])
api_router.include_router(agent_router, tags=["agent"])
api_router.include_router(speech_router, tags=["speech"])
api_router.include_router(analytics_router, tags=["analytics"])
