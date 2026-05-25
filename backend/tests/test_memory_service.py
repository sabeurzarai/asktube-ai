import re

import pytest

from app.schemas.rag import ChatMessage
from app.services.memory_service import ConversationMemoryService


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


# ---------------------------------------------------------------------------
# create_session_id
# ---------------------------------------------------------------------------


def test_create_session_id_is_valid_uuid4() -> None:
    svc = ConversationMemoryService()
    session_id = svc.create_session_id()
    assert UUID_RE.match(session_id), f"Not a valid UUID4: {session_id}"


def test_create_session_id_is_unique() -> None:
    svc = ConversationMemoryService()
    ids = {svc.create_session_id() for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------------------
# get_messages
# ---------------------------------------------------------------------------


def test_get_messages_unknown_session_returns_empty_list() -> None:
    svc = ConversationMemoryService()
    assert svc.get_messages("does-not-exist") == []


def test_get_messages_returns_list_not_deque() -> None:
    svc = ConversationMemoryService()
    svc.append_exchange("s1", "hello", "world")
    result = svc.get_messages("s1")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# append_exchange
# ---------------------------------------------------------------------------


def test_append_exchange_stores_user_then_assistant() -> None:
    svc = ConversationMemoryService()
    svc.append_exchange("s1", "What is RAG?", "RAG stands for Retrieval-Augmented Generation.")

    messages = svc.get_messages("s1")
    assert len(messages) == 2
    assert messages[0] == ChatMessage(role="user", content="What is RAG?")
    assert messages[1] == ChatMessage(role="assistant", content="RAG stands for Retrieval-Augmented Generation.")


def test_multiple_exchanges_accumulate_in_order() -> None:
    svc = ConversationMemoryService(max_messages=10)
    svc.append_exchange("s1", "Q1", "A1")
    svc.append_exchange("s1", "Q2", "A2")
    svc.append_exchange("s1", "Q3", "A3")

    messages = svc.get_messages("s1")
    assert len(messages) == 6
    roles = [m.role for m in messages]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]
    contents = [m.content for m in messages]
    assert contents == ["Q1", "A1", "Q2", "A2", "Q3", "A3"]


# ---------------------------------------------------------------------------
# max_messages / deque eviction
# ---------------------------------------------------------------------------


def test_oldest_messages_evicted_when_limit_reached() -> None:
    svc = ConversationMemoryService(max_messages=4)
    svc.append_exchange("s1", "Q1", "A1")  # will be evicted
    svc.append_exchange("s1", "Q2", "A2")  # will be evicted
    svc.append_exchange("s1", "Q3", "A3")  # retained

    messages = svc.get_messages("s1")
    assert len(messages) == 4
    contents = [m.content for m in messages]
    assert "Q1" not in contents
    assert "A1" not in contents
    assert contents == ["Q2", "A2", "Q3", "A3"]


def test_max_messages_one_exchange_keeps_only_last_pair() -> None:
    svc = ConversationMemoryService(max_messages=2)
    svc.append_exchange("s1", "first", "first-answer")
    svc.append_exchange("s1", "second", "second-answer")

    messages = svc.get_messages("s1")
    assert len(messages) == 2
    assert messages[0].content == "second"
    assert messages[1].content == "second-answer"


# ---------------------------------------------------------------------------
# session isolation
# ---------------------------------------------------------------------------


def test_sessions_are_isolated() -> None:
    svc = ConversationMemoryService()
    svc.append_exchange("alice", "Hello from Alice", "Hi Alice")
    svc.append_exchange("bob", "Hello from Bob", "Hi Bob")

    alice_msgs = svc.get_messages("alice")
    bob_msgs = svc.get_messages("bob")

    assert all("Alice" in m.content for m in alice_msgs)
    assert all("Bob" in m.content for m in bob_msgs)


def test_unknown_session_does_not_leak_into_other_sessions() -> None:
    svc = ConversationMemoryService()
    svc.append_exchange("real", "Q", "A")

    _ = svc.get_messages("phantom")  # touching unknown session must not corrupt "real"

    assert len(svc.get_messages("real")) == 2


def test_separate_instances_do_not_share_state() -> None:
    svc_a = ConversationMemoryService()
    svc_b = ConversationMemoryService()
    svc_a.append_exchange("s", "from-a", "ans-a")

    assert svc_b.get_messages("s") == []


# ---------------------------------------------------------------------------
# default max_messages value
# ---------------------------------------------------------------------------


def test_default_max_messages_is_eight() -> None:
    svc = ConversationMemoryService()
    # 5 exchanges = 10 messages, should keep only last 8
    for i in range(5):
        svc.append_exchange("s", f"Q{i}", f"A{i}")

    messages = svc.get_messages("s")
    assert len(messages) == 8
    # Oldest two messages (Q0, A0) must be gone
    assert messages[0].content == "Q1"
