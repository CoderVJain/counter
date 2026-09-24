"""The schema builds and the base-unit convention round-trips."""

from counter.domain.models import Item, StockMovement


def test_schema_creates_and_stores_base_units(db):
    sugar = Item(
        name="sugar",
        aliases=["cheeni", "shakkar"],
        unit="kg",
        base_unit="g",
        base_per_unit=1000,
        price_paise=4500,
        reorder_level_base=2000,
    )
    db.add(sugar)
    db.flush()

    db.add(StockMovement(item_id=sugar.id, delta_base=10_000, reason="opening"))
    db.add(StockMovement(item_id=sugar.id, delta_base=-2_000, reason="sale"))
    db.commit()

    moves = db.query(StockMovement).all()
    assert sum(m.delta_base for m in moves) == 8_000
    assert db.query(Item).one().aliases == ["cheeni", "shakkar"]
