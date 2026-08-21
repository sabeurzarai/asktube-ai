"""The one place that decides what "a store is unavailable" looks like.

Two call sites need this and used to disagree. `routes/vectorstore.py` had a
carefully worded 502 naming a paused Supabase project; `RAGService` - the path
the frontend actually uses through `/api/chat` and `/api/agent/chat` - had no
handling at all, so the same outage surfaced there as a bare 500.

The exception tuple is the part that was wrong, not the message. The route's
comment asserted that a paused project "fails exactly like a network fault
(connection refused/reset)". Production disproved that on 2026-08-21: the pooler
ACCEPTS the connection and then reports the paused project at the Postgres
protocol level. SQLAlchemy wraps that in SQLAlchemyError, which is not an
OSError, so a catch of (OSError, ConnectionError) missed the single case the
message was written for.

Why a bare 500 is worse than it looks: an unhandled exception propagates past
CORSMiddleware, so the response carries no Access-Control-Allow-Origin and the
browser reports only "Failed to fetch" - the message never reaches the user.
Raising HTTPException keeps the response inside the middleware stack.
"""

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

# Everything that means "the store did not answer", including a database that
# answered with a refusal. Used by BOTH store families, because they share one
# DATABASE_URL: when it is paused, conversation history and vectors fail together.
# ValueError is deliberately NOT here - a dimension mismatch is a different fault
# with a different fix, handled at its own site. Neither are AttributeError or
# TypeError: a backend missing a method is a bug and must still surface as a 500.
STORE_UNAVAILABLE: tuple[type[BaseException], ...] = (
    OSError,
    ConnectionError,
    SQLAlchemyError,
)

VECTOR_STORE_UNAVAILABLE_DETAIL = (
    "Vector store unavailable. If DATABASE_URL points at Supabase, the project "
    "may be paused - Free plan projects pause after 7 days of low activity and "
    "must be restored from the dashboard. Videos already ingested are not lost; "
    "they are read back once the database is running again."
)


def vector_store_unavailable() -> HTTPException:
    """A 502 that names the likely cause and the fix, not just "error"."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=VECTOR_STORE_UNAVAILABLE_DETAIL,
    )
