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


def test_delete_rule_removes_it_and_clears_rule_applied_on_transactions(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)
    rule = Rule(match_type="contains", match_value="CHIPOTLE", category_id=category.id, priority=0)
    session.add(rule)
    session.commit()
    session.refresh(rule)
    txn = Transaction(
        account_id=account.id,
        posted_at=datetime(2026, 9, 1),
        payee="CHIPOTLE 1",
        amount_cents=-1200,
        category_id=category.id,
        rule_applied_id=rule.id,
    )
    session.add(txn)
    session.commit()
    session.refresh(txn)

    response = client.post(f"/rules/{rule.id}/delete", follow_redirects=False)
    assert response.status_code == 303

    assert session.get(Rule, rule.id) is None
    session.refresh(txn)
    assert txn.rule_applied_id is None
    # Category stays — only the "which rule categorized me" pointer is cleared.
    assert txn.category_id == category.id


def test_delete_rule_returns_404_for_unknown_id(client):
    response = client.post("/rules/99999/delete", follow_redirects=False)
    assert response.status_code == 404


def test_update_rule_changes_all_fields(session, client):
    first_cat = Category(name="Dining", monthly_limit_cents=10000)
    second_cat = Category(name="Groceries", monthly_limit_cents=50000)
    session.add(first_cat)
    session.add(second_cat)
    session.commit()
    session.refresh(first_cat)
    session.refresh(second_cat)
    rule = Rule(match_type="contains", match_value="CHIPOTLE", category_id=first_cat.id, priority=0)
    session.add(rule)
    session.commit()
    session.refresh(rule)

    response = client.post(
        f"/rules/{rule.id}",
        data={
            "source": "description",
            "match_type": "regex",
            "match_value": "^KROGER",
            "category_id": str(second_cat.id),
            "priority": "5",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    session.refresh(rule)
    assert rule.source == "description"
    assert rule.match_type == "regex"
    assert rule.match_value == "^KROGER"
    assert rule.category_id == second_cat.id
    assert rule.priority == 5


def test_create_rule_with_description_source(session, client):
    category = Category(name="Transfers", monthly_limit_cents=0)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        "/rules",
        data={
            "source": "description",
            "match_type": "equals",
            "match_value": "KEEP THE CHANGE TRANSFER",
            "category_id": str(category.id),
            "priority": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    rule = session.exec(select(Rule)).first()
    assert rule.source == "description"


def test_update_rule_returns_404_for_unknown_id(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(
        "/rules/99999",
        data={
            "match_type": "contains",
            "match_value": "FOO",
            "category_id": str(category.id),
            "priority": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 404
