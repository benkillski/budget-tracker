import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from app.models import Rule, Transaction
from app.money import to_cents
from app.rules_engine import apply_rules


@dataclass
class RawTransaction:
    posted_at: datetime
    payee: str
    description: str
    amount_cents: int


class CSVImportError(ValueError):
    pass


def parse_csv(file_bytes: bytes) -> list[RawTransaction]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"Date", "Description", "Amount"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise CSVImportError(f"CSV must have columns: {', '.join(sorted(required))}")

    rows: list[RawTransaction] = []
    for line_number, row in enumerate(reader, start=2):
        try:
            posted_at = datetime.strptime(row["Date"].strip(), "%Y-%m-%d")
            amount_cents = to_cents(Decimal(row["Amount"].strip()))
        except (ValueError, InvalidOperation) as exc:
            raise CSVImportError(f"Row {line_number}: {exc}") from exc
        description = row["Description"].strip()
        rows.append(
            RawTransaction(
                posted_at=posted_at,
                payee=description,
                description=description,
                amount_cents=amount_cents,
            )
        )
    return rows


def _dedup_hash(account_id: int, raw: RawTransaction) -> str:
    key = f"{account_id}|{raw.posted_at.isoformat()}|{raw.payee}|{raw.amount_cents}"
    return hashlib.sha256(key.encode()).hexdigest()


def import_csv_transactions(session: Session, account_id: int, rows: list[RawTransaction]) -> int:
    rules = session.exec(select(Rule).order_by(Rule.priority)).all()
    inserted = 0
    for raw in rows:
        dedup_hash = _dedup_hash(account_id, raw)
        existing = session.exec(select(Transaction).where(Transaction.csv_dedup_hash == dedup_hash)).first()
        if existing is not None:
            continue
        matched_rule = apply_rules(raw.payee, rules, description=raw.description or "")
        session.add(
            Transaction(
                account_id=account_id,
                posted_at=raw.posted_at,
                payee=raw.payee,
                description=raw.description or None,
                amount_cents=raw.amount_cents,
                category_id=matched_rule.category_id if matched_rule else None,
                rule_applied_id=matched_rule.id if matched_rule else None,
                import_source="csv",
                csv_dedup_hash=dedup_hash,
            )
        )
        inserted += 1
    session.commit()
    return inserted
