"""In-memory SQLite for tests: fast, isolated, no credentials."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from counter.domain.models import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = maker()
    yield s
    s.close()
