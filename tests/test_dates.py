"""Spoken payment days become real dates, read forwards, in shop time."""

from datetime import date, timedelta

import pytest

from counter.domain import dates

# A Thursday, so "Friday" is tomorrow and "Wednesday" is nearly a week out.
THURSDAY = date(2026, 10, 8)


def test_today_and_tomorrow():
    assert dates.to_date("aaj", THURSDAY) == THURSDAY
    assert dates.to_date("kal", THURSDAY) == date(2026, 10, 9)
    assert dates.to_date("tomorrow", THURSDAY) == date(2026, 10, 9)


def test_kal_is_read_forwards_because_a_due_date_is_a_promise():
    """ "kal" is both yesterday and tomorrow in Hindi. A debt is never due in the past."""
    assert dates.to_date("kal", THURSDAY) > THURSDAY


def test_parso_is_the_day_after_tomorrow():
    assert dates.to_date("parso", THURSDAY) == date(2026, 10, 10)


def test_a_weekday_still_to_come_this_week():
    assert dates.to_date("Friday", THURSDAY) == date(2026, 10, 9)


def test_a_weekday_already_past_means_next_week():
    assert dates.to_date("Monday", THURSDAY) == date(2026, 10, 12)


def test_todays_own_weekday_means_a_week_out():
    """Someone paying today would say aaj, so "Thursday" on a Thursday means the next one."""
    assert dates.to_date("Thursday", THURSDAY) == THURSDAY + timedelta(days=7)


def test_hindi_weekday_names_work():
    assert dates.to_date("shukravar", THURSDAY) == date(2026, 10, 9)
    assert dates.to_date("somvar", THURSDAY) == date(2026, 10, 12)


def test_a_phrase_wins_over_a_bare_word_inside_it():
    """ "ek hafte baad" must not be read as some stray single word."""
    assert dates.to_date("ek hafte baad", THURSDAY) == THURSDAY + timedelta(days=7)
    assert dates.to_date("agle hafte", THURSDAY) == THURSDAY + timedelta(days=7)


def test_extra_words_around_the_day_do_not_matter():
    assert dates.to_date("kal dega", THURSDAY) == date(2026, 10, 9)
    assert dates.to_date("next Friday", THURSDAY) == date(2026, 10, 9)


def test_a_day_nobody_said_is_refused():
    with pytest.raises(dates.UnknownDate):
        dates.to_date("sometime", THURSDAY)
    with pytest.raises(dates.UnknownDate):
        dates.to_date("   ", THURSDAY)


def test_today_uses_shop_time_not_utc():
    """At 23:30 in India the UTC date is already tomorrow; a UTC today would misdate debts."""
    assert dates.today() == dates.datetime.now(dates.SHOP_TZ).date()


def test_dates_are_said_back_the_way_they_were_heard():
    assert dates.spoken(THURSDAY, THURSDAY) == "today"
    assert dates.spoken(date(2026, 10, 9), THURSDAY) == "tomorrow"
    assert dates.spoken(date(2026, 10, 12), THURSDAY) == "Monday"
    assert dates.spoken(date(2026, 11, 3), THURSDAY) == "3 Nov"


def test_both_spellings_of_next_week_are_read():
    """The Sep 25 eval said 'agla hafte' and was asked a needless question for it."""
    assert dates.to_date("agla hafte", THURSDAY) == THURSDAY + timedelta(days=7)
