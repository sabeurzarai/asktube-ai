from functools import lru_cache

from app.core.config import settings
from app.services.conversation_store import ConversationStore
from app.services.conversation_store.factory import create_conversation_store


@lru_cache
def get_memory_service() -> ConversationStore:
    """Built once per process.

    Reached through FastAPI dependencies, which run per request; the postgres
    backend holds a session factory that must not be rebuilt each time.
    """
    return create_conversation_store(settings)
