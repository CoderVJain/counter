"""Turn a spoken payment day into a real date.

"kal", "Friday", "agle hafte" are lexical, so they are resolved here in code rather than by a
model, for the same reason units are: a due date decides when a shopkeeper chases a debt, and it
has to mean the same thing every time it is said.

Two decisions worth stating.

Everything is read as **forward-looking**. "kal" means both yesterday and tomorrow in Hindi, and
"parso" means both the day after tomorrow and the day before yesterday; the verb tense carries the
difference and we do not have it. A due date is a promise to pay, so it is always the future one.
A weekday already past this week means the next one, and saying today's own weekday means a week
out, because someone paying today would say "aaj".

Dates are computed in **shop time, not UTC**. At 23:30 in India the UTC date is already tomorrow,
so a UTC "today" would date every late-evening debt a day early.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SHOP_TZ = ZoneInfo("Asia/Kolkata")


class UnknownDate(Exception):
    """A day nobody said clearly. Carries the phrase so the caller can ask about it."""

    def __init__(self, spoken: str):
        self.spoken = spoken
        super().__init__(f"cannot read a date from {spoken!r}")


# Spoken day to days from today, read forwards.
RELATIVE_DAYS = {
    "aaj": 0, "today": 0, "abhi": 0, "now": 0,
    "kal": 1, "tomorrow": 1, "kl": 1,
    "parso": 2, "parson": 2, "parsoon": 2,
    "narso": 3,
}  # fmt: skip

# Phrases that only make sense as a whole, checked before single words.
RELATIVE_PHRASES = {
    # "agla hafte" is what the Sep 25 eval actually heard, and it cost a needless question.
    "agle hafte": 7, "agla hafte": 7, "next week": 7, "hafte baad": 7, "in a week": 7, "ek hafte baad": 7,
    "agle mahine": 30, "next month": 30, "mahine baad": 30,
    "do din baad": 2, "in two days": 2, "teen din baad": 3, "char din baad": 4,
    "das din baad": 10, "pandrah din baad": 15,
}  # fmt: skip

# Weekday names to Python's Monday-is-zero numbering.
WEEKDAYS = {
    "monday": 0, "somvar": 0, "somwar": 0,
    "tuesday": 1, "mangalvar": 1, "mangalwar": 1,
    "wednesday": 2, "budhvar": 2, "budhwar": 2,
    "thursday": 3, "guruvar": 3, "guruwar": 3, "brihaspativar": 3,
    "friday": 4, "shukravar": 4, "shukrawar": 4,
    "saturday": 5, "shanivar": 5, "shaniwar": 5,
    "sunday": 6, "ravivar": 6, "raviwar": 6, "itvar": 6, "itwar": 6,
}  # fmt: skip


def today() -> date:
    """Today in the shop's own timezone, never UTC."""
    return datetime.now(SHOP_TZ).date()


def _next_weekday(reference: date, weekday: int) -> date:
    """The next time that weekday comes round. Never today; today would have been said as aaj."""
    ahead = (weekday - reference.weekday()) % 7
    return reference + timedelta(days=ahead or 7)


def to_date(spoken: str, reference: date | None = None) -> date:
    """The date a spoken payment day means. Raises rather than guessing."""
    day = reference or today()
    key = " ".join(spoken.lower().split())
    if not key:
        raise UnknownDate(spoken)

    for phrase, offset in RELATIVE_PHRASES.items():
        if phrase in key:
            return day + timedelta(days=offset)

    if key in RELATIVE_DAYS:
        return day + timedelta(days=RELATIVE_DAYS[key])
    if key in WEEKDAYS:
        return _next_weekday(day, WEEKDAYS[key])

    for word in key.split():
        if word in RELATIVE_DAYS:
            return day + timedelta(days=RELATIVE_DAYS[word])
        if word in WEEKDAYS:
            return _next_weekday(day, WEEKDAYS[word])

    raise UnknownDate(spoken)


def spoken(when: date, reference: date | None = None) -> str:
    """How a shopkeeper would hear that date said back."""
    day = reference or today()
    delta = (when - day).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if 2 <= delta <= 6:
        return when.strftime("%A")
    return f"{when.day} {when.strftime('%b')}"  # %-d is glibc only and raises on Windows
