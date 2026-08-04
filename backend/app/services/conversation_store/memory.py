from collections import defaultdict, deque
from uuid import uuid4

from app.schemas.rag import ChatMessage
from app.services.conversation_store.base import DEFAULT_MAX_MESSAGES


class InMemoryConversationStore:
    """Process-local history. The development and CI backend.

    Behaviour is identical to the ConversationMemoryService it replaces, so the
    contract suite pins today's semantics before the Postgres implementation has to
    reproduce them.
    """

    def __init__(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> None:
        self.max_messages = max_messages
        self._messages: dict[str, deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_messages)
        )

    def create_session_id(self) -> str:
        return str(uuid4())

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        return list(self._messages[session_id])

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        self._messages[session_id].append(ChatMessage(role="user", content=user_message))
        self._messages[session_id].append(
            ChatMessage(role="assistant", content=assistant_message)
        )
