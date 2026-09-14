import pytest
from sqlmodel import select

from app.csv_import import CSVImportError, import_csv_transactions, parse_csv
from app.models import Account, Category, Rule, Transaction

CSV_TEXT = (
    "Date,Description,Amount\n"
    "2026-09-01,KROGER #123,-25.99\n"
    "2026-09-02,Paycheck,1500.00\n"
)


def test_parse_csv_returns_raw_transactions():
    rows = parse_csv(CSV_TEXT.encode())

    assert len(rows) == 2
    assert rows[0].payee == "KROGER #123"
    assert rows[0].amount_cents == -2599
    assert rows[1].amount_cents == 150000


def test_parse_csv_raises_on_missing_columns():
    with pytest.raises(CSVImportError):
        parse_csv(b"Date,Amount\n2026-09-01,-10.00\n")


def test_parse_csv_raises_on_malformed_row():
    with pytest.raises(CSVImportError):
        parse_csv(b"Date,Description,Amount\nnot-a-date,Store,-10.00\n")


def test_import_csv_transactions_applies_rules_and_dedupes(session):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Groceries", monthly_limit_cents=10000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)
    session.add(Rule(match_type="contains", match_value="KROGER", category_id=category.id, priority=0))
    session.commit()

    rows = parse_csv(CSV_TEXT.encode())

    first_count = import_csv_transactions(session, account.id, rows)
    second_count = import_csv_transactions(session, account.id, rows)

    assert first_count == 2
    assert second_count == 0

    kroger_txn = session.exec(
        select(Transaction).where(Transaction.payee == "KROGER #123")
    ).first()
    assert kroger_txn.category_id == category.id
    assert kroger_txn.import_source == "csv"
