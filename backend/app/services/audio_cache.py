"""
Audio cache service, PostgreSQL + Alibaba OSS.

Adapted from hsk-tutor's backend/app/services/audio_cache.py: points at
ctts.audio_cache instead of yihan.audio_cache, so this service owns its
own cache table instead of reaching into another schema. See models.py's
AudioCache docstring for why.

Flow:
  1. Hash(text + voice_type) → lookup in audio_cache table
  2. Hit  → update last_used_at + hit_count, return OSS URL
  3. Miss → call TTS (caller provides bytes), upload to OSS,
            insert row (evict LRU if > MAX_ROWS)
"""

import hashlib
import io
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_ROWS = 1000

# OSS helpers

def _oss_bucket():
    import oss2
    auth = oss2.Auth(
        os.environ.get("ALIBABA_ACCESS_KEY_ID", ""),
        os.environ.get("ALIBABA_ACCESS_KEY_SECRET", ""),
    )
    endpoint = os.environ.get("ALIBABA_OSS_ENDPOINT", "oss-ap-southeast-1.aliyuncs.com")
    bucket_name = os.environ.get("ALIBABA_BUCKET_NAME", "taobao-image-search-bucket")
    return oss2.Bucket(auth, f"https://{endpoint}", bucket_name), endpoint, bucket_name


def upload_to_oss(audio_bytes: bytes, object_key: str) -> str:
    """Upload MP3 bytes to OSS and return the public URL."""
    bucket, endpoint, bucket_name = _oss_bucket()
    bucket.put_object(object_key, io.BytesIO(audio_bytes), headers={"Content-Type": "audio/mpeg"})
    return f"https://{bucket_name}.{endpoint}/{object_key}"


# Cache helpers

def _make_hash(text_content: str, voice_type: int) -> str:
    return hashlib.sha256(f"{voice_type}:{text_content}".encode()).hexdigest()


async def get_cached_url(db: AsyncSession, text_content: str, voice_type: int = 200001) -> str | None:
    """Return cached OSS URL if exists, else None."""
    h = _make_hash(text_content, voice_type)
    row = await db.execute(
        text("SELECT id, audio_url FROM ctts.audio_cache WHERE text_hash = :h"),
        {"h": h},
    )
    row = row.fetchone()
    if row is None:
        return None
    await db.execute(
        text(
            "UPDATE ctts.audio_cache SET hit_count = hit_count + 1, last_used_at = now() "
            "WHERE text_hash = :h"
        ),
        {"h": h},
    )
    await db.commit()
    return row.audio_url


async def save_to_cache(
    db: AsyncSession,
    text_content: str,
    audio_bytes: bytes,
    voice_type: int = 200001,
) -> str:
    """Upload audio to OSS, save record to DB (evicting LRU if over limit). Returns URL."""
    h = _make_hash(text_content, voice_type)
    object_key = f"ctts-tts-cache/{h[:2]}/{h}.mp3"

    try:
        url = upload_to_oss(audio_bytes, object_key)
    except Exception as e:
        logger.warning(f"OSS upload failed: {e}")
        raise

    count_row = await db.execute(text("SELECT COUNT(*) FROM ctts.audio_cache"))
    count = count_row.scalar()
    if count >= MAX_ROWS:
        await db.execute(
            text(
                "DELETE FROM ctts.audio_cache WHERE id IN ("
                "  SELECT id FROM ctts.audio_cache ORDER BY last_used_at ASC LIMIT :n"
                ")"
            ),
            {"n": max(1, count - MAX_ROWS + 1)},
        )

    await db.execute(
        text(
            "INSERT INTO ctts.audio_cache (text_hash, text_content, voice_type, audio_url) "
            "VALUES (:h, :tc, :vt, :url) ON CONFLICT (text_hash) DO NOTHING"
        ),
        {"h": h, "tc": text_content[:2000], "vt": voice_type, "url": url},
    )
    await db.commit()
    return url
