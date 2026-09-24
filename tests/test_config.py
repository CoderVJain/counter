"""Settings load without a .env present."""

from counter.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.aws_region == "us-east-1"
    assert s.llm_provider == "bedrock"
