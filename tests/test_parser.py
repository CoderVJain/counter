"""What was heard becomes real rows and real money, or a question. Never a guess."""

from datetime import timedelta

import pytest

from counter.agent import parser
from counter.agent.parser import HeardLine, HeardSale
from counter.domain import dates
from counter.domain.models import Customer, Item


@pytest.fixture
def shop(db):
    db.add_all(
        [
            Item(
                name="sugar",
                aliases=["cheeni"],
                unit="kg",
                base_unit="g",
                base_per_unit=1000,
                price_paise=4500,
            ),
            Item(
                name="toned milk",
                aliases=["doodh"],
                unit="litre",
                base_unit="ml",
                base_per_unit=1000,
                price_paise=6000,
            ),
            Item(
                name="bread",
                aliases=["double roti"],
                unit="packet",
                base_unit="piece",
                base_per_unit=1,
                price_paise=4500,
            ),
            Item(
                name="mustard oil",
                aliases=["sarson ka tel"],
                unit="litre",
                base_unit="ml",
                base_per_unit=1000,
                price_paise=18000,
            ),
            Item(
                name="refined oil",
                aliases=["cooking oil"],
                unit="litre",
                base_unit="ml",
                base_per_unit=1000,
                price_paise=15500,
            ),
            Customer(name="Sharma ji", nicknames=["sharmaji"]),
        ]
    )
    db.commit()
    return db


@pytest.fixture(autouse=True)
def clean_cache():
    """The parse cache outlives a test, so one test's scripted answer must not reach the next."""
    parser._heard_cache.clear()
    yield
    parser._heard_cache.clear()


def heard(**kw) -> HeardSale:
    kw.setdefault("lines", [HeardLine(item="cheeni", qty="2", unit="kilo")])
    return HeardSale(**kw)


def test_a_cash_sale_resolves_to_items_and_a_total(shop):
    sale = parser.resolve(shop, heard())
    assert sale.lines[0].item.name == "sugar"
    assert sale.lines[0].qty_base == 2000  # 2 kg in grams
    assert sale.total_paise == 9000  # 2 x Rs 45
    assert sale.customer is None


def test_a_hinglish_fraction_is_converted_by_code_not_the_model(shop):
    """ "dhai kilo cheeni" is 2.5 kg. units.py owns that, so the model may pass the word through."""
    sale = parser.resolve(shop, heard(lines=[HeardLine(item="cheeni", qty="dhai", unit="kilo")]))
    assert sale.lines[0].qty_base == 2500
    assert sale.total_paise == 11250


def test_several_items_are_totalled_in_code(shop):
    sale = parser.resolve(
        shop,
        heard(
            lines=[
                HeardLine(item="doodh", qty="2", unit="litre"),
                HeardLine(item="bread", qty="1"),
            ]
        ),
    )
    assert [line.item.name for line in sale.lines] == ["toned milk", "bread"]
    assert sale.total_paise == 12000 + 4500


def test_a_credit_sale_resolves_the_customer(shop):
    sale = parser.resolve(shop, heard(customer="sharmaji", is_credit=True, due_spoken="Friday"))
    assert sale.customer.name == "Sharma ji"
    assert sale.is_credit
    assert sale.due_spoken == "Friday"


def test_credit_without_a_named_person_is_a_question(shop):
    with pytest.raises(parser.NeedsClarification) as caught:
        parser.resolve(shop, heard(is_credit=True))
    assert "credit" in str(caught.value).lower()


def test_an_ambiguous_item_asks_which_one_and_offers_both(shop):
    with pytest.raises(parser.NeedsClarification) as caught:
        parser.resolve(shop, heard(lines=[HeardLine(item="oil", qty="1", unit="litre")]))
    assert caught.value.options == ["mustard oil", "refined oil"]


def test_an_unstocked_item_asks_rather_than_inventing_one(shop):
    with pytest.raises(parser.NeedsClarification):
        parser.resolve(shop, heard(lines=[HeardLine(item="chocolate", qty="1")]))


