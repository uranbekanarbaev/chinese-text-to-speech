"""
Public Chinese TTS/STT endpoints (uranbekanarbaev.dev + the browser extension),
powered by iFLYTEK (primary) with Tencent Cloud as fallback.

Ported out of hsk-tutor's backend/app/routers/voice.py - dropped the
internal /api/voice/tts and /api/voice/transcribe endpoints, which stay in
hsk-tutor since they're used by its own lesson features (flashcard audio),
not by this product. Everything below this line is CTTS-only and unchanged
in behavior from the monolith version.

TTS: TextToVoice (synchronous, returns base64 MP3)
STT: CreateRecTask + DescribeTaskStatus (async polling, accepts base64 audio)
Both APIs run in a thread-pool so FastAPI stays non-blocking.
"""

import asyncio
import base64
import logging
import re
import time as _time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import settings
from ..database import AsyncSessionLocal
from ..services import amplitude as amp
from ..services.audio_cache import get_cached_url, save_to_cache
from ..services.tts_resilient import synthesize_with_fallback

logger = logging.getLogger(__name__)

# Tencent Cloud SDK (synchronous)
from tencentcloud.asr.v20190614 import asr_client
from tencentcloud.asr.v20190614.models import CreateRecTaskRequest, DescribeTaskStatusRequest
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tts.v20190823 import models as tts_models
from tencentcloud.tts.v20190823 import tts_client

router = APIRouter(prefix="/api/voice", tags=["voice"])

# Sized so several concurrent users each doing a large chunked request
# (_PER_REQUEST_CONCURRENCY=3 below) still get real parallelism instead of
# queueing behind each other; each worker can occupy a thread for up to
# 2 iFLYTEK attempts + a Tencent fallback.
_executor = ThreadPoolExecutor(max_workers=16)


# Helpers

def _cred():
    return credential.Credential(settings.TENCENT_SECRET_ID, settings.TENCENT_SECRET_KEY)


def _tts_client():
    hp = HttpProfile()
    hp.endpoint = "tts.intl.tencentcloudapi.com"
    cp = ClientProfile()
    cp.httpProfile = hp
    return tts_client.TtsClient(_cred(), settings.TENCENT_REGION, cp)


def _asr_client():
    return asr_client.AsrClient(_cred(), settings.TENCENT_REGION)


def _clean_for_tts(text: str) -> str:
    """
    Prepare text for Chinese TTS.
    Keeps Chinese characters + ASCII words + basic punctuation.
    Strips markdown, code blocks, emoji.
    """
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'[*_#~|]', '', text)
    text = re.sub(r'\.{2,}', '。', text)
    text = re.sub(r'[:—–]', '，', text)

    result = []
    for char in text:
        if '一' <= char <= '鿿':
            result.append(char)
        elif '　' <= char <= '〿' or '＀' <= char <= '￯':
            result.append(char)
        else:
            cat = unicodedata.category(char)
            if cat.startswith('L') or cat.startswith('N'):
                result.append(char)
            elif cat.startswith('Z') or char == ' ':
                result.append(' ')
            elif char in '.,!?，。！？、；：\n':
                result.append(char)

    cleaned = ''.join(result)
    cleaned = re.sub(r' {2,}', ' ', cleaned).strip()
    return cleaned


# TTS

# iFLYTEK voice name → unique cache ID (200xxx range avoids collision with Tencent IDs)
_VOICE_MAP: dict[str, int] = {
    "x_xiaoyan":              200001,
    "x_xiaolin":              200002,
    "x_xiaomei":              200003,
    "x_xiaoxue":              200004,
    "x_xiaoxi":               200005,
    "x_xiaoyuan":             200006,
    "x_xiaofeng":             200007,
    "x_yifeng":               200008,
    "x_laoma":                200009,
    "x4_lingfeizhe_assist":   200010,
    "x4_lingxiaoqi_assist":   200011,
    "x4_ziwen_assist":        200012,
    "x4_yilin":               200013,
    "x3_xiaoyue":             200014,
    # Backward compat, old Tencent names map to nearest iFLYTEK cache slot
    "zhiyu":   200001, "zhiling": 200002, "zhimei":  200003,
    "zhiyun":  200008, "zhili":   200005, "zhiyan":  200001,
    "zhina":   200007, "zhiqi":   200004, "zhiyun2": 200009, "zhihua": 200009,
}

