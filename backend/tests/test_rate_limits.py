"""
DB-backed tests for the tiered rate-limit model: anonymous is IP-scoped at
DAILY_CHAR_LIMIT_ANON, authenticated is user-scoped at DAILY_CHAR_LIMIT_AUTH,
and the two budgets never leak into each other. Requires a real Postgres
(see conftest.py) - skipped automatically if unreachable.
"""
import pytest

from app.routers.ctts import (
    DAILY_CHAR_LIMIT_ANON,
    DAILY_CHAR_LIMIT_AUTH,
    DAILY_REQUEST_LIMIT,
    check_and_increment_rate_limit,
)


@pytest.mark.asyncio
async def test_anonymous_budget_allows_up_to_the_limit(clean_rate_limits):
    allowed, msg = await check_and_increment_rate_limit("1.2.3.4", DAILY_CHAR_LIMIT_ANON)
    assert allowed is True
    assert msg == ""


@pytest.mark.asyncio
async def test_anonymous_budget_blocks_over_the_limit(clean_rate_limits):
    allowed, msg = await check_and_increment_rate_limit("1.2.3.4", DAILY_CHAR_LIMIT_ANON + 1)
    assert allowed is False
    assert str(DAILY_CHAR_LIMIT_ANON) in msg
    assert "anonymous" in msg


@pytest.mark.asyncio
async def test_anonymous_budget_accumulates_across_requests(clean_rate_limits):
    ok1, _ = await check_and_increment_rate_limit("1.2.3.4", DAILY_CHAR_LIMIT_ANON - 10)
    ok2, msg2 = await check_and_increment_rate_limit("1.2.3.4", 20)  # pushes 10 over budget
    assert ok1 is True
    assert ok2 is False
    assert "10 remaining" in msg2


@pytest.mark.asyncio
async def test_authenticated_users_get_the_higher_budget(clean_rate_limits):
    over_anon_budget = DAILY_CHAR_LIMIT_ANON + 500
    assert over_anon_budget < DAILY_CHAR_LIMIT_AUTH, "test assumption: this fits in the auth budget"

    allowed, msg = await check_and_increment_rate_limit(
        "5.6.7.8", over_anon_budget, user_id=99
    )
    assert allowed is True, "an authenticated user should not be capped at the anonymous budget"
    assert msg == ""


@pytest.mark.asyncio
async def test_authenticated_budget_blocks_over_its_own_higher_limit(clean_rate_limits):
    allowed, msg = await check_and_increment_rate_limit(
        "5.6.7.8", DAILY_CHAR_LIMIT_AUTH + 1, user_id=99
    )
    assert allowed is False
    assert str(DAILY_CHAR_LIMIT_AUTH) in msg
    assert "signed-in" in msg
    # Authenticated users get no "sign in for more" hint - they're already signed in.
    assert "Sign in" not in msg


@pytest.mark.asyncio
async def test_anonymous_and_authenticated_budgets_are_independent(clean_rate_limits):
    """Same IP, but one request is anonymous and one is from a signed-in
    user on that IP - they must not share a budget."""
    ok_anon, _ = await check_and_increment_rate_limit("9.9.9.9", DAILY_CHAR_LIMIT_ANON)
    assert ok_anon is True

    # A signed-in user on the exact same IP should still get their own,
    # separate (and larger) budget rather than inheriting the exhausted
    # anonymous one.
    ok_auth, msg = await check_and_increment_rate_limit("9.9.9.9", 500, user_id=7)
    assert ok_auth is True, f"authenticated budget wrongly shared the anonymous IP bucket: {msg}"


@pytest.mark.asyncio
async def test_two_different_users_do_not_share_a_budget(clean_rate_limits):
    ok1, _ = await check_and_increment_rate_limit("ignored", DAILY_CHAR_LIMIT_AUTH, user_id=1)
    ok2, msg2 = await check_and_increment_rate_limit("ignored", 100, user_id=2)
    assert ok1 is True
    assert ok2 is True, f"user 2's budget was wrongly shared with user 1: {msg2}"


@pytest.mark.asyncio
async def test_request_count_limit_is_enforced_independently_of_char_budget(clean_rate_limits):
    # Send DAILY_REQUEST_LIMIT tiny (1-char) requests - none individually
    # trip the char budget, but the request-count budget should still bite.
    for i in range(DAILY_REQUEST_LIMIT):
        allowed, _ = await check_and_increment_rate_limit("1.1.1.1", 1)
        assert allowed is True, f"request {i + 1}/{DAILY_REQUEST_LIMIT} unexpectedly blocked"

    allowed, msg = await check_and_increment_rate_limit("1.1.1.1", 1)
    assert allowed is False
    assert str(DAILY_REQUEST_LIMIT) in msg