def test_the_wrong_kind_of_unit_asks_rather_than_recording(shop):
    """Litres of bread is not a sale, it is a mishearing."""
    with pytest.raises(parser.NeedsClarification):
        parser.resolve(shop, heard(lines=[HeardLine(item="bread", qty="1", unit="litre")]))


def test_an_unknown_customer_is_not_silently_created(shop):
    with pytest.raises(parser.NeedsClarification):
        parser.resolve(shop, heard(customer="Mehta ji", is_credit=True))


def test_a_sentence_with_no_items_records_nothing(shop):
    with pytest.raises(parser.NothingHeard):
        parser.resolve(shop, heard(lines=[]))


async def test_parse_sale_sends_the_utterance_as_data_not_instructions(shop, monkeypatch):
    """The utterance must arrive in the user turn; SYSTEM must carry the instructions."""
    seen = {}

    async def fake_parse(prompt, out, *, system=None, smart=False):
        seen["prompt"], seen["system"] = prompt, system
        return heard()

    monkeypatch.setattr(parser.llm, "parse", fake_parse)
    sale = await parser.parse_sale(shop, "2 kilo cheeni")
    assert seen["prompt"] == "2 kilo cheeni"
    assert seen["system"] is parser.SYSTEM
    assert sale.total_paise == 9000


def test_naming_a_payment_day_makes_it_credit_even_if_the_model_said_cash(shop):
    """ "he will pay Friday" is a debt. Code decides this, not the model's flag."""
    sale = parser.resolve(shop, heard(customer="sharmaji", is_credit=False, due_spoken="Friday"))
    assert sale.is_credit
    assert sale.customer.name == "Sharma ji"


def test_a_dozen_is_not_multiplied_twice(shop):
    """ "ek dozen" is qty 1 unit dozen. If the model ever sends qty 12, this is the 12x overcharge."""
    shop.add(
        Item(name="eggs", aliases=["ande"], unit="piece", base_unit="piece", base_per_unit=1, price_paise=700)
    )
    shop.commit()
    sale = parser.resolve(shop, heard(lines=[HeardLine(item="ande", qty="ek", unit="dozen")]))
    assert sale.lines[0].qty_base == 12
    assert sale.total_paise == 8400


def test_a_spoken_payment_day_becomes_a_real_date(shop):
    sale = parser.resolve(shop, heard(customer="sharmaji", due_spoken="kal"))
    assert sale.due_date == dates.today() + timedelta(days=1)
    assert sale.is_credit


def test_a_cash_sale_has_no_due_date(shop):
    assert parser.resolve(shop, heard()).due_date is None


def test_an_unreadable_payment_day_asks_rather_than_guessing(shop):
    with pytest.raises(parser.NeedsClarification) as caught:
        parser.resolve(shop, heard(customer="sharmaji", due_spoken="sometime soon"))
    assert "when will they pay" in str(caught.value).lower()


async def test_the_same_sentence_is_only_sent_to_the_model_once(shop, monkeypatch):
    calls = []

    async def counted(prompt, out, *, system=None, smart=False):
        calls.append(prompt)
        return heard()

    parser._heard_cache.clear()
    monkeypatch.setattr(parser.llm, "parse", counted)
    await parser.parse_sale(shop, "2 kilo cheeni")
    await parser.parse_sale(shop, "  2  KILO   cheeni ")
    assert len(calls) == 1


async def test_the_cache_holds_what_was_heard_not_what_it_resolved_to(shop, monkeypatch):
    """A price change must show up immediately, so only the model's reading is remembered."""

    async def counted(prompt, out, *, system=None, smart=False):
        return heard()

    parser._heard_cache.clear()
    monkeypatch.setattr(parser.llm, "parse", counted)
    first = await parser.parse_sale(shop, "2 kilo cheeni")
    shop.query(Item).filter_by(name="sugar").one().price_paise = 5000
    shop.commit()
    second = await parser.parse_sale(shop, "2 kilo cheeni")
    assert first.total_paise == 9000
    assert second.total_paise == 10000


