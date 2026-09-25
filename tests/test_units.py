"""Spoken quantities in, speakable quantities out, with exact arithmetic."""

from decimal import Decimal

import pytest

from counter.domain import units
from counter.domain.models import Item

SUGAR = Item(name="sugar", aliases=[], unit="kg", base_unit="g", base_per_unit=1000, price_paise=4500)
MILK = Item(name="milk", aliases=[], unit="litre", base_unit="ml", base_per_unit=1000, price_paise=6000)
MAGGI = Item(name="maggi", aliases=[], unit="packet", base_unit="piece", base_per_unit=1, price_paise=1400)


def test_selling_unit_is_the_default():
    assert units.to_base(SUGAR, 2) == 2_000


def test_spoken_unit_overrides_the_default():
    assert units.to_base(SUGAR, 500, "gram") == 500
    assert units.to_base(SUGAR, 2, "kilo") == 2_000


def test_hinglish_quantity_words():
    assert units.to_base(SUGAR, "dhai") == 2_500
    assert units.to_base(SUGAR, "aadha") == 500
    assert units.to_base(SUGAR, "pav") == 250


def test_fractional_quantities_are_exact():
    # 0.1 kg is 100 g exactly; float arithmetic would give 100.00000000000001
    assert units.to_base(SUGAR, Decimal("0.1")) == 100


def test_dozen_converts_to_pieces():
    eggs = Item(name="egg", aliases=[], unit="piece", base_unit="piece", base_per_unit=1, price_paise=800)
    assert units.to_base(eggs, 2, "dozen") == 24


def test_wrong_kind_of_unit_is_refused():
    with pytest.raises(units.UnitMismatch):
        units.to_base(SUGAR, 2, "litre")


def test_unknown_unit_is_refused():
    with pytest.raises(units.UnknownUnit):
        units.to_base(SUGAR, 2, "bori")


def test_from_base_speaks_the_selling_unit():
    assert units.from_base(SUGAR, 7_500) == "7.5 kg"
    assert units.from_base(SUGAR, 2_000) == "2 kg"
    assert units.from_base(MILK, 500) == "0.5 litre"


def test_from_base_never_speaks_in_exponents():
    """A round amount normalises to 1E+1 unless it is forced back to an int."""
    assert units.from_base(SUGAR, 10_000) == "10 kg"
    assert units.from_base(SUGAR, 100_000) == "100 kg"


def test_from_base_pluralises_counted_items():
    assert units.from_base(MAGGI, 1) == "1 packet"
    assert units.from_base(MAGGI, 3) == "3 packets"


def test_line_total_is_priced_per_selling_unit():
    assert units.line_total_paise(SUGAR, 2_000) == 9_000  # 2 kg at Rs 45
    assert units.line_total_paise(SUGAR, 500) == 2_250  # 500 g
    assert units.line_total_paise(MAGGI, 3) == 4_200  # 3 packets at Rs 14


def test_line_total_rounds_half_up_to_the_paisa():
    odd = Item(name="odd", aliases=[], unit="kg", base_unit="g", base_per_unit=1000, price_paise=333)
    assert units.line_total_paise(odd, 5) == 2  # 1.665 paise rounds to 2


def test_money_is_spoken_plainly():
    assert units.rupees(4_500) == "Rs 45"
    assert units.rupees(4_550) == "Rs 45.50"


def test_spoken_whole_numbers_resolve_in_code():
    """The model returns "ek" or "1" unpredictably, so code must understand both."""
    assert units.quantity_value("ek") == 1
    assert units.quantity_value("do") == 2
    assert units.quantity_value("1") == 1
    assert units.to_base(SUGAR, "do", "kilo") == 2000


def test_a_spoken_number_and_its_digit_agree():
    assert units.to_base(SUGAR, "teen", "kilo") == units.to_base(SUGAR, "3", "kilo")


def test_twenty_and_twenty_two_are_distinct_words_not_a_conversion():
    """The model returned 22 for "bees" when it was asked to convert. Now it copies; code decides."""
    assert units.quantity_value("bees") == 20
    assert units.quantity_value("bais") == 22


def test_sixty_is_absent_because_it_sounds_like_seven():
    """ "saath" (60) against "saat" (7) is an eightfold error, so it is refused rather than guessed."""
    assert units.quantity_value("saat") == 7
    with pytest.raises(units.UnknownUnit):
        units.quantity_value("saath")


def test_to_paise_converts_what_a_shopkeeper_says():
    assert units.to_paise(500) == 50_000
    assert units.to_paise("12.50") == 1_250
    assert units.to_paise(0.05) == 5


def test_to_paise_rounds_half_up_to_the_paisa():
    assert units.to_paise("1.005") == 101


@pytest.mark.parametrize("amount", [0, -1, "-250", "1000000", "abhi", float("nan")])
def test_to_paise_refuses_an_amount_no_shop_would_take(amount):
    with pytest.raises(units.ImpossibleAmount):
        units.to_paise(amount)


def test_both_spellings_of_a_spoken_number_are_the_same_number():
    """dus and das, pachas and pachaas: one word, two transcriptions, one quantity."""
    assert units.quantity_value("dus") == units.quantity_value("das")
    assert units.quantity_value("pachaas") == units.quantity_value("pachas")
