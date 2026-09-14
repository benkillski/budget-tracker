from datetime import datetime

from sqlmodel import select

from app.models import Account, Category, Rule, Transaction


def test_create_rule_then_list_shows_it(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        "/rules",
        data={"match_type": "contains", "match_value": "CHIPOTLE", "category_id": str(category.id), "priority": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    list_response = client.get("/rules")
    assert "CHIPOTLE" in list_response.text
    assert "Dining" in list_response.text


def test_create_rule_from_transaction_categorizes_it_and_adds_rule(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    transaction = Transaction(account_id=account.id, posted_at=datetime(2026, 9, 1), payee="CHIPOTLE 456",
                               amount_cents=-1200)
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    response = client.post(
        f"/rules/from-transaction/{transaction.id}",
        data={"category_id": str(category.id)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(transaction)
    assert transaction.category_id == category.id

    rules = session.exec(select(Rule)).all()
    assert any(r.match_value == "CHIPOTLE 456" for r in rules)
