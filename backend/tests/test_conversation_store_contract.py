import pytest

from app.services.conversation_store import InMemoryConversationStore


# Task 5 appends the postgres backend here. Test bodies stay unchanged.
@pytest.fixture(params=["memory"])
async def store(request):
    if request.param == "memory":
        yield InMemoryConversationStore(max_messages=4)
        return
    raise AssertionError(f"unknown backend {request.param}")


async def test_appended_exchange_is_readable(store):
    session = store.create_session_id()
    await store.append_exchange(session, "question", "answer")

    messages = await store.get_messages(session)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "question"),
        ("assistant", "answer"),
    ]


async def test_messages_come_back_oldest_first(store):
    session = store.create_session_id()
    await store.append_exchange(session, "first", "reply one")
    await store.append_exchange(session, "second", "reply two")

    contents = [m.content for m in await store.get_messages(session)]
    assert contents == ["first", "reply one", "second", "reply two"]


async def test_both_messages_of_one_exchange_keep_their_order(store):
    """Regression guard for ordering.

    In Postgres both rows of an exchange are written in one transaction and share
    an identical created_at, so any implementation ordering by that column would
    return them in an arbitrary order — putting the answer before the question.
    """
    session = store.create_session_id()
    await store.append_exchange(session, "q", "a")

    roles = [m.role for m in await store.get_messages(session)]
    assert roles == ["user", "assistant"]


async def test_sessions_are_isolated(store):
    first = store.create_session_id()
    second = store.create_session_id()
    await store.append_exchange(first, "mine", "yours")

    assert await store.get_messages(second) == []
    assert len(await store.get_messages(first)) == 2


async def test_unknown_session_returns_empty_list(store):
    assert await store.get_messages("never-seen") == []


async def test_history_is_trimmed_to_max_messages_dropping_oldest(store):
    # The fixture uses max_messages=4, so three exchanges (6 messages) must leave
    # the newest 4 and drop the first exchange entirely.
    session = store.create_session_id()
    await store.append_exchange(session, "q1", "a1")
    await store.append_exchange(session, "q2", "a2")
    await store.append_exchange(session, "q3", "a3")

    contents = [m.content for m in await store.get_messages(session)]
    assert contents == ["q2", "a2", "q3", "a3"]


async def test_create_session_id_is_unique_and_synchronous(store):
    first = store.create_session_id()
    second = store.create_session_id()
    assert first != second
    assert isinstance(first, str)
