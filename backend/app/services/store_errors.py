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

try:  # pragma: no cover - asyncpg ships with the Postgres backend
    from asyncpg.exceptions import PostgresError
except ImportError:  # SQLite-only installs have no asyncpg
    PostgresError = ()

# Everything that means "the store did not answer", including a database that
# answered with a refusal. Used by BOTH store families, because they share one
# DATABASE_URL: when it is down, conversation history and vectors fail together.
#
# PostgresError is here because of a measured miss, not for symmetry. The error
# production raised - "(ENOTFOUND) tenant/user postgres.<ref> not found" - is an
# asyncpg.exceptions.InternalServerError raised inside the connection pool's
# connect step. SQLAlchemy wraps DBAPI errors from EXECUTION, not from that path,
# so it arrived raw; and asyncpg's PostgresError descends straight from Exception.
# A tuple of (OSError, ConnectionError, SQLAlchemyError) therefore still let the
# real outage through as a bare 500 - the exact failure this module exists to
# prevent, missed on the first attempt.
#
# ValueError is deliberately NOT here - a dimension mismatch is a different fault
# with a different fix, handled at its own site. Neither are AttributeError or
# TypeError: a backend missing a method is a bug and must still surface as a 500.
STORE_UNAVAILABLE: tuple[type[BaseException], ...] = tuple(
    e for e in (OSError, ConnectionError, SQLAlchemyError, PostgresError) if isinstance(e, type)
)

VECTOR_STORE_UNAVAILABLE_DETAIL = (
    "Vector store unavailable - the database did not answer. Two causes are "
    "common and this message cannot tell them apart, so check both: the Supabase "
    "project behind DATABASE_URL may be PAUSED (Free plan projects pause after 7 "
    "days of low activity and are restored from the dashboard), or it may NO "
    "LONGER EXIST at that reference - a deleted or recreated project leaves "
    "DATABASE_URL pointing at a tenant the pooler does not know, which fails "
    "identically from the outside. Compare the project ref in DATABASE_URL "
    "against the dashboard. Videos already ingested are not lost; they are read "
    "back once the database answers again. The server log carries the underlying "
    "error."
)


def vector_store_unavailable() -> HTTPException:
    """A 502 that names the likely cause and the fix, not just "error"."""
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=VECTOR_STORE_UNAVAILABLE_DETAIL,
    )
