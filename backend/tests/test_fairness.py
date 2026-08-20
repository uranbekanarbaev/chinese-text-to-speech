"""
Concurrency-fairness tests for _synthesize_chunked: a single request with
many chunks must never occupy more than _PER_REQUEST_CONCURRENCY worker
slots at once, so other users' requests can't be starved behind one huge
request (see voice.py's _PER_REQUEST_CONCURRENCY comment for the full
rationale - this test is what actually proves that comment true).
"""
import threading
import time

import pytest

from app.routers import voice


class _ConcurrencyTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def fake_synthesize(self, *, tencent_fn, text, rate, voice_name):
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)
        time.sleep(0.02)  # simulate real network latency to the TTS vendor
        with self.lock:
            self.current -= 1
        return b"fake-audio-bytes", "fake-provider"


@pytest.mark.asyncio
async def test_per_request_concurrency_is_bounded(monkeypatch):
    tracker = _ConcurrencyTracker()
    monkeypatch.setattr(voice, "synthesize_with_fallback", tracker.fake_synthesize)

    # 20 chunks worth of text (way more than _PER_REQUEST_CONCURRENCY) so
    # there's real opportunity for unbounded concurrency if the fairness
    # gate weren't there.
    text = "你好。" * (voice._TTS_CHUNK_LIMIT // 3) * 20
    chunks = voice._split_text_chunks(text, max_len=voice._TTS_CHUNK_LIMIT)
    assert len(chunks) >= 20, f"test setup should produce plenty of chunks, got {len(chunks)}"

    await voice._synthesize_chunked(text, rate=1.0, voice_name="x_xiaoyan", tencent_type=101001)

    assert tracker.peak <= voice._PER_REQUEST_CONCURRENCY, (
        f"one request used {tracker.peak} concurrent workers, "
        f"expected at most {voice._PER_REQUEST_CONCURRENCY}"
    )
    assert tracker.peak > 1, "fairness gate is real (>1) not accidentally serialized to 1"


@pytest.mark.asyncio
async def test_concatenation_preserves_chunk_order(monkeypatch):
    """Bounded concurrency must not scramble which audio bytes go where."""

    def fake_synthesize_ordered(*, tencent_fn, text, rate, voice_name):
        # return a byte-marker unique to this chunk's content so we can
        # verify the final concatenation matches the original chunk order,
        # not completion order (later chunks can finish before earlier ones).
        delay = 0.03 if text.startswith("A") else 0.005
        time.sleep(delay)
        return text.encode(), "fake-provider"

    monkeypatch.setattr(voice, "synthesize_with_fallback", fake_synthesize_ordered)

    text = "A" * voice._TTS_CHUNK_LIMIT + "B" * voice._TTS_CHUNK_LIMIT + "C" * 10
    audio, providers = await voice._synthesize_chunked(text, 1.0, "x_xiaoyan", 101001)

    assert audio == text.encode(), "chunk A (slow) must still come before B and C in the output"
    assert providers == "fake-provider"
