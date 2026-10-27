from datetime import datetime
from typing import Optional

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    simplefin_account_id: str = Field(unique=True, index=True)
    name: str
    institution: str
    account_type: str = Field(default="unknown")
    balance_cents: int = Field(default=0)
    balance_date: Optional[NaiveDatetime] = None


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="category.id")
    monthly_limit_cents: int = Field(default=0)


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_type: str  # "contains" | "equals" | "regex"
    match_value: str
    category_id: int = Field(foreign_key="category.id")
    priority: int = Field(default=0, index=True)


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    simplefin_transaction_id: Optional[str] = Field(default=None, unique=True, index=True)
    csv_dedup_hash: Optional[str] = Field(default=None, unique=True, index=True)
    account_id: int = Field(foreign_key="account.id", index=True)
    posted_at: NaiveDatetime
    payee: str
    description: Optional[str] = None
    amount_cents: int
    pending: bool = Field(default=False)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)
    rule_applied_id: Optional[int] = Field(default=None, foreign_key="rule.id")
    import_source: str = Field(default="simplefin")  # "simplefin" | "csv"


class AlertLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id")
    year: int
    month: int
    threshold_pct: int
    sent_at: NaiveDatetime


class SyncStatus(SQLModel, table=True):
    """Singleton row (id=1) tracking the outcome of the last sync attempt."""

    id: Optional[int] = Field(default=None, primary_key=True)
    last_synced_at: Optional[NaiveDatetime] = None
    last_sync_ok: bool = Field(default=True)
    last_error: Optional[str] = None