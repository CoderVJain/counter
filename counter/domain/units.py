"""Convert between what a shopkeeper says and what the database stores.

The database holds integer base units (g, ml, piece) and integer paise. This
module is the only place that turns "dhai kilo" into 2500 and 2500 back into
"2.5 kg". Conversion is lexical and deterministic, so it lives in code rather
than in a prompt.
"""

from decimal import ROUND_HALF_UP, Decimal

from counter.domain.models import Item


class UnknownUnit(Exception):
    """A unit nobody in the shop uses."""


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

# Quantity words that carry a fixed value. Number words themselves come from
# the parser; these are the ones that are fractions rather than digits.
QUANTITY_WORDS = {
    "aadha": Decimal("0.5"), "adha": Decimal("0.5"), "half": Decimal("0.5"),
    "pav": Decimal("0.25"), "quarter": Decimal("0.25"),
    "dedh": Decimal("1.5"), "derh": Decimal("1.5"),
    "dhai": Decimal("2.5"), "dhaai": Decimal("2.5"),
    "sawa": Decimal("1.25"),
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

    amount = (Decimal(qty_base) / item.base_per_unit).normalize()
    if amount == amount.to_integral_value():
        amount = amount.to_integral_value()
    return f"{amount} {item.unit}"


def line_total_paise(item: Item, qty_base: int) -> int:
    """What that quantity costs, rounded half-up to the paisa."""
    total = Decimal(qty_base) * item.price_paise / item.base_per_unit
    return int(total.to_integral_value(rounding=ROUND_HALF_UP))


def rupees(paise: int) -> str:
    """Money as a shopkeeper would say it."""
    amount = Decimal(paise) / 100
    if amount == amount.to_integral_value():
        return f"Rs {int(amount)}"
    return f"Rs {amount.quantize(Decimal('0.01'))}"
