import io

from sqlmodel import select

from app.models import Account, Transaction


def test_import_csv_via_form_upload(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    session.add(account)
    session.commit()
    session.refresh(account)

    csv_bytes = b"Date,Description,Amount\n2026-09-01,Coffee Shop,-4.50\n"

    response = client.post(
        "/import",
        data={"account_id": str(account.id)},
        files={"file": ("statement.csv", io.BytesIO(csv_bytes), "text/csv")},
    )

    assert response.status_code == 200
    assert "Imported 1 new transaction" in response.text

    imported = session.exec(select(Transaction)).first()
    assert imported.payee == "Coffee Shop"
    assert imported.import_source == "csv"
