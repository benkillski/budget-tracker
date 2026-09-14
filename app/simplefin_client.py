from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass
class SimpleFINTransaction:
    id: str
    posted_at: datetime
    payee: str
    amount_cents: int
    pending: bool


@dataclass
class SimpleFINAccount:
    id: str
    name: str
    org_name: str
    balance_cents: int
    transactions: list[SimpleFINTransaction] = field(default_factory=list)


class SimpleFINClient:
    def __init__(self, access_url: str, http_client: httpx.Client | None = None):
        parts = urlsplit(access_url)
        netloc = parts.hostname or ""
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        self._base_url = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        self._auth = (parts.username or "", parts.password or "")
        self._client = http_client or httpx.Client(timeout=30.0)

    def get_accounts(self, start_date: datetime | None = None) -> list[SimpleFINAccount]:
        params = {}
        if start_date is not None:
            params["start-date"] = int(start_date.replace(tzinfo=timezone.utc).timestamp())
        response = self._client.get(f"{self._base_url}/accounts", params=params, auth=self._auth)
        response.raise_for_status()
        payload = response.json()
        return [_parse_account(raw) for raw in payload.get("accounts", [])]


def _parse_account(raw: dict) -> SimpleFINAccount:
    return SimpleFINAccount(
        id=raw["id"],
        name=raw["name"],
        org_name=raw.get("org", {}).get("name", ""),
        balance_cents=_to_cents(raw["balance"]),
        transactions=[_parse_transaction(t) for t in raw.get("transactions", [])],
    )


def _parse_transaction(raw: dict) -> SimpleFINTransaction:
    return SimpleFINTransaction(
        id=raw["id"],
        posted_at=datetime.fromtimestamp(raw["posted"], tz=timezone.utc).replace(tzinfo=None),
        payee=raw.get("payee") or raw.get("description", ""),
        amount_cents=_to_cents(raw["amount"]),
        pending=bool(raw.get("pending", False)),
    )


def _to_cents(amount_str: str) -> int:
    return int(Decimal(amount_str) * 100)
