"""
Amplitude, отправка событий через HTTP API v2.
Все вызовы, fire-and-forget, ошибки не прерывают основной запрос.
Ported from hsk-tutor's backend/app/services/amplitude.py, unchanged.
"""
import hashlib
import logging
import time
import uuid

import httpx

logger = logging.getLogger(__name__)

_API_KEY = ""  # заполняется при первом вызове из settings
_URL = "https://api2.amplitude.com/2/httpapi"


def _key() -> str:
    global _API_KEY
    if not _API_KEY:
        try:
            from ..config import settings
            _API_KEY = getattr(settings, "AMPLITUDE_API_KEY", "") or ""
        except Exception:
            pass
    return _API_KEY


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


async def track(
    event_type: str,
    properties: dict | None = None,
    user_id: str = "anonymous_backend",
) -> None:
    key = _key()
    if not key:
        return
    payload = {
        "api_key": key,
        "events": [
            {
                "event_type": event_type,
                "user_id": user_id,
                "time": int(time.time() * 1000),
                "event_properties": properties or {},
                "insert_id": uuid.uuid4().hex,
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(_URL, json=payload)
            if r.status_code not in (200, 202):
                logger.debug("Amplitude вернул %s: %s", r.status_code, r.text[:200])
    except Exception as exc:
        logger.debug("Amplitude: ошибка отправки: %s", exc)


async def track_backend_error(
    endpoint: str,
    error: str,
    status_code: int,
    extra: dict | None = None,
) -> None:
    props = {
        "эндпоинт": endpoint,
        "ошибка": error,
        "код_статуса": status_code,
        **(extra or {}),
    }
    await track("бэкенд_ошибка", props)
