"""Trust the operating system's certificate store for outbound TLS.

Machines running TLS-inspecting antivirus or a corporate proxy serve re-signed
certificates whose CA sits in the Windows trust store but not in the certifi
bundle that botocore uses. Entrypoints call use_system_certs() before creating
any AWS client. On machines without interception this is a no-op in effect.
"""

import os
import ssl
from pathlib import Path

BUNDLE = Path(".cache/system-ca.pem")


def _write_bundle() -> Path | None:
    """Dump the Windows root store to a PEM file. None if unavailable."""
    if not hasattr(ssl, "enum_certificates"):
        return None
    server_auth = ssl.Purpose.SERVER_AUTH.oid
    pems = [
        ssl.DER_cert_to_PEM_cert(der)
        for store in ("ROOT", "CA")
        for der, _enc, trust in ssl.enum_certificates(store)
        if trust is True or (trust is not False and server_auth in trust)
    ]
    if not pems:
        return None
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE.write_text("".join(pems), encoding="ascii")
    return BUNDLE


def use_system_certs() -> None:
    """Point botocore and httpx at the OS trust store via the standard env vars."""
    if os.environ.get("AWS_CA_BUNDLE"):
        return
    bundle = _write_bundle()
    if bundle:
        os.environ["AWS_CA_BUNDLE"] = str(bundle.resolve())
        os.environ.setdefault("SSL_CERT_FILE", str(bundle.resolve()))
