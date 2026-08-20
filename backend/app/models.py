"""
ORM models, used only so Base.metadata.create_all() can create these tables
on first boot - actual queries go through raw SQL (see routers/ctts.py,
services/audio_cache.py), matching how this schema was originally set up
inside hsk-tutor's monolith.
"""
from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .database import Base


class CTTSUser(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "ctts"}

    id = Column(Integer, primary_key=True)
    google_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255))
    name = Column(String(255))
    picture = Column(Text)
    created_at = Column(DateTime, default=func.now())

    history = relationship("TTSHistory", back_populates="user", order_by="TTSHistory.created_at.desc()")


class TTSHistory(Base):
    __tablename__ = "tts_history"
    __table_args__ = {"schema": "ctts"}

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("ctts.users.id", ondelete="CASCADE"), nullable=False)
    text_content = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    voice = Column(String(50), default="x_xiaoyan")
    rate = Column(Float, default=1.0)
    audio_url = Column(Text)
    created_at = Column(DateTime, default=func.now())

    user = relationship("CTTSUser", back_populates="history")


class TTSRateLimit(Base):
    __tablename__ = "rate_limits"
    __table_args__ = {"schema": "ctts"}

    ip = Column(String(64), primary_key=True)
    limit_date = Column(Date, primary_key=True, default=func.current_date())
    char_count = Column(Integer, default=0)
    request_count = Column(Integer, default=0)


class AudioCache(Base):
    """
    ctts.audio_cache - deliberately its own table, not a share of
    yihan.audio_cache (which hsk-tutor's internal lesson-audio TTS still
    uses). Keeps this service's data fully isolated to the `ctts` schema.
    Trade-off: the cache starts cold after cutover from the monolith -
    previously-cached phrases get re-synthesized once, then cache normally.
    """
    __tablename__ = "audio_cache"
    __table_args__ = {"schema": "ctts"}

    id = Column(Integer, primary_key=True)
    text_hash = Column(String(64), unique=True, nullable=False, index=True)
    text_content = Column(Text, nullable=False)
    voice_type = Column(Integer, default=200001)
    audio_url = Column(Text, nullable=False)
    hit_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=func.now())
    last_used_at = Column(DateTime, default=func.now())
