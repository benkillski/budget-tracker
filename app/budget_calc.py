from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, func, select

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

    spend_rows = session.exec(
        select(Transaction.category_id, func.sum(-Transaction.amount_cents).label("spent"))
        .where(
            Transaction.posted_at >= start,
            Transaction.posted_at <= end,
            Transaction.amount_cents < 0,
            Transaction.category_id.is_not(None),
        )
        .group_by(Transaction.category_id)
    ).all()
    spent_by_category = {category_id: spent for category_id, spent in spend_rows}

    results: list[CategorySpend] = []
    for category in categories:
        results.append(
            CategorySpend(
                category_id=category.id,
                category_name=category.name,
                limit_cents=category.monthly_limit_cents,
                spent_cents=spent_by_category.get(category.id, 0),
            )
        )
    return results
