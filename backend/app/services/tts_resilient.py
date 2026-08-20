"""
Resilient TTS, iFLYTEK primary, Tencent fallback.

Call order:
  1. iFLYTEK attempt 1
  2. iFLYTEK attempt 2 (0.5 s pause)
  3. Tencent fallback (pre-bound tencent_fn)
  4. All failed → raise
"""

import logging
import time
from collections.abc import Callable

from ..config import settings
from .tts_iflytek import synthesize as _iflytek_synthesize

logger = logging.getLogger(__name__)

RETRY_DELAY = 0.5  # seconds between iFLYTEK retries


def _iflytek_ready() -> bool:
    return bool(
        settings.IFLYTEK_APPID
        and settings.IFLYTEK_API_KEY
        and settings.IFLYTEK_API_SECRET
    )


def _call_iflytek(text: str, rate: float, vcn: str) -> bytes:
    return _iflytek_synthesize(
        text=text,
        rate=rate,
        vcn=vcn,
        appid=settings.IFLYTEK_APPID,
        api_key=settings.IFLYTEK_API_KEY,
        api_secret=settings.IFLYTEK_API_SECRET,
    )


def synthesize_with_fallback(
    tencent_fn: Callable[[], bytes],
    text: str,
    rate: float,
    voice_name: str,
) -> tuple[bytes, str]:
    """
    Returns (audio_bytes, provider_name).
    Raises RuntimeError if all providers fail.
    tencent_fn: zero-arg callable already bound to text/rate/voice params.
    voice_name: iFLYTEK vcn (e.g. "x_xiaoyan").
    """
    iflytek = _iflytek_ready()
    last_iflytek_err: Exception | None = None

    # iFLYTEK primary (2 attempts)
    if iflytek:
        for attempt in range(1, 3):
            try:
                audio = _call_iflytek(text, rate, voice_name)
                logger.debug("[TTS] iFLYTEK OK (attempt %d)", attempt)
                return audio, "iflytek"
            except Exception as e:
                last_iflytek_err = e
                logger.warning("[TTS] iFLYTEK attempt %d failed: %s", attempt, e)
            if attempt < 2:
                time.sleep(RETRY_DELAY)

    # Tencent fallback
    try:
        audio = tencent_fn()
        logger.debug("[TTS] Tencent fallback OK")
        return audio, "tencent"
    except Exception as e:
        if last_iflytek_err:
            raise RuntimeError(
                f"All TTS providers failed. iFLYTEK: {last_iflytek_err}. Tencent: {e}"
            ) from e
        raise RuntimeError(f"TTS failed: {e}") from e
