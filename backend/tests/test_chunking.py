"""Pure unit tests for text-chunking - no DB, no network."""
from app.routers.voice import _TTS_CHUNK_LIMIT, _split_text_chunks


def test_short_text_is_a_single_chunk():
    assert _split_text_chunks("你好世界") == ["你好世界"]


def test_splits_on_sentence_boundary_when_possible():
    long_text = "你好。" * 200  # well over the 500-char limit, all clean sentence breaks
    chunks = _split_text_chunks(long_text, max_len=500)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 500
        # each chunk should end on a sentence boundary, not mid-sentence
        assert c.endswith("。")
    assert "".join(chunks) == long_text


def test_hard_cuts_when_no_punctuation_available():
    # a single unbroken run of characters longer than the limit, no punctuation at all
    text = "很" * 1200
    chunks = _split_text_chunks(text, max_len=500)
    assert len(chunks) == 3
    assert [len(c) for c in chunks] == [500, 500, 200]
    assert "".join(chunks) == text


def test_exactly_at_the_limit_is_one_chunk():
    text = "你" * _TTS_CHUNK_LIMIT
    assert _split_text_chunks(text) == [text]


def test_one_char_over_the_limit_splits():
    text = "你" * (_TTS_CHUNK_LIMIT + 1)
    chunks = _split_text_chunks(text)
    assert len(chunks) == 2


def test_empty_string():
    assert _split_text_chunks("") == [""]


def test_500k_ceiling_produces_the_expected_chunk_count():
    # sanity check for the new MAX_REQUEST_CHARS=500_000 ceiling: confirms
    # chunking a request right at the absolute limit stays well-behaved
    # (no pathological chunk count, no infinite loop) rather than just
    # trusting it in the abstract.
    text = "很" * 500_000
    chunks = _split_text_chunks(text, max_len=500)
    assert len(chunks) == 1000
    assert "".join(chunks) == text
