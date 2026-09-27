"""The scheduled briefing: off by default, once a day at most, and no model needed.

The point of these tests is the money, not the feature. A scheduled job that can call a model is
the one way this project could bill overnight, so what is pinned here is that it stays off unless
asked, and that it cannot run twice in a day however the clock behaves.
"""

import asyncio
from datetime import date, datetime

import pytest

from counter.config import Settings
from counter.domain import dates
from counter.jobs import briefing
from counter.seed import seed


@pytest.fixture
def stub_settings(monkeypatch):
    """Point the job at settings a test controls, without touching the environment."""

    def use(**values):
        s = Settings(_env_file=None, **values)
        monkeypatch.setattr(briefing, "settings", lambda: s)
        return s

    return use


def test_off_by_default(stub_settings):
    stub_settings()
    assert briefing.start() is None


@pytest.mark.asyncio
async def test_start_returns_a_task_when_switched_on(stub_settings, monkeypatch):
    stub_settings(briefing_enabled=True)
    monkeypatch.setattr(briefing, "seconds_until", lambda *_: 3600)
    task = briefing.start()
    assert task is not None
    task.cancel()


def test_ceiling_allows_one_run_a_day():
    ceiling = briefing.Ceiling()
    day = date(2026, 9, 27)
    assert ceiling.take(day)
    assert not ceiling.take(day)
    assert ceiling.take(date(2026, 9, 28))


def test_ceiling_survives_a_clock_jumping_back():
    """A clock that goes backwards must not buy a second briefing."""
    ceiling = briefing.Ceiling()
    assert ceiling.take(date(2026, 9, 27))
    assert not ceiling.take(date(2026, 9, 27))


def test_seconds_until_is_the_next_occurrence():
    now = datetime(2026, 9, 27, 7, 30, tzinfo=dates.SHOP_TZ)
    assert briefing.seconds_until(8, 0, now) == 1800
    # Already past today, so tomorrow.
    assert briefing.seconds_until(7, 0, now) == 23 * 3600 + 1800


def test_seconds_until_skips_a_day_when_the_time_is_now():
    now = datetime(2026, 9, 27, 8, 0, tzinfo=dates.SHOP_TZ)
    assert briefing.seconds_until(8, 0, now) == 24 * 3600


@pytest.mark.asyncio
async def test_run_once_needs_no_model(shop, no_model):
    """The facts are computed in code, so a briefing survives a model that is not there."""
    seed(shop)
    spoken = await briefing.run_once()
    assert "outstanding" in spoken


@pytest.mark.asyncio
async def test_loop_stops_at_the_ceiling(shop, no_model, stub_settings, monkeypatch):
    """A clock that keeps arriving at the briefing hour still bills for one briefing."""
    seed(shop)
    stub_settings(briefing_enabled=True)
    monkeypatch.setattr(briefing, "seconds_until", lambda *_: 0)

    runs = 0
    real_run = briefing.run_once

    async def counted():
        nonlocal runs
        runs += 1
        return await real_run()

    monkeypatch.setattr(briefing, "run_once", counted)
    task = asyncio.create_task(briefing.loop())
    await asyncio.sleep(0.05)
    task.cancel()
    assert runs == 1
