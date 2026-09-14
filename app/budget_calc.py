from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.models import Category, Transaction


@dataclass
class CategorySpend:
    category_id: int
    category_name: str
    limit_cents: int
    spent_cents: int

    @property
    def remaining_cents(self) -> int:
        return self.limit_cents - self.spent_cents

    @property
    def pct_used(self) -> float:
        if self.limit_cents <= 0:
            return 0.0
        return (self.spent_cents / self.limit_cents) * 100


def compute_budget_period(session: Session, year: int, month: int) -> list[CategorySpend]:
    start = datetime(year, month, 1)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59)

    categories = session.exec(select(Category)).all()
    results: list[CategorySpend] = []
    for category in categories:
        expenses = session.exec(
            select(Transaction).where(
                Transaction.category_id == category.id,
                Transaction.posted_at >= start,
                Transaction.posted_at <= end,
                Transaction.amount_cents < 0,
            )
        ).all()
        spent_cents = sum(-t.amount_cents for t in expenses)
        results.append(
            CategorySpend(
                category_id=category.id,
                category_name=category.name,
                limit_cents=category.monthly_limit_cents,
                spent_cents=spent_cents,
            )
        )
    return results
