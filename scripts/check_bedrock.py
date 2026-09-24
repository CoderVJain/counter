"""Prove Bedrock access with one cheap Nova Micro call.

Run it yourself; it reads credentials from your AWS profile or environment and
prints nothing sensitive:

    uv run --native-tls python -m scripts.check_bedrock
"""

import boto3
from dotenv import load_dotenv

from counter.config import settings
from counter.tls import use_system_certs


def main() -> None:
    load_dotenv()  # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY may live in .env
    use_system_certs()
    cfg = settings()
    region = cfg.aws_region

    who = boto3.client("sts", region_name=region).get_caller_identity()
    print(f"account {who['Account'][:4]}... in {region}, arn ends {who['Arn'][-24:]}")

    bedrock = boto3.client("bedrock-runtime", region_name=region)
    reply = bedrock.converse(
        modelId=cfg.bedrock_model_fast,
        messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}],
        inferenceConfig={"maxTokens": 10, "temperature": 0},
    )
    text = reply["output"]["message"]["content"][0]["text"].strip()
    usage = reply["usage"]
    print(f"{cfg.bedrock_model_fast} said: {text}")
    print(f"tokens in/out: {usage['inputTokens']}/{usage['outputTokens']}")


if __name__ == "__main__":
    main()
