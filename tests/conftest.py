"""In-memory SQLite for tests: fast, isolated, no credentials."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from counter.agent import llm, parser
from counter.domain import db as db_module
from counter.domain.models import Base
from counter.server import create_app

BASE_URL = "http://localhost:8000"


@pytest.fixture
def db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    s = maker()
    yield s
    s.close()


@pytest.fixture
def shop(monkeypatch):
    """A database the server's own `session()` hands out, so tools run against it unchanged.

    StaticPool keeps one connection, which is what makes an in-memory database visible to the
    several short sessions a tool call opens and closes.
    """
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", maker)
    s = maker()
    yield s
    s.close()


@pytest.fixture
def connect(shop):
    """Open a real MCP client talking Streamable HTTP to our own app, over ASGI rather than a port.

    This is the whole path a judge exercises - handshake, tool listing, tool call - with no network
    and no credentials. Two details are not optional:

    - The lifespan is entered by hand, because ASGI transports do not run it and without it the MCP
      session manager never starts, so the endpoint answers nothing.
    - This is a factory the test enters itself, not an async fixture. A session manager lives in an
      anyio cancel scope, which must be closed by the task that opened it, and pytest-asyncio
      finalises an async fixture in a different task than it created it in.
    """

    @asynccontextmanager
    async def open_client(mode: str = "auto") -> AsyncIterator[Client]:
        app = create_app()
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url=BASE_URL) as http:
                streams = streamable_http_client(f"{BASE_URL}/mcp", http_client=http)
                async with Client(streams, mode=mode) as mcp:
                    yield mcp

    return open_client


@pytest.fixture
def no_model():
    """No model, on purpose. A test that needs one scripts what it hears.

    Reaching a provider from a test would cost money, need credentials and give a different answer
    each run. Spoken text degrades to the plain facts when a model is unavailable, which is the
    behaviour `summarizer.say` promises, so assertions here are on facts computed in code.

    The parse cache is emptied around each test, because it outlives one and would otherwise hand a
    later test the sentence an earlier one scripted.
    """

    async def refuse(*_args, **_kwargs):
        raise AssertionError("this test reached the model without scripting it")

    parser._heard_cache.clear()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(llm, "complete", refuse)
        patch.setattr(llm, "parse", refuse)
        yield
    parser._heard_cache.clear()
