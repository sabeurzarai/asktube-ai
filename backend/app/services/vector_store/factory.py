from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.vector_store.base import VectorStore
from app.services.vector_store.memory import InMemoryVectorStore
from app.services.vector_store.postgres import PgVectorStore


def resolve_vector_backend(config: Settings) -> str:
    """Explicit VECTOR_BACKEND wins; otherwise derive from DATABASE_URL.

    Deriving rather than defaulting to "memory" is deliberate: forgetting the
    variable in a deployment that has a database would otherwise start an
    in-memory store that resets on every restart and looks like it is working.
    A bare checkout has no DATABASE_URL and still needs no infrastructure.
    """
    if config.vector_backend:
        return config.vector_backend.lower()
    return "pgvector" if config.database_url else "memory"


def create_vector_store(config: Settings) -> VectorStore:
    """Select the vector store backend.

    Only 'memory' and 'pgvector' are built here — both are real VectorStore
    implementations. 'chroma' is not: ChromaVectorStoreService does not satisfy
    the VectorStore protocol (it has upsert_chunks/similarity_search(query: str),
    not replace_video_chunks/similarity_search(query_embedding: list[float])), so
    selecting it is a service-layer decision made in
    app.services.vectorstore_service.get_vectorstore_service(), not here.
    """
    backend = resolve_vector_backend(config)

    if backend == "memory":
        return InMemoryVectorStore()

    if backend == "pgvector":
        if not config.database_url:
            raise ValueError(
                "VECTOR_BACKEND=pgvector requires DATABASE_URL to be set."
            )
        engine = create_async_engine(
            config.database_url,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        return PgVectorStore(factory)

    if backend == "chroma":
        raise ValueError(
            "VECTOR_BACKEND=chroma is no longer supported: ChromaDB was removed in "
            "favour of Postgres + pgvector. Unset VECTOR_BACKEND to derive the "
            "backend from DATABASE_URL."
        )

    raise ValueError(
        f"Unknown VECTOR_BACKEND {backend!r}. Expected 'pgvector' or 'memory'."
    )
