"""Hackathon eligibility guard: the SDK must speak MCP 2025-11-25 or later."""

from mcp_types import LATEST_PROTOCOL_VERSION

REQUIRED_VERSION = "2025-11-25"


def test_sdk_supports_required_protocol_version():
    assert LATEST_PROTOCOL_VERSION >= REQUIRED_VERSION
