import pytest

from tests.conftest import NotAScratchDatabase, reject_non_scratch_database

# ── The guard itself ──────────────────────────────────────────────────────────
# Tested as a pure function: a safeguard whose job is to fire when no scratch
# database is available must not itself require one.


def test_guard_rejects_pointing_at_the_application_database():
    with pytest.raises(NotAScratchDatabase, match="same database as DATABASE_URL"):
        reject_non_scratch_database(
            test_database_url="postgresql+asyncpg://u:p@host/db",
            app_database_url="postgresql+asyncpg://u:p@host/db",
            existing_row_count=0,
        )


def test_guard_rejects_a_table_that_already_holds_data():
    # The real incident: the table held a demo video's chunks and the fixture
    # deleted them. Row count alone is enough to refuse.
    with pytest.raises(NotAScratchDatabase, match="10 row"):
        reject_non_scratch_database(
            test_database_url="postgresql+asyncpg://u:p@scratch/db",
            app_database_url="postgresql+asyncpg://u:p@prod/db",
            existing_row_count=10,
        )


def test_guard_allows_a_distinct_and_empty_database():
    reject_non_scratch_database(
        test_database_url="postgresql+asyncpg://u:p@scratch/db",
        app_database_url="postgresql+asyncpg://u:p@prod/db",
        existing_row_count=0,
    )


def test_guard_allows_an_empty_database_when_the_app_has_none_configured():
    # Local checkouts have no DATABASE_URL; the row-count check still applies.
    reject_non_scratch_database(
        test_database_url="postgresql+asyncpg://u:p@scratch/db",
        app_database_url=None,
        existing_row_count=0,
    )