def test_a_quantity_the_model_dropped_is_read_from_the_sentence():
    """The measured failure: "do" comes back as "ek". The sentence says "do", so the code takes it."""
    said = "do kilo cheeni Sharma ji ko, kal dega"
    misheard = heard(lines=[HeardLine(item="cheeni", qty="ek", unit="kilo")])

    fixed = parser.recover_quantities(said, misheard)

    assert [line.qty for line in fixed.lines] == ["do"]
    parser.check_quantities(said, fixed)  # and the guard still passes, because "do" was spoken


def test_each_item_gets_the_number_next_to_it():
    said = "do doodh aur teen bread"
    misheard = heard(lines=[HeardLine(item="doodh", qty="ek"), HeardLine(item="bread", qty="ek")])

    fixed = parser.recover_quantities(said, misheard)

    assert [line.qty for line in fixed.lines] == ["do", "teen"]


def test_a_number_that_belongs_to_another_line_is_never_taken():
    """ "ek" is the bread's. The milk must be asked about, not handed the bread's number."""
    said = "doodh aur ek bread"
    misheard = heard(lines=[HeardLine(item="doodh", qty="paanch"), HeardLine(item="bread", qty="ek")])

    fixed = parser.recover_quantities(said, misheard)

    assert fixed.lines[0].qty == "paanch", "nothing in the sentence is the milk's, so leave it"
    with pytest.raises(parser.NeedsClarification):
        parser.check_quantities(said, fixed)


def test_a_quantity_the_model_copied_correctly_is_left_alone():
    said = "2 kilo cheeni aur 3 packet maggi"
    right = heard(
        lines=[
            HeardLine(item="cheeni", qty="2", unit="kilo"),
            HeardLine(item="maggi", qty="3", unit="packet"),
        ]
    )

    fixed = parser.recover_quantities(said, right)

    assert [line.qty for line in fixed.lines] == ["2", "3"]


def test_a_sentence_with_no_number_at_all_is_still_a_question():
    """Recovery never invents. A sentence that states no quantity must still be asked about."""
    said = "cheeni Sharma ji ko"
    misheard = heard(lines=[HeardLine(item="cheeni", qty="ek")])

    fixed = parser.recover_quantities(said, misheard)

    with pytest.raises(parser.NeedsClarification):
        parser.check_quantities(said, fixed)


def test_a_number_after_the_item_is_found_too():
    said = "cheeni 2 kilo"
    misheard = heard(lines=[HeardLine(item="cheeni", qty="ek", unit="kilo")])

    assert parser.recover_quantities(said, misheard).lines[0].qty == "2"


async def test_a_refused_hearing_is_not_remembered(shop, monkeypatch):
    """A hearing that failed its check can never become a sale, so it must not be kept.

    Keeping it made a miscopied quantity permanent: the shopkeeper repeating the same words got the
    same question back for the life of the process, with no way out but different words.
    """
    calls = []

    async def misheard(prompt, out, *, system=None, smart=False):
        calls.append(prompt)
        return heard(lines=[HeardLine(item="cheeni", qty="bees", unit="kilo")])

    parser._heard_cache.clear()
    monkeypatch.setattr(parser.llm, "parse", misheard)
    for _ in range(2):
        with pytest.raises(parser.NeedsClarification):
            await parser.parse_sale(shop, "cheeni Sharma ji ko")

    assert len(calls) == 2, "the second attempt must reach the model again"
    assert not parser._heard_cache
    parser._heard_cache.clear()


async def test_a_quantity_nobody_said_is_never_written(shop, monkeypatch):
    """Measured: "do kilo cheeni cash" came back as qty "bees". Twenty kilos must not leave a shelf.

    This used to be a question. Now the sentence itself supplies the answer - it says "do" - so the
    sale records two kilos. What the model claimed is still never written, which is the point.
    """

    async def misheard(prompt, out, *, system=None, smart=False):
        return heard(lines=[HeardLine(item="cheeni", qty="bees", unit="kilo")])

    parser._heard_cache.clear()
    monkeypatch.setattr(parser.llm, "parse", misheard)
    sale = await parser.parse_sale(shop, "do kilo cheeni cash")

    assert sale.lines[0].qty_base == 2000, "two kilos, as spoken - not twenty"
    parser._heard_cache.clear()


