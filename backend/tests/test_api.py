"""
HTTP-level integration tests against the real FastAPI app (ASGI transport,
no real network socket). Validation-only tests below need no DB (all these
checks run before any database touch in voice.py); only the happy-path test
needs a real Postgres, gated by the db_available fixture.
"""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text as sqltext

from app.database import AsyncSessionLocal
from app.main import app
from app.routers import voice


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_tts_speak_rejects_empty_text(client):
    r = await client.post("/api/voice/tts/speak", json={"text": "", "rate": 1, "voice": "x_xiaoyan"})
    assert r.status_code == 400
    assert "No Chinese text" in r.json()["detail"]


@pytest.mark.asyncio
async def test_tts_speak_rejects_non_chinese_text(client):
    r = await client.post(
        "/api/voice/tts/speak", json={"text": "hello world, no chinese here", "rate": 1, "voice": "x_xiaoyan"}
    )
    assert r.status_code == 400
    assert "No Chinese text" in r.json()["detail"]


@pytest.mark.asyncio
async def test_tts_speak_rejects_over_500k_chars(client):
    r = await client.post(
        "/api/voice/tts/speak", json={"text": "你" * 500_001, "rate": 1, "voice": "x_xiaoyan"}
    )
    assert r.status_code == 400
    assert "500000" in r.json()["detail"]


@pytest.mark.asyncio
async def test_tts_export_rejects_empty_text(client):
    r = await client.post("/api/voice/tts/export", json={"text": "", "rate": 1, "voice": "x_xiaoyan"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_stt_record_rejects_empty_audio(client):
    r = await client.post("/api/voice/stt/record", files={"audio": ("empty.wav", b"", "audio/wav")})
    assert r.status_code == 400
    assert "Empty audio" in r.json()["detail"]


@pytest.mark.asyncio
async def test_stt_record_rejects_oversized_audio(client):
    huge = b"0" * (10 * 1024 * 1024 + 1)
    r = await client.post("/api/voice/stt/record", files={"audio": ("big.wav", huge, "audio/wav")})
    assert r.status_code == 400
    assert "Max 10 MB" in r.json()["detail"]


@pytest.mark.asyncio
async def test_tts_speak_happy_path_returns_audio(client, monkeypatch, db_available):
    """Full request → validation → rate-limit → (mocked) synthesis → audio/mpeg response."""
    if not db_available:
        pytest.skip("No reachable Postgres at TEST_DATABASE_URL")

    def fake_synthesize(*, tencent_fn, text, rate, voice_name):
        return b"\xff\xfb\x90\x00fake-mp3-bytes", "iflytek"

    monkeypatch.setattr(voice, "synthesize_with_fallback", fake_synthesize)

    async with AsyncSessionLocal() as db:
        await db.execute(sqltext("DELETE FROM ctts.rate_limits"))
        await db.commit()

    r = await client.post(
        "/api/voice/tts/speak", json={"text": "你好，世界", "rate": 1, "voice": "x_xiaoyan"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"\xff\xfb\x90\x00fake-mp3-bytes"