# iFLYTEK voice name → Tencent VoiceType ID (used only when Tencent is the fallback)
_TENCENT_FALLBACK: dict[str, int] = {
    "x_xiaoyan":              101001,
    "x_xiaolin":              101002,
    "x_xiaomei":              101003,
    "x_xiaoxue":              101008,
    "x_xiaoxi":               101005,
    "x_xiaoyuan":             101001,
    "x_xiaofeng":             101007,
    "x_yifeng":               101004,
    "x_laoma":                101009,
    "x4_lingfeizhe_assist":   101004,
    "x4_lingxiaoqi_assist":   101001,
    "x4_ziwen_assist":        101004,
    "x4_yilin":               101001,
    "x3_xiaoyue":             101001,
    # Old Tencent names fall through as-is
    "zhiyu": 101001, "zhiling": 101002, "zhimei": 101003,
    "zhiyun": 101004, "zhili": 101005, "zhiyan": 101006,
    "zhina": 101007, "zhiqi": 101008, "zhiyun2": 101009, "zhihua": 101010,
}

_DEFAULT_VOICE = "x_xiaoyan"

CJK_RE = re.compile(r'[一-鿿㐀-䶿]')

# Tencent's TextToVoice hard limit is 500 chars per call; iFLYTEK is looser but
# we chunk to the same size so the Tencent fallback never sees oversized input.
_TTS_CHUNK_LIMIT = 500
_SENTENCE_END = set('。！？；\n')