async def test_a_quantity_that_was_spoken_passes(shop, monkeypatch):
    async def faithful(prompt, out, *, system=None, smart=False):
        return heard(lines=[HeardLine(item="cheeni", qty="do", unit="kilo")])

    monkeypatch.setattr(parser.llm, "parse", faithful)
    sale = await parser.parse_sale(shop, "do kilo cheeni cash")
    assert sale.lines[0].qty_base == 2000


def test_the_spoken_check_reads_digits_stuck_to_a_unit():
    """ "2kg" is one token to a regex and two words to a shopkeeper."""
    parser.check_quantities("2kg cheeni", heard(lines=[HeardLine(item="cheeni", qty="2", unit="kg")]))


def test_the_spoken_check_ignores_case_and_spacing():
    parser.check_quantities("  DHAI  kilo  cheeni ", heard(lines=[HeardLine(item="cheeni", qty="dhai")]))


def test_the_spoken_check_allows_a_fraction():
    parser.check_quantities("2.5 kilo cheeni", heard(lines=[HeardLine(item="cheeni", qty="2.5")]))


async def test_two_lines_cannot_claim_one_spoken_quantity(shop, monkeypatch):
    """Measured: "do doodh aur ek bread" came back as qty "ek" twice, halving the milk."""

    async def misheard(prompt, out, *, system=None, smart=False):
        return heard(
            lines=[
                HeardLine(item="cheeni", qty="ek", unit="kilo"),
                HeardLine(item="bread", qty="ek", unit="piece"),
            ]
        )

    monkeypatch.setattr(parser.llm, "parse", misheard)
    with pytest.raises(parser.NeedsClarification):
        await parser.parse_sale(shop, "do cheeni aur ek bread")


def test_a_word_said_twice_covers_two_lines():
    """ "do kilo cheeni aur do kilo chawal" is two real twos, and must not be questioned."""
    parser.check_quantities(
        "do kilo cheeni aur do kilo chawal",
        heard(
            lines=[
                HeardLine(item="cheeni", qty="do", unit="kilo"),
                HeardLine(item="chawal", qty="do", unit="kilo"),
            ]
        ),
    )


async def test_a_unit_nobody_said_is_ignored(shop, monkeypatch):
    """Measured: "das anda" came back with unit "dozen", turning ten eggs into a hundred and twenty."""
    shop.add(
        Item(name="eggs", aliases=["anda"], unit="piece", base_unit="piece", base_per_unit=1, price_paise=700)
    )
    shop.commit()

    async def misheard(prompt, out, *, system=None, smart=False):
        return heard(lines=[HeardLine(item="anda", qty="das", unit="dozen")])

    monkeypatch.setattr(parser.llm, "parse", misheard)
    sale = await parser.parse_sale(shop, "Verma bhai ko das anda")
    assert sale.lines[0].qty_base == 10


def test_a_spoken_dozen_is_still_a_dozen():
    """Dropping unspoken units must not drop a real one."""
    fixed = parser.drop_unspoken_units(
        "do dozen anda", heard(lines=[HeardLine(item="anda", qty="do", unit="dozen")])
    )
    assert fixed.lines[0].unit == "dozen"


def test_a_unit_said_in_another_form_is_kept():
    """ "500 g" and unit "gram" are the same unit, so nothing is dropped."""
    fixed = parser.drop_unspoken_units(
        "500 g cheeni", heard(lines=[HeardLine(item="cheeni", qty="500", unit="gram")])
    )
    assert fixed.lines[0].unit == "gram"


def test_dropping_a_unit_does_not_touch_the_cached_reading():
    """The original is what the cache holds, so it must come back unchanged."""
    original = heard(lines=[HeardLine(item="anda", qty="das", unit="dozen")])
    parser.drop_unspoken_units("das anda", original)
    assert original.lines[0].unit == "dozen"
