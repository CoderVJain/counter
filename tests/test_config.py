"""Settings load without a .env present."""

from counter.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.aws_region == "us-east-1"
    assert s.llm_provider == "bedrock"


def test_the_mcp_url_is_an_address_not_a_name():
    """ "localhost" tries ::1 first on Windows and costs about 1.2 seconds on every connection."""
    assert "localhost" not in Settings(_env_file=None).counter_mcp_url