def _split_text_chunks(text: str, max_len: int = _TTS_CHUNK_LIMIT) -> list[str]:
    """Split text into <=max_len pieces, preferring sentence-boundary cuts."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + max_len, n)
        if end < n:
            for i in range(end - 1, start, -1):
                if text[i] in _SENTENCE_END:
                    end = i + 1
                    break
        chunks.append(text[start:end])
        start = end
    return chunks


# Caps how many chunks *one request* may have in flight at once. The thread
# pool (_executor) is shared by every concurrent user; without this, a
# single huge request (up to MAX_REQUEST_CHARS / _TTS_CHUNK_LIMIT = 1000
# chunks) would fire them all via asyncio.gather at once and occupy every
# worker until it finished, starving everyone else's requests behind it.
# Capping per-request concurrency below the pool size guarantees headroom
# stays available for other users regardless of how large any one request is.
_PER_REQUEST_CONCURRENCY = 3


async def _synthesize_chunked(clean: str, rate: float, voice_name: str, tencent_type: int) -> tuple[bytes, str]:
    """Synthesize arbitrarily long text by splitting into per-vendor-safe chunks and concatenating audio."""
    loop = asyncio.get_running_loop()
    chunks = _split_text_chunks(clean)
    fairness_gate = asyncio.Semaphore(_PER_REQUEST_CONCURRENCY)

    async def _run(chunk: str) -> tuple[bytes, str]:
        async with fairness_gate:
            return await loop.run_in_executor(
                _executor,
                lambda: synthesize_with_fallback(
                    tencent_fn=lambda: _tts_export_sync(chunk, rate, tencent_type),
                    text=chunk,
                    rate=rate,
                    voice_name=voice_name,
                ),
            )

    # gather() preserves input order in `results` regardless of completion order,
    # so the concatenated audio still plays back in the original text order.
    results = await asyncio.gather(*(_run(c) for c in chunks))
    audio = b"".join(r[0] for r in results)
    providers = "+".join(sorted({r[1] for r in results}))
    return audio, providers


def _tts_export_sync(text: str, rate: float, voice_type: int) -> bytes:
    """Tencent TTS, public export variant with rate + voice selection."""
    client = _tts_client()

    # Convert browser speechSynthesis rate (0.5–2) → Tencent speed (-2 to 2)
    # Formula: tencent_speed = (rate - 1) * 2  →  0.5x→-1, 1x→0, 2x→2
    tencent_speed = round(max(-2.0, min(2.0, (rate - 1.0) * 2.0)), 1)

    req = tts_models.TextToVoiceRequest()
    req.Text            = text[:_TTS_CHUNK_LIMIT]   # Tencent hard limit; callers pre-chunk to this size
    req.SessionId       = f"exp-{uuid.uuid4().hex[:16]}"
    req.VoiceType       = voice_type
    req.Codec           = "mp3"
    req.SampleRate      = 16000
    req.PrimaryLanguage = 1
    req.Speed           = tencent_speed
    req.Volume          = 5

    resp = client.TextToVoice(req)
    return base64.b64decode(resp.Audio)


class TTSPublicRequest(BaseModel):
    text: str
    rate: float | None = 1.0
    voice: str | None = "x_xiaoyan"


TTSExportRequest = TTSPublicRequest
TTSSpeakRequest  = TTSPublicRequest


@router.post("/tts/speak")
async def tts_speak(
    body: TTSSpeakRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    Public TTS speak, optional Google auth.
    - Anonymous: 30 req/day or DAILY_CHAR_LIMIT_ANON chars/day per IP.
    - Authenticated: 30 req/day or DAILY_CHAR_LIMIT_AUTH chars/day per user.
    - Any single request over MAX_REQUEST_CHARS is rejected outright.
    Text over _TTS_CHUNK_LIMIT chars is split and synthesized in parallel
    (bounded per-request, see _PER_REQUEST_CONCURRENCY), then concatenated.
    Returns audio/mpeg blob for inline playback.
    """
    from .ctts import MAX_REQUEST_CHARS, check_and_increment_rate_limit, decode_ctts_token
    from .ctts import save_history as _save_history

    clean = _clean_for_tts(body.text.strip())
    if not clean or not CJK_RE.search(clean):
        raise HTTPException(status_code=400, detail="No Chinese text detected. Please paste Mandarin characters.")
    if len(clean) > MAX_REQUEST_CHARS:
        raise HTTPException(status_code=400, detail=f"Text too long. Max {MAX_REQUEST_CHARS} characters per request.")

    rate = max(0.5, min(2.0, body.rate or 1.0))
    voice_name = body.voice or _DEFAULT_VOICE
    voice_type = _VOICE_MAP.get(voice_name, 200001)
    tencent_type = _TENCENT_FALLBACK.get(voice_name, 101001)

    ctts_user_id: int | None = None
    if authorization and authorization.startswith("Bearer "):
        ctts_user_id = decode_ctts_token(authorization.removeprefix("Bearer "))

    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "0.0.0.0")
    )
    amp_user = str(ctts_user_id) if ctts_user_id else f"anon_{amp._hash_ip(ip)}"

    background_tasks.add_task(amp.track, "Бэкенд_ттс_запрос_принят", {
        "длина_текста": len(clean),
        "голос": voice_name,
        "скорость": rate,
        "авторизован": ctts_user_id is not None,
    }, amp_user)

    allowed, err_msg = await check_and_increment_rate_limit(ip, len(clean), user_id=ctts_user_id)
    if not allowed:
        background_tasks.add_task(amp.track, "Бэкенд_ттс_лимит_превышен", {
            "сообщение": err_msg,
        }, amp_user)
        raise HTTPException(status_code=429, detail=err_msg)

    t0 = _time.monotonic()

    async with AsyncSessionLocal() as db:
        cached_url = await get_cached_url(db, clean, voice_type)

    if cached_url:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10) as hclient:
            r = await hclient.get(cached_url)
            if r.status_code == 200:
                if ctts_user_id is not None:
                    background_tasks.add_task(_save_history, ctts_user_id, clean, voice_name, rate, cached_url)
                background_tasks.add_task(amp.track, "Бэкенд_ттс_аудио_отдано", {
                    "длина_текста": len(clean),
                    "кэш_хит": True,
                    "время_мс": int((_time.monotonic() - t0) * 1000),
                }, amp_user)
                return Response(content=r.content, media_type="audio/mpeg")

    try:
        if len(clean) <= _TTS_CHUNK_LIMIT:
            loop = asyncio.get_running_loop()
            audio_bytes, provider = await loop.run_in_executor(
                _executor,
                lambda: synthesize_with_fallback(
                    tencent_fn=lambda: _tts_export_sync(clean, rate, tencent_type),
                    text=clean,
                    rate=rate,
                    voice_name=voice_name,
                ),
            )
        else:
            audio_bytes, provider = await _synthesize_chunked(clean, rate, voice_name, tencent_type)
    except Exception as e:
        err_str = str(e)
        background_tasks.add_task(amp.track, "Бэкенд_ттс_ошибка", {
            "ошибка": err_str,
            "длина_текста": len(clean),
            "голос": voice_name,
        }, amp_user)
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    async def _bg_save(ab: bytes, ct: str, vt: int, uid: int | None, vn: str, r: float):
        url: str | None = None
        try:
            async with AsyncSessionLocal() as db:
                url = await save_to_cache(db, ct, ab, vt)
        except Exception as exc:
            logger.warning(f"OSS cache save failed: {exc}")
        if uid is not None:
            try:
                await _save_history(uid, ct, vn, r, url)
            except Exception as exc:
                logger.warning(f"History save failed: {exc}")

    background_tasks.add_task(_bg_save, audio_bytes, clean, voice_type, ctts_user_id, voice_name, rate)
    background_tasks.add_task(amp.track, "Бэкенд_ттс_аудио_отдано", {
        "длина_текста": len(clean),
        "кэш_хит": False,
        "время_мс": int((_time.monotonic() - t0) * 1000),
        "провайдер": provider,
    }, amp_user)

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/tts/export")
async def tts_export(body: TTSExportRequest, background_tasks: BackgroundTasks, request: Request):
    """
    Public TTS export, no auth support (download tool) - now rate-limited
    like /tts/speak's anonymous tier, closing a previously-flagged gap where
    this endpoint had no daily budget at all.
    Returns audio/mpeg blob directly for download.
    Text over _TTS_CHUNK_LIMIT chars is split and synthesized in parallel, then concatenated.
    """
    from .ctts import MAX_REQUEST_CHARS, check_and_increment_rate_limit

    text = _clean_for_tts(body.text.strip())
    if not text or not CJK_RE.search(text):
        raise HTTPException(status_code=400, detail="No Chinese text detected. Please paste Mandarin characters.")
    if len(text) > MAX_REQUEST_CHARS:
        raise HTTPException(status_code=400, detail=f"Text too long. Max {MAX_REQUEST_CHARS} characters per request.")

    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "0.0.0.0")
    )
    allowed, err_msg = await check_and_increment_rate_limit(ip, len(text))
    if not allowed:
        raise HTTPException(status_code=429, detail=err_msg)

    rate = max(0.5, min(2.0, body.rate or 1.0))
    vcn         = body.voice or _DEFAULT_VOICE
    voice_type  = _VOICE_MAP.get(vcn, 200001)
    tencent_type = _TENCENT_FALLBACK.get(vcn, 101001)

    async with AsyncSessionLocal() as db:
        cached_url = await get_cached_url(db, text, voice_type)
    if cached_url:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10) as client:
            r = await client.get(cached_url)
            if r.status_code == 200:
                return Response(
                    content=r.content,
                    media_type="audio/mpeg",
                    headers={"Content-Disposition": f'attachment; filename="chinese-tts-{uuid.uuid4().hex[:8]}.mp3"'},
                )

    try:
        if len(text) <= _TTS_CHUNK_LIMIT:
            loop = asyncio.get_running_loop()
            audio_bytes, _ = await loop.run_in_executor(
                _executor,
                lambda: synthesize_with_fallback(
                    tencent_fn=lambda: _tts_export_sync(text, rate, tencent_type),
                    text=text,
                    rate=rate,
                    voice_name=vcn,
                ),
            )
        else:
            audio_bytes, _ = await _synthesize_chunked(text, rate, vcn, tencent_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")

    async def _bg_save(audio_bytes: bytes, clean_text: str, vt: int):
        async with AsyncSessionLocal() as db:
            try:
                await save_to_cache(db, clean_text, audio_bytes, vt)
            except Exception as exc:
                logger.warning(f"Cache save failed: {exc}")

    background_tasks.add_task(_bg_save, audio_bytes, text, voice_type)

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="chinese-tts-{uuid.uuid4().hex[:8]}.mp3"'},
    )


