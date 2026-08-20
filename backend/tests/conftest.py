"""
Test config. DB-backed tests need a real Postgres reachable at
TEST_DATABASE_URL (defaults to the local docker-compose stack from
postgres-database/, exposed on localhost:5432) with the ctts_user role and
ctts schema already bootstrapped (see postgres-database/init-db.sql).

Run: `pytest` from backend/ with that stack up, or set TEST_DATABASE_URL to
point elsewhere. Tests that need the DB use the `db_available` fixture
(skips at test time, not at import time - calling asyncio.run() during
module import fights pytest-asyncio for the event loop and produces false
"unreachable" results even against a live DB).
"""
import os

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ctts_user:vl4_31ElHcFiwwFdqjjp4BZXd3LJHDhm@localhost:5432/postgres",
    ),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-prod")
os.environ.setdefault("TENCENT_SECRET_ID", "test")
os.environ.setdefault("TENCENT_SECRET_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal, engine  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_each_test():
    """
    Each pytest-asyncio test function gets its own event loop by default,
    but `engine` is one module-level singleton shared by every test. Its
    connection pool holds onto connections opened in a previous test's
    (now-closed) loop, and asyncpg then fails the next test with "Future
    attached to a different loop". Disposing after every test forces the
    pool to open fresh connections in whichever loop asks for one next.
    """
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db_available() -> bool:
    # Deliberately function-scoped, not session-scoped: pytest-asyncio gives
    # each test function its own event loop by default, and an AsyncEngine's
    # connection pool can't be reused across different event loops ("Future
    # attached to a different loop") - matching this fixture's scope to the
    # test's own loop avoids that entirely instead of fighting it.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def clean_rate_limits(db_available):
    """Wipes ctts.rate_limits before and after each test that needs it."""
    if not db_available:
        pytest.skip("No reachable Postgres at TEST_DATABASE_URL")
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM ctts.rate_limits"))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM ctts.rate_limits"))
        await db.commit()
