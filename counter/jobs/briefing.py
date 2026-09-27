"""The morning briefing on a schedule: the one thing Counter does without being asked.

This is also the only code in the project that can spend Bedrock credit while nobody is watching,
so the limits come first and the schedule second:

- **Off unless `BRIEFING_ENABLED=true`.** A development server, a test run and a judge's checkout
  all leave it off, so the default costs nothing.
- **A hard ceiling of one run per shop day.** The sleep is computed from the clock, and a clock that
  jumps backwards - a laptop waking, a container's time syncing - would otherwise let the loop fire
  again and again. The ceiling makes that cost at most one briefing.
- **No retry.** `summarizer.say` degrades to the plain facts rather than raising, so a failed model
  call already has an answer and a second attempt would only buy a second bill.

Everything is asyncio. A scheduler library would add a dependency to sleep until eight in the
morning, which asyncio already does.

Nothing here logs a customer name or an amount. Counts only, the same rule the tools follow.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta

from counter.agent import summarizer
from counter.config import settings
from counter.domain import dates
from counter.domain.db import session
from counter.tools import summary

log = logging.getLogger(__name__)

DAILY_CEILING = 1


class Ceiling:
    """How many briefings today. Refuses past the ceiling, and forgets when the day turns over."""

    def __init__(self, per_day: int = DAILY_CEILING):
        self.per_day = per_day
        self._day: date | None = None
        self._runs = 0

    def take(self, day: date) -> bool:
        """Claim one run for that day, or return False when the day is already spent."""
        if day != self._day:
            self._day, self._runs = day, 0
        if self._runs >= self.per_day:
            return False
        self._runs += 1
        return True


def seconds_until(hour: int, minute: int, now: datetime | None = None) -> float:
    """Seconds from now to the next time that clock time comes round, in shop time."""
    moment = now or datetime.now(dates.SHOP_TZ)
    target = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= moment:
        target += timedelta(days=1)
    return (target - moment).total_seconds()


async def run_once() -> str:
    """Build today's briefing and phrase it. One model call at most, and it cannot raise."""
    with session() as db:
        briefing = summary.build_briefing(db)
    spoken = await summarizer.say(summary.briefing_facts(briefing))
    log.info(
        "morning briefing ran: %d running low, %d due today",
        len(briefing.low_stock),
        len(briefing.due_today),
    )
    return spoken


async def loop(ceiling: Ceiling | None = None) -> None:
    """Sleep until the briefing hour, brief, repeat. Cancelled by the server shutting down."""
    allowance = ceiling or Ceiling()
    config = settings()
    while True:
        await asyncio.sleep(seconds_until(config.briefing_hour, config.briefing_minute))
        if allowance.take(dates.today()):
            await run_once()
        else:
            log.info("morning briefing skipped: already ran today")


def start() -> asyncio.Task | None:
    """Start the loop if it is switched on. Returns the task so the caller can cancel it."""
    if not settings().briefing_enabled:
        return None
    log.info("morning briefing scheduled")
    return asyncio.create_task(loop(), name="morning-briefing")