# STT

_TIMESTAMP_RE = re.compile(r'^\[[\d:.,\s]+\]\s*')


def _strip_timestamps(text: str) -> str:
    return _TIMESTAMP_RE.sub('', text).strip()


def _stt_sync(audio_bytes: bytes, language: str = "zh") -> str:
    """
    Upload audio as base64 via CreateRecTask, poll until done.
    language: "zh" → 16k_zh, "en" → 16k_en, others → 16k_zh
    """
    _engine_map = {"zh": "16k_zh", "en": "16k_en", "ja": "16k_ja", "ko": "16k_ko"}
    engine = _engine_map.get(language, "16k_zh")

    client = _asr_client()

    req = CreateRecTaskRequest()
    req.EngineModelType = engine
    req.ChannelNum      = 1
    req.ResTextFormat   = 0
    req.SourceType      = 1                              # 1 = base64
    req.Data            = base64.b64encode(audio_bytes).decode()
    req.DataLen         = len(audio_bytes)

    resp = client.CreateRecTask(req)
    task_id = resp.Data.TaskId

    req_status = DescribeTaskStatusRequest()
    req_status.TaskId = task_id

    # 120 * 2s = 4 min ceiling - CreateRecTask genuinely scales with audio
    # duration, so a short fixed wait fails on anything but a short clip.
    for _ in range(120):
        _time.sleep(2)
        sr = client.DescribeTaskStatus(req_status)
        status = sr.Data.Status
        if status == 2:                                  # done
            return _strip_timestamps(sr.Data.Result or "")
        if status == 3:                                  # error
            raise RuntimeError(sr.Data.ErrorMsg or "ASR task failed")

    raise RuntimeError("ASR task timed out after 4 minutes")


