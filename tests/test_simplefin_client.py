from datetime import datetime, timezone

import httpx
import respx

from app.simplefin_client import SimpleFINClient

ACCESS_URL = "https://user:pass@bridge.example.com/simplefin"

FIXTURE_RESPONSE = {
    "accounts": [
        {
            "id": "acc-1",
            "name": "Everyday Checking",
            "org": {"name": "Test Bank"},
            "balance": "1234.56",
            "transactions": [
                {
                    "id": "txn-1",
                    "posted": 1757000000,
                    "payee": "KROGER #123",
                    "description": "KROGER #123 CINCINNATI OH",
                    "amount": "-25.99",
                    "pending": False,
                },
                {
                    "id": "txn-2",
                    "posted": 1757100000,
                    "description": "Pending charge",
                    "amount": "-10.00",
                    "pending": True,
                },
            ],
        }
    ]
}


@respx.mock
def test_get_accounts_parses_accounts_and_transactions():
    route = respx.get("https://bridge.example.com/simplefin/accounts").mock(
        return_value=httpx.Response(200, json=FIXTURE_RESPONSE)
    )
    client = SimpleFINClient(ACCESS_URL)

    accounts = client.get_accounts()

    assert route.called
    assert len(accounts) == 1
    account = accounts[0]
    assert account.id == "acc-1"
    assert account.name == "Everyday Checking"
    assert account.org_name == "Test Bank"
    assert account.balance_cents == 123456
    assert len(account.transactions) == 2

    first, second = account.transactions
    assert first.id == "txn-1"
    assert first.payee == "KROGER #123"
    assert first.description == "KROGER #123 CINCINNATI OH"
    assert first.amount_cents == -2599
    assert first.pending is False

    assert second.payee == "Pending charge"
    assert second.description == "Pending charge"
    assert second.pending is True


@respx.mock
def test_get_accounts_sends_basic_auth_from_url():
    route = respx.get("https://bridge.example.com/simplefin/accounts").mock(
        return_value=httpx.Response(200, json={"accounts": []})
    )
    client = SimpleFINClient(ACCESS_URL)

    client.get_accounts()

    request = route.calls.last.request
    assert request.headers["authorization"].startswith("Basic ")


@respx.mock
def test_get_accounts_passes_start_date_as_epoch_seconds():
    route = respx.get("https://bridge.example.com/simplefin/accounts").mock(
        return_value=httpx.Response(200, json={"accounts": []})
    )
    client = SimpleFINClient(ACCESS_URL)

    client.get_accounts(start_date=datetime(2026, 1, 1, tzinfo=timezone.utc))

    request = route.calls.last.request
    assert request.url.params["start-date"] == "1767225600"
