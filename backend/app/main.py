from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401 - registers the ORM classes on Base.metadata;
# nothing else in the app imports this module (routers use raw SQL), so
# without this import Base.metadata is empty and create_all() below
# silently creates zero tables - verified against a real Postgres instance.
from .config import settings
from .database import Base, engine
from .routers import ctts as ctts_router
from .routers import voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Deliberately does NOT try to CREATE SCHEMA here: ctts_user only has
    # CREATE-within-the-ctts-schema privilege, not CREATE-a-new-schema
    # privilege on the database (verified against a real Postgres instance -
    # CREATE SCHEMA IF NOT EXISTS still checks the CREATE permission before
    # the existence check, so it fails even when the schema already exists).
    # Schema creation is postgres-database/init-db.sql's job (run as the
    # postgres superuser); this app only creates its own tables inside it.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Chinese TTS API", version="1.0.0", lifespan=lifespan)

origins = settings.CORS_ORIGINS.split(",") if settings.CORS_ORIGINS != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice.router)
app.include_router(ctts_router.router)


@app.get("/health")
async def health():
    return {"ok": True}
