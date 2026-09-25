"""Resolve what a shopkeeper says onto catalog rows.

Aliases and nicknames are data, never prompt text. A model transcribes the sound it heard -
"cheeni", "sharmaji" - and this module decides which row that is, in code, against the database.
Keeping the decision here is what stops a confident model from inventing an item that does not
exist, and it is why check_stock and get_dues can reuse the same matching as record_sale.

Matching is deliberately shallow: exact on name or alias first, then a containment pass. Anything
that resolves to more than one row is refused rather than guessed, because the caller is expected
to ask a clarifying question instead. Fuzzy or phonetic matching is not attempted; a wrong silent
match on a ledger is worse than one more question.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from counter.domain.models import Customer, Item, Supplier


class UnknownItem(Exception):
    """Nothing in the catalog matches. Carries what was heard, so the caller can say it back."""

    def __init__(self, spoken: str):
        self.spoken = spoken
        super().__init__(f"no item matches {spoken!r}")


class AmbiguousItem(Exception):
    """Several items match. Carries them so the caller can ask which one was meant."""

    def __init__(self, spoken: str, candidates: list[Item]):
        self.spoken = spoken
        self.candidates = candidates
        names = ", ".join(i.name for i in candidates)
        super().__init__(f"{spoken!r} matches {names}")


class UnknownCustomer(Exception):
    """Nobody on the books matches. Carries what was heard."""

    def __init__(self, spoken: str):
        self.spoken = spoken
        super().__init__(f"no customer matches {spoken!r}")


class AmbiguousCustomer(Exception):
    """Several customers match. Carries them so the caller can ask which one was meant."""

    def __init__(self, spoken: str, candidates: list[Customer]):
        self.spoken = spoken
        self.candidates = candidates
        names = ", ".join(c.name for c in candidates)
        super().__init__(f"{spoken!r} matches {names}")


class UnknownSupplier(Exception):
    """No supplier on file matches. Carries what was heard."""

    def __init__(self, spoken: str):
        self.spoken = spoken
        super().__init__(f"no supplier matches {spoken!r}")


class AmbiguousSupplier(Exception):
    """Several suppliers match. Carries them so the caller can ask which one was meant."""

    def __init__(self, spoken: str, candidates: list[Supplier]):
        self.spoken = spoken
        self.candidates = candidates
        names = ", ".join(s.name for s in candidates)
        super().__init__(f"{spoken!r} matches {names}")


def _key(text: str) -> str:
    """Compare on lowercase words, so spacing and case never decide a match."""
    return " ".join(text.lower().split())


def _terms(row: Item | Customer | Supplier) -> list[str]:
    """Every spoken form this row answers to. Only a customer calls them nicknames."""
    extra = row.nicknames if isinstance(row, Customer) else row.aliases
    return [_key(row.name), *(_key(a) for a in extra)]


def _match(rows: list, spoken: str) -> list:
    """Exact matches if there are any, otherwise rows whose terms contain or sit inside the input."""
    key = _key(spoken)
    if not key:
        return []
    exact = [r for r in rows if key in _terms(r)]
    if exact:
        return exact
    return [r for r in rows if any(key in t or t in key for t in _terms(r))]


def find_item(db: Session, spoken: str) -> Item:
    """The one item that spoken names. Refuses rather than picking between candidates."""
    found = _match(list(db.execute(select(Item)).scalars()), spoken)
    if not found:
        raise UnknownItem(spoken)
    if len(found) > 1:
        raise AmbiguousItem(spoken, sorted(found, key=lambda i: i.name))
    return found[0]


def find_customer(db: Session, spoken: str) -> Customer:
    """The one customer that spoken names. Refuses rather than picking between candidates."""
    found = _match(list(db.execute(select(Customer)).scalars()), spoken)
    if not found:
        raise UnknownCustomer(spoken)
    if len(found) > 1:
        raise AmbiguousCustomer(spoken, sorted(found, key=lambda c: c.name))
    return found[0]


def find_supplier(db: Session, spoken: str) -> Supplier:
    """The one supplier that spoken names. Refuses rather than picking between candidates."""
    found = _match(list(db.execute(select(Supplier)).scalars()), spoken)
    if not found:
        raise UnknownSupplier(spoken)
    if len(found) > 1:
        raise AmbiguousSupplier(spoken, sorted(found, key=lambda s: s.name))
    return found[0]


def suppliers(db: Session) -> list[Supplier]:
    """Everyone the shop buys from, by name, so a caller can ask which one."""
    return sorted(db.execute(select(Supplier)).scalars(), key=lambda s: s.name)
