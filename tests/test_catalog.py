"""What the shopkeeper says resolves to one catalog row, or to a refusal that names the choices."""

import pytest

from counter.domain import catalog
from counter.domain.models import Customer, Item, Supplier


@pytest.fixture
def shop(db):
    db.add_all(
        [
            Item(
                name="sugar",
                aliases=["cheeni", "shakkar"],
                unit="kg",
                base_unit="g",
                base_per_unit=1000,
                price_paise=4500,
            ),
            Item(
                name="toor dal",
                aliases=["arhar dal", "dal"],
                unit="kg",
                base_unit="g",
                base_per_unit=1000,
                price_paise=14000,
            ),
            Item(
                name="moong dal",
                aliases=["moong"],
                unit="kg",
                base_unit="g",
                base_per_unit=1000,
                price_paise=12500,
            ),
            Item(
                name="toned milk",
                aliases=["doodh", "milk"],
                unit="litre",
                base_unit="ml",
                base_per_unit=1000,
                price_paise=6000,
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
            Customer(name="Sharma ji", nicknames=["sharma", "sharmaji"]),
            Customer(name="Sunita ji", nicknames=["sunita"]),
        ]
    )
    db.commit()
    return db


def test_an_alias_resolves_to_its_item(shop):
    assert catalog.find_item(shop, "cheeni").name == "sugar"


def test_the_name_itself_resolves(shop):
    assert catalog.find_item(shop, "toned milk").name == "toned milk"


def test_case_and_spacing_do_not_decide_a_match(shop):
    assert catalog.find_item(shop, "  ShaKKar ").name == "sugar"


def test_an_exact_alias_wins_over_a_containment_match(shop):
    """'dal' is an exact alias of toor dal, so it must not be called ambiguous with moong dal."""
    assert catalog.find_item(shop, "dal").name == "toor dal"


def test_a_word_matching_several_items_is_refused_with_the_candidates(shop):
    """ "ek litre oil" must produce a question, not a coin toss between two oils."""
    with pytest.raises(catalog.AmbiguousItem) as caught:
        catalog.find_item(shop, "oil")
    assert [i.name for i in caught.value.candidates] == ["mustard oil", "refined oil"]


def test_an_honorific_shared_by_two_customers_is_refused(shop):
    """ "ji" fits both, and crediting the wrong person is worse than asking."""
    with pytest.raises(catalog.AmbiguousCustomer) as caught:
        catalog.find_customer(shop, "ji")
    assert [c.name for c in caught.value.candidates] == ["Sharma ji", "Sunita ji"]


def test_an_unknown_item_is_refused_and_says_what_it_heard(shop):
    with pytest.raises(catalog.UnknownItem) as caught:
        catalog.find_item(shop, "chocolate")
    assert caught.value.spoken == "chocolate"


def test_an_empty_utterance_is_not_a_match(shop):
    with pytest.raises(catalog.UnknownItem):
        catalog.find_item(shop, "   ")


def test_a_nickname_resolves_to_its_customer(shop):
    assert catalog.find_customer(shop, "sharmaji").name == "Sharma ji"


def test_an_unknown_customer_is_refused(shop):
    with pytest.raises(catalog.UnknownCustomer):
        catalog.find_customer(shop, "Mehta ji")


def test_a_supplier_is_found_by_name_or_alias(db):
    db.add_all(
        [
            Supplier(name="Gupta Traders", aliases=["gupta"]),
            Supplier(name="Sharma Wholesale", aliases=[]),
        ]
    )
    db.flush()
    assert catalog.find_supplier(db, "gupta").name == "Gupta Traders"
    assert catalog.find_supplier(db, "Gupta Traders").name == "Gupta Traders"


def test_an_unknown_supplier_is_refused(db):
    db.add(Supplier(name="Gupta Traders", aliases=[]))
    db.flush()
    with pytest.raises(catalog.UnknownSupplier):
        catalog.find_supplier(db, "Metro Cash")


def test_two_matching_suppliers_are_handed_back_to_be_asked_about(db):
    db.add_all([Supplier(name="Gupta Traders", aliases=[]), Supplier(name="Gupta Sons", aliases=[])])
    db.flush()
    with pytest.raises(catalog.AmbiguousSupplier) as exc:
        catalog.find_supplier(db, "gupta")
    assert [s.name for s in exc.value.candidates] == ["Gupta Sons", "Gupta Traders"]