@router.post("/stt/record")
async def stt_record(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    language: str = "zh",
    request: Request = None,
    authorization: str | None = Header(default=None),
):
    """
    Public STT transcription, optional Google auth.
    Anonymous: same daily rate limit bucket as TTS (30 req/day per IP).
    Returns {"transcript": "..."}
    """
    from .ctts import check_and_increment_rate_limit, decode_ctts_token

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio too large. Max 10 MB.")

    ctts_user_id: int | None = None
    if authorization and authorization.startswith("Bearer "):
        ctts_user_id = decode_ctts_token(authorization.removeprefix("Bearer "))

    ip = "unknown"
    if request is not None:
        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "0.0.0.0")
        )

    amp_user = str(ctts_user_id) if ctts_user_id else f"anon_{amp._hash_ip(ip)}"

    background_tasks.add_task(amp.track, "Бэкенд_стт_запрос_принят", {
        "размер_аудио_кб": round(len(audio_bytes) / 1024, 1),
        "авторизован": ctts_user_id is not None,
    }, amp_user)

    if ctts_user_id is None and request is not None:
        allowed, err_msg = await check_and_increment_rate_limit(ip, 50)
        if not allowed:
            background_tasks.add_task(amp.track, "Бэкенд_стт_лимит_превышен", {
                "сообщение": err_msg,
            }, amp_user)
            raise HTTPException(status_code=429, detail=err_msg)

    t0 = _time.monotonic()
    loop = asyncio.get_running_loop()
    try:
        transcript = await loop.run_in_executor(_executor, _stt_sync, audio_bytes, language)
    except Exception as e:
        err_str = str(e)
        background_tasks.add_task(amp.track, "Бэкенд_стт_ошибка", {
            "ошибка": err_str,
            "размер_аудио_кб": round(len(audio_bytes) / 1024, 1),
        }, amp_user)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    background_tasks.add_task(amp.track, "Бэкенд_стт_транскрипт_получен", {
        "длина_транскрипта": len(transcript),
        "время_мс": int((_time.monotonic() - t0) * 1000),
    }, amp_user)

    return {"transcript": transcript}
