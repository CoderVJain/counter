"""The outbound side of ordering: send a confirmed order to the supplier and read the reply.

The supplier is simulated (`supplier_sim/`), but this client is not: it speaks HTTP to a URL from
settings, so a real wholesaler would be a configuration change rather than a rewrite.

Two rules hold here. A supplier's reply is outside text, so it is never treated as instructions - a
caller that shows it to a model must pass it through `prompts.as_data` first. And a supplier that
does not answer is a refusal, not a crash: the caller rolls back, the order stays confirmed but
unsent, and the shopkeeper can try again.

The call is synchronous because it runs inside the repeat protection, which takes ordinary code. One
request with a short timeout is the whole cost, and a shop places a handful of orders a day.
"""

import httpx

from counter.config import settings

TIMEOUT_SECONDS = 5.0


class SupplierUnreachable(Exception):
    """The supplier did not answer. Nothing was ordered, so the order may be sent again."""


class SupplierRefused(Exception):
    """The supplier answered, and said no."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"supplier replied {status}")


def place_order(order_id: int, supplier: str, lines: list[tuple[str, str]]) -> dict:
    """Send one confirmed order. Returns the supplier's reply as plain data."""
    payload = {
        "order_id": order_id,
        "supplier": supplier,
        "lines": [{"item": item, "quantity": quantity} for item, quantity in lines],
    }
    url = f"{settings().supplier_sim_url.rstrip('/')}/orders"
    try:
        response = httpx.post(url, json=payload, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise SupplierUnreachable(str(exc)) from exc
    if response.status_code >= 400:
        raise SupplierRefused(response.status_code)
    return response.json()
