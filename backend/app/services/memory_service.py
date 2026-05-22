from collections import defaultdict, deque
from uuid import uuid4

from app.schemas.rag import ChatMessage


class ConversationMemoryService:
    def __init__(self, max_messages: int = 8) -> None:
        self.max_messages = max_messages
        self._messages: dict[str, deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_messages)
        )

    def create_session_id(self) -> str:
        return str(uuid4())

    def get_messages(self, session_id: str) -> list[ChatMessage]:
        return list(self._messages[session_id])

    def append_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        self._messages[session_id].append(ChatMessage(role="user", content=user_message))
        self._messages[session_id].append(
            ChatMessage(role="assistant", content=assistant_message)
        )


memory_service = ConversationMemoryService()


def get_memory_service() -> ConversationMemoryService:
    return memory_service
