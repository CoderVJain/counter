"""Convert between what a shopkeeper says and what the database stores.

The database holds integer base units (g, ml, piece) and integer paise. This
module is the only place that turns "dhai kilo" into 2500 and 2500 back into
"2.5 kg". Conversion is lexical and deterministic, so it lives in code rather
than in a prompt.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from counter.domain.models import Item


class UnknownUnit(Exception):
    """A unit nobody in the shop uses."""


class ImpossibleAmount(Exception):
    """A sum of money no shopkeeper would say. Refused rather than written to a ledger."""

    def __init__(self, spoken: str):
        self.spoken = spoken
        super().__init__(f"{spoken} is not a payment this shop takes")


class UnitMismatch(Exception):
    """A unit that does not measure this item, such as litres of sugar."""

    def __init__(self, item: Item, unit: str):
        self.item = item
        self.unit = unit
        super().__init__(f"cannot measure {item.name} in {unit}")


# Spoken forms to canonical unit.
UNIT_ALIASES = {
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg", "kilo gram": "kg",
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "gms": "g",
    "l": "litre", "litre": "litre", "litres": "litre", "liter": "litre", "liters": "litre",
    "ml": "ml", "millilitre": "ml", "millilitres": "ml",
    "packet": "packet", "packets": "packet", "pkt": "packet", "pack": "packet",
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "dozen": "dozen", "dozens": "dozen",
}  # fmt: skip

# Canonical unit to (base unit, how many base units it is worth).
BASE_FACTORS = {
    "kg": ("g", 1000),
    "g": ("g", 1),
    "litre": ("ml", 1000),
    "ml": ("ml", 1),
    "dozen": ("piece", 12),
    "piece": ("piece", 1),
    "packet": ("piece", 1),
}

# Spoken quantities that carry a fixed value, fractions and whole numbers alike.
#
# The whole numbers were originally left to the parser, on the assumption that a model asked for
# digits would return digits. Measured on Sep 25 it does not: the same sentence returned qty "ek"
# on one run and "1" on the next two, at temperature zero. A quantity decides what a customer is
# charged, so it is resolved here where the answer is the same every time.
QUANTITY_WORDS = {
    "aadha": Decimal("0.5"), "adha": Decimal("0.5"), "half": Decimal("0.5"),
    "pav": Decimal("0.25"), "quarter": Decimal("0.25"),
    "dedh": Decimal("1.5"), "derh": Decimal("1.5"),
    "dhai": Decimal("2.5"), "dhaai": Decimal("2.5"),
    "sawa": Decimal("1.25"),
    "ek": Decimal(1), "do": Decimal(2), "teen": Decimal(3), "char": Decimal(4),
    "chaar": Decimal(4), "paanch": Decimal(5), "panch": Decimal(5), "chhe": Decimal(6),
    "che": Decimal(6), "chah": Decimal(6), "saat": Decimal(7), "aath": Decimal(8),
    "nau": Decimal(9), "das": Decimal(10), "dus": Decimal(10), "gyarah": Decimal(11), "barah": Decimal(12),
    "terah": Decimal(13), "chaudah": Decimal(14), "pandrah": Decimal(15), "solah": Decimal(16),
    "satrah": Decimal(17), "atharah": Decimal(18), "unnees": Decimal(19),
    # "bees" (20) and "bais" (22) sound nearly alike. Both are listed so a model that only has to
    # copy the word cannot turn one into the other; it returned 22 for "bees" in the Sep 25 eval.
    "bees": Decimal(20), "ikkis": Decimal(21), "bais": Decimal(22), "teis": Decimal(23),
    "chaubis": Decimal(24), "pachees": Decimal(25), "tees": Decimal(30), "chalees": Decimal(40),
    # "saath" (60) is deliberately absent: it differs from "saat" (7) by one aspirated consonant,
    # 60 is rare at a counter, and being asked beats recording eight times the quantity.
    "pachas": Decimal(50), "pachaas": Decimal(50), "sattar": Decimal(70), "assi": Decimal(80),
    "nabbe": Decimal(90), "sau": Decimal(100),
}  # fmt: skip


def canonical_unit(spoken: str) -> str:
    """Map a spoken unit onto a canonical one."""
    key = spoken.strip().lower()
    if key not in UNIT_ALIASES:
        raise UnknownUnit(spoken)
    return UNIT_ALIASES[key]


def quantity_value(spoken: str) -> Decimal:
    """Turn a spoken quantity into a number, understanding aadha, pav, dhai."""
    key = spoken.strip().lower()
    if key in QUANTITY_WORDS:
        return QUANTITY_WORDS[key]
    try:
        return Decimal(key)
    except Exception as exc:
        raise UnknownUnit(spoken) from exc


def to_base(item: Item, qty: Decimal | int | str, unit: str | None = None) -> int:
    """Quantity in the item's base units. `unit` defaults to how the item is sold."""
    amount = qty if isinstance(qty, Decimal) else quantity_value(str(qty))
    canonical = canonical_unit(unit) if unit else item.unit

    if canonical == item.unit:
        base_unit, factor = item.base_unit, item.base_per_unit
    else:
        base_unit, factor = BASE_FACTORS[canonical]

    if base_unit != item.base_unit:
        raise UnitMismatch(item, canonical)

    return int((amount * factor).to_integral_value(rounding=ROUND_HALF_UP))


def from_base(item: Item, qty_base: int) -> str:
    """Speakable quantity, in the unit the shop sells the item in."""
    if item.base_per_unit == 1:
        noun = item.unit if qty_base == 1 else f"{item.unit}s"
        return f"{qty_base} {noun}"

    # normalize() turns a round number into an exponent - Decimal("10") becomes 1E+1 - so a whole
    # amount is spoken as an int. "1E+1 kg sugar" is not a sentence anyone should hear.
    amount = (Decimal(qty_base) / item.base_per_unit).normalize()
    if amount == amount.to_integral_value():
        return f"{int(amount)} {item.unit}"
    return f"{amount} {item.unit}"


def line_total_paise(item: Item, qty_base: int) -> int:
    """What that quantity costs, rounded half-up to the paisa."""
    total = Decimal(qty_base) * item.price_paise / item.base_per_unit
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))


# A shop payment. The cap is not about arithmetic: it is the line past which a misheard figure is
# more likely than a real one, and a ledger is easier to protect than to correct.
MAX_RUPEES = Decimal("100000")


def to_paise(amount: Decimal | int | float | str) -> int:
    """Rupees as spoken into paise as stored. The only place that conversion happens.

    A payment must be a positive, plausible sum. Zero, a negative and a fat-fingered lakh are all
    refused here, so nothing downstream has to wonder whether an amount is real.
    """
    try:
        value = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ImpossibleAmount(str(amount)) from exc
    if not value.is_finite() or value <= 0 or value > MAX_RUPEES:
        raise ImpossibleAmount(str(amount))
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def rupees(paise: int) -> str:
    """Money as a shopkeeper would say it."""
    amount = Decimal(paise) / 100
    if amount == amount.to_integral_value():
        return f"Rs {int(amount)}"
    return f"Rs {amount.quantize(Decimal('0.01'))}"
