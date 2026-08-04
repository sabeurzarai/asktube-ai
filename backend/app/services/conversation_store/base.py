from typing import Protocol

from app.schemas.rag import ChatMessage

DEFAULT_MAX_MESSAGES = 8


class ConversationStore(Protocol):
    """Per-session chat history.

    create_session_id is deliberately synchronous: it is uuid4() with no I/O, and
    making it async for symmetry would force `await` into the two call sites shaped
    `session_id or store.create_session_id()`.
    """

    def create_session_id(self) -> str: ...

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        """Oldest first, at most max_messages entries."""
        ...

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Append the pair, then drop anything beyond the newest max_messages."""
        ...
