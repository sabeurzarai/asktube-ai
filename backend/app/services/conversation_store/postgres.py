from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.schemas.rag import ChatMessage
from app.services.conversation_store.base import DEFAULT_MAX_MESSAGES


class PostgresConversationStore:
    """Conversation history backed by Postgres."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_messages: int = DEFAULT_MAX_MESSAGES,
    ) -> None:
        self._session_factory = session_factory
        self._max_messages = max_messages

    def create_session_id(self) -> str:
        return str(uuid4())

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        # Ordered by id, not created_at: now() is the transaction timestamp, so both
        # rows of one exchange share it and ordering by it would be arbitrary.
        statement = text(
            "select role, content from conversation_messages "
            "where session_id = :session_id "
            "order by id desc limit :limit"
        )
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    statement,
                    {"session_id": session_id, "limit": self._max_messages},
                )
            ).mappings().all()

        # Newest-first from SQL so LIMIT keeps the right end; reversed here so the
        # caller receives oldest-first, matching the deque it replaces.
        return [
            ChatMessage(role=row["role"], content=row["content"])
            for row in reversed(rows)
        ]

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        async with self._session_factory() as session:
            # One transaction: a failure must not leave a question stored without
            # its answer, nor trim against a half-written exchange.
            async with session.begin():
                await session.execute(
                    text(
                        "insert into conversation_messages (session_id, role, content) "
                        "values (:session_id, 'user', :user_message), "
                        "       (:session_id, 'assistant', :assistant_message)"
                    ),
                    {
                        "session_id": session_id,
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                    },
                )
                await session.execute(
                    text(
                        "delete from conversation_messages "
                        "where session_id = :session_id and id not in ("
                        "  select id from conversation_messages "
                        "  where session_id = :session_id order by id desc limit :limit"
                        ")"
                    ),
                    {"session_id": session_id, "limit": self._max_messages},
                )
