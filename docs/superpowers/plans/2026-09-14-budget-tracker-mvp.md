# Budget Tracker MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted budget tracker that automatically syncs bank transactions from SimpleFIN, categorizes them via user-defined rules, tracks spending against monthly per-category limits, and emails alerts/digests — deployable as a single Docker container.

**Architecture:** A single FastAPI application (server-rendered HTML via Jinja2 + HTMX, no separate frontend build) backed by SQLite via SQLModel. An in-process APScheduler runs a daily sync job (pull SimpleFIN transactions, apply categorization rules, check budgets, email alerts) and a digest job. A CSV import path reuses the same categorization pipeline as a fallback for accounts SimpleFIN doesn't cover.

**Tech Stack:** Python 3.12, FastAPI, SQLModel (SQLAlchemy) + SQLite, Jinja2, HTMX 2.x + Chart.js 4.x (via CDN), APScheduler, httpx, pydantic-settings, pytest.

**Spec:** [docs/superpowers/specs/2026-09-14-budget-tracker-design.md](../specs/2026-09-14-budget-tracker-design.md)

## Global Constraints

- No authentication — the app relies on Tailscale network access as the security boundary (per spec's "Context & constraints"; only devices on the user's tailnet can reach it).
- No database migration tool — schema is created via `SQLModel.metadata.create_all()` at startup. Hand-write `ALTER TABLE` statements if the schema changes later (single-developer project, low expected schema churn).
- All monetary values are stored as integer cents (`*_cents` columns) and converted to/from `Decimal` only at input/display boundaries via `app/money.py` — never `float` — to avoid floating-point rounding errors.
- All internally-generated timestamps use `app.timeutil.utc_now()` (a naive `datetime` representing UTC) rather than `datetime.now()`/`datetime.utcnow()` directly, giving one consistent naive-UTC convention for storage and range comparisons in SQLite.
- SimpleFIN's amount sign convention is preserved as-is in `Transaction.amount_cents`: negative = money out (expense), positive = money in (income/refund). Budget calculations sum only negative (expense) transactions per category.
- Rules are evaluated in ascending `priority` order (lower number = checked first); the first match wins.
- SMTP is the sole notification channel (both instant over-budget alerts and periodic digests), configured entirely via environment variables, provider-agnostic.
- Deployment target: a single Docker container via docker-compose, on the user's existing Proxmox Docker host, reachable over the already-running Tailscale subnet router (no per-service Tailscale sidecar needed).
- `Jinja2Templates.TemplateResponse` is always called with the modern `(request, name, context)` signature, not the deprecated `(name, {"request": request, ...})` form.
- Router tests use a `TestClient(app)` instance that is **not** entered as a context manager (no `with` block), so FastAPI's lifespan (which touches the real database file and starts the scheduler) never runs during tests. Test data instead comes from an in-memory SQLite engine injected via `app.dependency_overrides[get_session]`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `tests/__init__.py`
- Create: `tests/test_health.py`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- Produces: `app.main:app` (a `FastAPI` instance) — every later router task registers itself on this object via `app.include_router(...)`.

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi>=0.115
uvicorn[standard]>=0.32
sqlmodel>=0.0.22
httpx>=0.27
jinja2>=3.1
apscheduler>=3.10
pydantic-settings>=2.5
python-multipart>=0.0.12
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
pytest-cov>=5.0
respx>=0.21
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 4: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
data/
.pytest_cache/
.venv/
*.egg-info/
```

- [ ] **Step 5: Create `.env.example`**

```
DATABASE_URL=sqlite:////app/data/budget.db
SIMPLEFIN_ACCESS_URL=
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_TO=
WARNING_THRESHOLD_PCT=80
ALERT_THRESHOLD_PCT=100
DIGEST_FREQUENCY=daily
SYNC_HOUR_UTC=11
```

- [ ] **Step 6: Create `app/__init__.py`** (empty file)

- [ ] **Step 7: Create `tests/__init__.py`** (empty file)

- [ ] **Step 8: Write the failing test — `tests/test_health.py`**

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 9: Run test to verify it fails**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.main'` or similar, since `app/main.py` doesn't exist yet)

- [ ] **Step 10: Create `app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Budget Tracker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 11: Install dependencies**

Run: `python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt` (Windows) — or activate however you normally manage the venv for this project.

- [ ] **Step 12: Run test to verify it passes**

Run: `python -m pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml .gitignore .env.example app/__init__.py app/main.py tests/__init__.py tests/test_health.py
git commit -m "chore: scaffold FastAPI project with health check"
```

---

### Task 2: Money helpers

**Files:**
- Create: `app/money.py`
- Test: `tests/test_money.py`

**Interfaces:**
- Consumes: nothing (pure module).
- Produces: `to_cents(amount: Decimal) -> int`, `to_decimal(cents: int) -> Decimal`, `format_money(cents: int) -> str` — used by every module that touches money from here on.

- [ ] **Step 1: Write the failing tests — `tests/test_money.py`**

```python
from decimal import Decimal

from app.money import format_money, to_cents, to_decimal


def test_to_cents_converts_decimal_to_integer_cents():
    assert to_cents(Decimal("12.34")) == 1234


def test_to_cents_rounds_half_up():
    assert to_cents(Decimal("12.345")) == 1235


def test_to_decimal_converts_cents_to_decimal():
    assert to_decimal(1234) == Decimal("12.34")


def test_format_money_formats_positive_cents():
    assert format_money(123456) == "$1,234.56"


def test_format_money_formats_negative_cents():
    assert format_money(-500) == "-$5.00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_money.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.money'`)

- [ ] **Step 3: Create `app/money.py`**

```python
from decimal import ROUND_HALF_UP, Decimal


def to_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def to_decimal(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole = abs(cents) // 100
    frac = abs(cents) % 100
    return f"{sign}${whole:,}.{frac:02d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_money.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/money.py tests/test_money.py
git commit -m "feat: add money helpers for cents/Decimal conversion"
```

---

### Task 3: Database models, engine, and time helper

**Files:**
- Create: `app/timeutil.py`
- Create: `app/models.py`
- Create: `app/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_timeutil.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `utc_now() -> datetime` (naive, UTC); SQLModel classes `Account`, `Category`, `Rule`, `Transaction`, `AlertLog`, `SyncStatus`; `engine` (SQLAlchemy `Engine`), `init_db() -> None`, `get_session() -> Generator[Session, None, None]` from `app/db.py`; pytest fixtures `session` and `client` in `tests/conftest.py` used by every later test.

- [ ] **Step 1: Write the failing test — `tests/test_timeutil.py`**

```python
from datetime import datetime

from app.timeutil import utc_now


def test_utc_now_returns_naive_datetime():
    result = utc_now()
    assert isinstance(result, datetime)
    assert result.tzinfo is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_timeutil.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.timeutil'`)

- [ ] **Step 3: Create `app/timeutil.py`**

```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current time as a naive datetime representing UTC.

    Naive (no tzinfo) so it compares cleanly against other stored
    timestamps in SQLite, which has no native timezone-aware type.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_timeutil.py -v`
Expected: PASS

- [ ] **Step 5: Create `app/models.py`**

```python
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    simplefin_account_id: str = Field(unique=True, index=True)
    name: str
    institution: str
    account_type: str = Field(default="unknown")
    balance_cents: int = Field(default=0)
    balance_date: Optional[datetime] = None


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
    account_id: int = Field(foreign_key="account.id")
    posted_at: datetime
    payee: str
    amount_cents: int
    pending: bool = Field(default=False)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    rule_applied_id: Optional[int] = Field(default=None, foreign_key="rule.id")
    import_source: str = Field(default="simplefin")  # "simplefin" | "csv"


class AlertLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    category_id: int = Field(foreign_key="category.id")
    year: int
    month: int
    threshold_pct: int
    sent_at: datetime


class SyncStatus(SQLModel, table=True):
    """Singleton row (id=1) tracking the outcome of the last sync attempt."""

    id: Optional[int] = Field(default=None, primary_key=True)
    last_synced_at: Optional[datetime] = None
    last_sync_ok: bool = Field(default=True)
    last_error: Optional[str] = None
```

- [ ] **Step 6: Create `app/db.py`**

```python
import os
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/budget.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
```

- [ ] **Step 7: Create `tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client(session):
    from app.db import get_session
    from app.main import app

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()
```

- [ ] **Step 8: Write the failing test — `tests/test_models.py`**

```python
from datetime import datetime

from app.models import Account, AlertLog, Category, Rule, SyncStatus, Transaction


def test_can_create_and_query_each_model(session):
    account = Account(
        simplefin_account_id="acc-1",
        name="Checking",
        institution="Test Bank",
        balance_cents=10000,
    )
    category = Category(name="Groceries", monthly_limit_cents=40000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    rule = Rule(match_type="contains", match_value="KROGER", category_id=category.id, priority=1)
    session.add(rule)
    session.commit()
    session.refresh(rule)

    transaction = Transaction(
        account_id=account.id,
        posted_at=datetime(2026, 9, 1),
        payee="KROGER #123",
        amount_cents=-2599,
        category_id=category.id,
        rule_applied_id=rule.id,
    )
    session.add(transaction)
    session.commit()
    session.refresh(transaction)

    alert = AlertLog(category_id=category.id, year=2026, month=9, threshold_pct=100, sent_at=datetime(2026, 9, 15))
    session.add(alert)
    session.commit()
    session.refresh(alert)

    sync_status = SyncStatus(id=1, last_synced_at=datetime(2026, 9, 15, 6, 0), last_sync_ok=True)
    session.add(sync_status)
    session.commit()
    session.refresh(sync_status)

    assert account.id is not None
    assert category.id is not None
    assert rule.category_id == category.id
    assert transaction.category_id == category.id
    assert transaction.rule_applied_id == rule.id
    assert alert.category_id == category.id
    assert sync_status.last_sync_ok is True
```

- [ ] **Step 9: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.models'`)

- [ ] **Step 10: Run test to verify it passes** (models.py and db.py already created in steps 5-6)

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add app/timeutil.py app/models.py app/db.py tests/conftest.py tests/test_timeutil.py tests/test_models.py
git commit -m "feat: add database models, engine, and UTC time helper"
```

---

### Task 4: Categorization rules engine

**Files:**
- Create: `app/rules_engine.py`
- Test: `tests/test_rules_engine.py`

**Interfaces:**
- Consumes: `Rule` from `app.models`.
- Produces: `apply_rules(payee: str, rules: list[Rule]) -> Rule | None` — caller must pass `rules` already sorted ascending by `priority`; used by `sync_service` (Task 7) and `csv_import` (Task 15).

- [ ] **Step 1: Write the failing tests — `tests/test_rules_engine.py`**

```python
import pytest

from app.models import Rule
from app.rules_engine import apply_rules


def _rule(match_type: str, match_value: str, priority: int = 0, category_id: int = 1) -> Rule:
    return Rule(match_type=match_type, match_value=match_value, category_id=category_id, priority=priority)


def test_contains_match_is_case_insensitive():
    rule = _rule("contains", "kroger")
    result = apply_rules("KROGER #123", [rule])
    assert result is rule


def test_equals_match_requires_exact_payee():
    rule = _rule("equals", "Netflix")
    assert apply_rules("Netflix", [rule]) is rule
    assert apply_rules("Netflix Inc", [rule]) is None


def test_regex_match():
    rule = _rule("regex", r"^AMZN\*")
    assert apply_rules("AMZN*ABC123", [rule]) is rule
    assert apply_rules("NOT AMZN", [rule]) is None


def test_first_match_wins_by_list_order():
    high_priority = _rule("contains", "STORE", priority=0, category_id=1)
    low_priority = _rule("contains", "STORE", priority=1, category_id=2)
    result = apply_rules("MY STORE", [high_priority, low_priority])
    assert result is high_priority


def test_no_match_returns_none():
    rule = _rule("contains", "STARBUCKS")
    assert apply_rules("KROGER", [rule]) is None


def test_unknown_match_type_raises():
    rule = _rule("fuzzy", "whatever")
    with pytest.raises(ValueError):
        apply_rules("anything", [rule])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rules_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.rules_engine'`)

- [ ] **Step 3: Create `app/rules_engine.py`**

```python
import re

from app.models import Rule


def apply_rules(payee: str, rules: list[Rule]) -> Rule | None:
    """Return the first rule (in list order) that matches payee, or None.

    Callers must pass rules pre-sorted ascending by priority (lower
    number = checked first) — e.g. `select(Rule).order_by(Rule.priority)`.
    """
    for rule in rules:
        if _matches(payee, rule):
            return rule
    return None


def _matches(payee: str, rule: Rule) -> bool:
    if rule.match_type == "contains":
        return rule.match_value.lower() in payee.lower()
    if rule.match_type == "equals":
        return payee.strip().lower() == rule.match_value.strip().lower()
    if rule.match_type == "regex":
        return re.search(rule.match_value, payee) is not None
    raise ValueError(f"Unknown match_type: {rule.match_type}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/rules_engine.py tests/test_rules_engine.py
git commit -m "feat: add categorization rules engine"
```

---

### Task 5: Budget calculation

**Files:**
- Create: `app/budget_calc.py`
- Test: `tests/test_budget_calc.py`

**Interfaces:**
- Consumes: `Category`, `Transaction` from `app.models`.
- Produces: `CategorySpend` dataclass (`category_id`, `category_name`, `limit_cents`, `spent_cents`, `.remaining_cents`, `.pct_used`); `compute_budget_period(session: Session, year: int, month: int) -> list[CategorySpend]` — used by `sync_service` (Task 7), `jobs.digest_job` (Task 9), dashboard/trends routers (Tasks 10, 13).

- [ ] **Step 1: Write the failing tests — `tests/test_budget_calc.py`**

```python
from datetime import datetime

from app.budget_calc import compute_budget_period
from app.models import Account, Category, Transaction


def _seed_account(session) -> Account:
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def test_sums_only_expenses_in_the_given_month(session):
    account = _seed_account(session)
    category = Category(name="Groceries", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    session.add_all(
        [
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 5), payee="Store A",
                        amount_cents=-2000, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 20), payee="Store B",
                        amount_cents=-1500, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 8, 31), payee="Store C (last month)",
                        amount_cents=-5000, category_id=category.id),
            Transaction(account_id=account.id, posted_at=datetime(2026, 9, 10), payee="Refund",
                        amount_cents=500, category_id=category.id),
        ]
    )
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.category_name == "Groceries"
    assert result.limit_cents == 10000
    assert result.spent_cents == 3500
    assert result.remaining_cents == 6500
    assert result.pct_used == 35.0


def test_category_with_no_transactions_has_zero_spend(session):
    session.add(Category(name="Dining", monthly_limit_cents=5000))
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.spent_cents == 0
    assert result.pct_used == 0.0


def test_pct_used_is_zero_when_limit_is_zero(session):
    session.add(Category(name="Misc", monthly_limit_cents=0))
    session.commit()

    [result] = compute_budget_period(session, 2026, 9)

    assert result.pct_used == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_budget_calc.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.budget_calc'`)

- [ ] **Step 3: Create `app/budget_calc.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_budget_calc.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/budget_calc.py tests/test_budget_calc.py
git commit -m "feat: add monthly budget calculation"
```

---

### Task 6: SimpleFIN client

**Files:**
- Create: `app/simplefin_client.py`
- Test: `tests/test_simplefin_client.py`

**Interfaces:**
- Consumes: `httpx`.
- Produces: `SimpleFINTransaction` (`id`, `posted_at`, `payee`, `amount_cents`, `pending`), `SimpleFINAccount` (`id`, `name`, `org_name`, `balance_cents`, `transactions`), `SimpleFINClient(access_url, http_client=None)` with `.get_accounts(start_date: datetime | None = None) -> list[SimpleFINAccount]` — used by `sync_service` (Task 7) and `jobs.py` (Task 9).

- [ ] **Step 1: Write the failing tests — `tests/test_simplefin_client.py`**

```python
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
    assert first.amount_cents == -2599
    assert first.pending is False

    assert second.payee == "Pending charge"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simplefin_client.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.simplefin_client'`)

- [ ] **Step 3: Create `app/simplefin_client.py`**

```python
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
```

Note: `start_date.replace(tzinfo=timezone.utc)` assumes the caller passes either a naive datetime that already represents UTC (per this project's convention, see Global Constraints) or an already-UTC-aware one; `.replace` overwrites any existing tzinfo rather than converting, which is correct for both cases here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simplefin_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/simplefin_client.py tests/test_simplefin_client.py
git commit -m "feat: add SimpleFIN API client"
```

---

### Task 7: Sync service

**Files:**
- Create: `app/sync_service.py`
- Test: `tests/test_sync_service.py`

**Interfaces:**
- Consumes: `apply_rules` (Task 4), `compute_budget_period` (Task 5), `SimpleFINClient`/`SimpleFINAccount`/`SimpleFINTransaction` (Task 6), `utc_now` (Task 3), models (Task 3).
- Produces: `ThresholdCrossing` (`category_id`, `category_name`, `threshold_pct`, `spent_cents`, `limit_cents`), `SyncResult` (`new_transaction_count`, `newly_crossed: list[ThresholdCrossing]`), `run_sync(session, client, warning_pct: int, alert_pct: int) -> SyncResult` — used by `jobs.daily_sync_job` (Task 9).

- [ ] **Step 1: Write the failing tests — `tests/test_sync_service.py`**

```python
from datetime import datetime

from sqlmodel import select

from app.models import Account, Category, Rule
from app.simplefin_client import SimpleFINAccount, SimpleFINTransaction
from app.sync_service import run_sync


class FakeSimpleFINClient:
    def __init__(self, accounts: list[SimpleFINAccount]):
        self._accounts = accounts

    def get_accounts(self, start_date=None):
        return self._accounts


def _seed_category_and_rule(session) -> Category:
    category = Category(name="Groceries", monthly_limit_cents=3000)
    session.add(category)
    session.commit()
    session.refresh(category)
    session.add(Rule(match_type="contains", match_value="KROGER", category_id=category.id, priority=0))
    session.commit()
    return category


def test_run_sync_inserts_new_transactions_and_categorizes_them(session):
    category = _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1",
        name="Checking",
        org_name="Test Bank",
        balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    result = run_sync(session, client, warning_pct=80, alert_pct=100)

    assert result.new_transaction_count == 1
    account = session.exec(
        select(Account).where(Account.simplefin_account_id == "acc-1")
    ).first()
    assert account is not None
    assert account.balance_cents == 50000


def test_run_sync_does_not_duplicate_existing_transactions(session):
    _seed_category_and_rule(session)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-2500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    first = run_sync(session, client, warning_pct=80, alert_pct=100)
    second = run_sync(session, client, warning_pct=80, alert_pct=100)

    assert first.new_transaction_count == 1
    assert second.new_transaction_count == 0


def test_run_sync_reports_newly_crossed_thresholds_once(session):
    category = _seed_category_and_rule(session)  # limit is 3000 cents ($30)
    fake_account = SimpleFINAccount(
        id="acc-1", name="Checking", org_name="Test Bank", balance_cents=50000,
        transactions=[
            SimpleFINTransaction(id="txn-1", posted_at=datetime(2026, 9, 5), payee="KROGER #1",
                                  amount_cents=-3500, pending=False),
        ],
    )
    client = FakeSimpleFINClient([fake_account])

    result = run_sync(session, client, warning_pct=80, alert_pct=100)

    crossed_thresholds = {c.threshold_pct for c in result.newly_crossed}
    assert crossed_thresholds == {80, 100}
    assert all(c.category_name == "Groceries" for c in result.newly_crossed)

    # A second sync with no new transactions must not re-alert.
    fake_account.transactions = []
    second = run_sync(session, client, warning_pct=80, alert_pct=100)
    assert second.newly_crossed == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_service.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.sync_service'`)

- [ ] **Step 3: Create `app/sync_service.py`**

```python
from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session, select

from app.budget_calc import compute_budget_period
from app.models import Account, AlertLog, Rule, Transaction
from app.rules_engine import apply_rules
from app.simplefin_client import SimpleFINClient
from app.timeutil import utc_now

SYNC_LOOKBACK_DAYS = 35


@dataclass
class ThresholdCrossing:
    category_id: int
    category_name: str
    threshold_pct: int
    spent_cents: int
    limit_cents: int


@dataclass
class SyncResult:
    new_transaction_count: int = 0
    newly_crossed: list[ThresholdCrossing] = field(default_factory=list)


def run_sync(session: Session, client: SimpleFINClient, warning_pct: int, alert_pct: int) -> SyncResult:
    result = SyncResult()
    start_date = utc_now() - timedelta(days=SYNC_LOOKBACK_DAYS)
    sf_accounts = client.get_accounts(start_date=start_date)

    rules = session.exec(select(Rule).order_by(Rule.priority)).all()

    for sf_account in sf_accounts:
        account = session.exec(
            select(Account).where(Account.simplefin_account_id == sf_account.id)
        ).first()
        if account is None:
            account = Account(
                simplefin_account_id=sf_account.id,
                name=sf_account.name,
                institution=sf_account.org_name,
                balance_cents=sf_account.balance_cents,
            )
        else:
            account.balance_cents = sf_account.balance_cents
        session.add(account)
        session.flush()

        for sf_txn in sf_account.transactions:
            existing = session.exec(
                select(Transaction).where(Transaction.simplefin_transaction_id == sf_txn.id)
            ).first()
            if existing is not None:
                existing.pending = sf_txn.pending
                session.add(existing)
                continue

            matched_rule = apply_rules(sf_txn.payee, rules)
            session.add(
                Transaction(
                    simplefin_transaction_id=sf_txn.id,
                    account_id=account.id,
                    posted_at=sf_txn.posted_at,
                    payee=sf_txn.payee,
                    amount_cents=sf_txn.amount_cents,
                    pending=sf_txn.pending,
                    category_id=matched_rule.category_id if matched_rule else None,
                    rule_applied_id=matched_rule.id if matched_rule else None,
                    import_source="simplefin",
                )
            )
            result.new_transaction_count += 1

    session.commit()

    now = utc_now()
    budget_periods = compute_budget_period(session, now.year, now.month)
    for period in budget_periods:
        if period.limit_cents <= 0:
            continue
        for threshold in sorted({warning_pct, alert_pct}):
            if period.pct_used < threshold:
                continue
            already_alerted = session.exec(
                select(AlertLog).where(
                    AlertLog.category_id == period.category_id,
                    AlertLog.year == now.year,
                    AlertLog.month == now.month,
                    AlertLog.threshold_pct == threshold,
                )
            ).first()
            if already_alerted is not None:
                continue
            session.add(
                AlertLog(
                    category_id=period.category_id,
                    year=now.year,
                    month=now.month,
                    threshold_pct=threshold,
                    sent_at=now,
                )
            )
            result.newly_crossed.append(
                ThresholdCrossing(
                    category_id=period.category_id,
                    category_name=period.category_name,
                    threshold_pct=threshold,
                    spent_cents=period.spent_cents,
                    limit_cents=period.limit_cents,
                )
            )
    session.commit()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/sync_service.py tests/test_sync_service.py
git commit -m "feat: add sync service orchestrating fetch, categorize, and alert"
```

---

### Task 8: Email notifications

**Files:**
- Create: `app/notifications.py`
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `format_money` (Task 2), `CategorySpend` (Task 5), `ThresholdCrossing` (Task 7).
- Produces: `SMTPConfig` (`host`, `port`, `username`, `password`, `from_addr`, `to_addr`), `send_alert_email(config, crossing) -> None`, `send_digest_email(config, periods) -> None` — used by `jobs.py` (Task 9).

- [ ] **Step 1: Write the failing tests — `tests/test_notifications.py`**

```python
from unittest.mock import MagicMock, patch

from app.budget_calc import CategorySpend
from app.notifications import SMTPConfig, send_alert_email, send_digest_email
from app.sync_service import ThresholdCrossing

CONFIG = SMTPConfig(
    host="smtp.example.com", port=587, username="user@example.com",
    password="secret", from_addr="user@example.com", to_addr="user@example.com",
)


@patch("app.notifications.smtplib.SMTP")
def test_send_alert_email_logs_in_and_sends_message(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    crossing = ThresholdCrossing(
        category_id=1, category_name="Groceries", threshold_pct=100,
        spent_cents=3500, limit_cents=3000,
    )

    send_alert_email(CONFIG, crossing)

    mock_smtp.login.assert_called_once_with("user@example.com", "secret")
    sent_message = mock_smtp.send_message.call_args[0][0]
    assert "Groceries" in sent_message["Subject"]
    assert "100%" in sent_message["Subject"]
    body = sent_message.get_content()
    assert "$35.00" in body
    assert "$30.00" in body


@patch("app.notifications.smtplib.SMTP")
def test_send_digest_email_lists_only_budgeted_categories(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    periods = [
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),
        CategorySpend(category_id=2, category_name="Unbudgeted", limit_cents=0, spent_cents=500),
    ]

    send_digest_email(CONFIG, periods)

    sent_message = mock_smtp.send_message.call_args[0][0]
    body = sent_message.get_content()
    assert "Groceries" in body
    assert "Unbudgeted" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notifications.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.notifications'`)

- [ ] **Step 3: Create `app/notifications.py`**

```python
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.budget_calc import CategorySpend
from app.money import format_money
from app.sync_service import ThresholdCrossing


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addr: str


def _send(config: SMTPConfig, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_addr
    message["To"] = config.to_addr
    message.set_content(body)

    with smtplib.SMTP(config.host, config.port) as smtp:
        smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def send_alert_email(config: SMTPConfig, crossing: ThresholdCrossing) -> None:
    subject = f"Budget alert: {crossing.category_name} at {crossing.threshold_pct}%"
    body = (
        f"{crossing.category_name} has reached {crossing.threshold_pct}% of its monthly budget.\n\n"
        f"Spent: {format_money(crossing.spent_cents)}\n"
        f"Limit: {format_money(crossing.limit_cents)}\n"
    )
    _send(config, subject, body)


def send_digest_email(config: SMTPConfig, periods: list[CategorySpend]) -> None:
    subject = "Budget digest"
    lines = [
        f"{p.category_name}: {format_money(p.spent_cents)} / {format_money(p.limit_cents)} ({p.pct_used:.0f}%)"
        for p in periods
        if p.limit_cents > 0
    ]
    body = "\n".join(lines) if lines else "No budgeted categories yet."
    _send(config, subject, body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notifications.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/notifications.py tests/test_notifications.py
git commit -m "feat: add SMTP alert and digest email sending"
```

---

### Task 9: Settings, scheduler, and job wiring

**Files:**
- Create: `app/config.py`
- Create: `app/jobs.py`
- Create: `app/scheduler.py`
- Modify: `app/main.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `Settings` reads `.env`; `run_sync` (Task 7), `send_alert_email`/`send_digest_email`/`SMTPConfig` (Task 8), `compute_budget_period` (Task 5), `SimpleFINClient` (Task 6), `utc_now` (Task 3), `SyncStatus` (Task 3).
- Produces: `app.config.settings` (a `Settings` instance); `daily_sync_job(settings, engine) -> None`, `digest_job(settings, engine) -> None`; `create_scheduler(settings, engine) -> BackgroundScheduler` — wired into `app.main`'s lifespan; later router tasks import `app.main.app` unchanged. `daily_sync_job` also upserts the singleton `SyncStatus` row (id=1) with the outcome of each attempt, consumed by the dashboard (Task 10) to show a last-synced/failed banner.

- [ ] **Step 1: Create `app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/budget.db"
    simplefin_access_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    warning_threshold_pct: int = 80
    alert_threshold_pct: int = 100
    digest_frequency: str = "daily"  # "daily" | "weekly"
    sync_hour_utc: int = 11


settings = Settings()
```

- [ ] **Step 2: Create `app/jobs.py`**

```python
from sqlmodel import Session

from app.budget_calc import compute_budget_period
from app.config import Settings
from app.models import SyncStatus
from app.notifications import SMTPConfig, send_alert_email, send_digest_email
from app.simplefin_client import SimpleFINClient
from app.sync_service import run_sync
from app.timeutil import utc_now


def _smtp_config(settings: Settings) -> SMTPConfig:
    return SMTPConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_addr=settings.smtp_from,
        to_addr=settings.smtp_to,
    )


def daily_sync_job(settings: Settings, engine) -> None:
    client = SimpleFINClient(settings.simplefin_access_url)
    with Session(engine) as session:
        status = session.get(SyncStatus, 1) or SyncStatus(id=1)
        try:
            result = run_sync(session, client, settings.warning_threshold_pct, settings.alert_threshold_pct)
        except Exception as exc:
            status.last_synced_at = utc_now()
            status.last_sync_ok = False
            status.last_error = str(exc)
            session.add(status)
            session.commit()
            raise

        status.last_synced_at = utc_now()
        status.last_sync_ok = True
        status.last_error = None
        session.add(status)
        session.commit()

        smtp_config = _smtp_config(settings)
        for crossing in result.newly_crossed:
            send_alert_email(smtp_config, crossing)


def digest_job(settings: Settings, engine) -> None:
    now = utc_now()
    with Session(engine) as session:
        periods = compute_budget_period(session, now.year, now.month)
        send_digest_email(_smtp_config(settings), periods)
```

Note: `daily_sync_job` re-raises after recording the failure so APScheduler logs it (it catches job exceptions internally and won't crash the app) — this satisfies the spec's "Sync failures... logged" requirement while still updating `SyncStatus` for the dashboard banner.

- [ ] **Step 3: Create `app/scheduler.py`**

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.jobs import daily_sync_job, digest_job


def create_scheduler(settings: Settings, engine) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        daily_sync_job,
        trigger=CronTrigger(hour=settings.sync_hour_utc, minute=0),
        args=[settings, engine],
        id="daily_sync",
        replace_existing=True,
    )
    if settings.digest_frequency == "weekly":
        digest_trigger = CronTrigger(day_of_week="mon", hour=settings.sync_hour_utc, minute=15)
    else:
        digest_trigger = CronTrigger(hour=settings.sync_hour_utc, minute=15)
    scheduler.add_job(
        digest_job,
        trigger=digest_trigger,
        args=[settings, engine],
        id="digest",
        replace_existing=True,
    )
    return scheduler
```

- [ ] **Step 4: Write the failing test — `tests/test_scheduler.py`**

```python
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.scheduler import create_scheduler


def test_create_scheduler_registers_daily_sync_and_digest_jobs():
    settings = Settings(digest_frequency="daily", sync_hour_utc=6)
    scheduler = create_scheduler(settings, engine=None)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"daily_sync", "digest"}


def test_weekly_digest_uses_day_of_week_trigger():
    settings = Settings(digest_frequency="weekly", sync_hour_utc=6)
    scheduler = create_scheduler(settings, engine=None)

    digest_job = scheduler.get_job("digest")
    assert isinstance(digest_job.trigger, CronTrigger)
    field_names = {f.name for f in digest_job.trigger.fields if not f.is_default}
    assert "day_of_week" in field_names
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.scheduler'`) — this resolves once step 3 above is in place; run again after confirming step 3's file exists.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 7: Write the failing tests — `tests/test_jobs.py`**

```python
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.jobs import daily_sync_job, digest_job
from app.models import Category, Rule, SyncStatus
from app.sync_service import SyncResult, ThresholdCrossing


def _make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_sends_alert_for_each_crossing(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    crossing = ThresholdCrossing(category_id=1, category_name="Groceries", threshold_pct=100,
                                  spent_cents=3500, limit_cents=3000)
    mock_run_sync.return_value = SyncResult(new_transaction_count=1, newly_crossed=[crossing])

    daily_sync_job(settings, engine)

    mock_client_class.assert_called_once_with(settings.simplefin_access_url)
    mock_run_sync.assert_called_once()
    mock_send_alert.assert_called_once()
    assert mock_send_alert.call_args[0][1] is crossing

    with Session(engine) as session:
        status = session.get(SyncStatus, 1)
        assert status.last_sync_ok is True
        assert status.last_synced_at is not None


@patch("app.jobs.send_alert_email")
@patch("app.jobs.run_sync")
@patch("app.jobs.SimpleFINClient")
def test_daily_sync_job_records_failure_and_reraises(mock_client_class, mock_run_sync, mock_send_alert):
    engine = _make_engine()
    settings = Settings(simplefin_access_url="https://u:p@bridge.example.com/simplefin")
    mock_run_sync.side_effect = RuntimeError("SimpleFIN returned 401")

    with pytest.raises(RuntimeError):
        daily_sync_job(settings, engine)

    mock_send_alert.assert_not_called()
    with Session(engine) as session:
        status = session.get(SyncStatus, 1)
        assert status.last_sync_ok is False
        assert status.last_error == "SimpleFIN returned 401"


@patch("app.jobs.send_digest_email")
def test_digest_job_sends_digest_with_current_budget_periods(mock_send_digest):
    engine = _make_engine()
    with Session(engine) as session:
        category = Category(name="Groceries", monthly_limit_cents=3000)
        session.add(category)
        session.commit()
        session.refresh(category)
    settings = Settings()

    digest_job(settings, engine)

    mock_send_digest.assert_called_once()
    periods_arg = mock_send_digest.call_args[0][1]
    assert any(p.category_name == "Groceries" for p in periods_arg)
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.jobs'`) — resolves once step 2 above is in place; run again after confirming.

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: PASS

- [ ] **Step 10: Modify `app/main.py`** to wire startup/shutdown to the scheduler

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import engine, init_db
from app.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler(settings, engine)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Budget Tracker", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 11: Run the full test suite to confirm nothing broke**

Run: `python -m pytest -v`
Expected: All tests PASS (health check still passes because `tests/test_health.py` uses `TestClient(app)` without a `with` block, so lifespan doesn't run and the real database/scheduler are never touched)

- [ ] **Step 12: Commit**

```bash
git add app/config.py app/jobs.py app/scheduler.py app/main.py tests/test_scheduler.py tests/test_jobs.py
git commit -m "feat: wire settings, scheduler, and sync/digest jobs into app lifespan"
```

---

### Task 10: Dashboard home view

**Files:**
- Create: `app/routers/__init__.py`
- Create: `app/routers/dashboard.py`
- Create: `app/templates/base.html`
- Create: `app/templates/home.html`
- Modify: `app/main.py`
- Test: `tests/test_dashboard_router.py`

**Interfaces:**
- Consumes: `get_session` (Task 3), `compute_budget_period` (Task 5), `format_money` (Task 2), `Account`/`SyncStatus` models (Task 3).
- Produces: `app/routers/dashboard.py:router` registered at `/`.

- [ ] **Step 1: Create `app/routers/__init__.py`** (empty file)

- [ ] **Step 2: Create `app/templates/base.html`**

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Budget Tracker</title>
    <script src="https://unpkg.com/htmx.org@2.0.3"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 900px; }
        nav a { margin-right: 1rem; }
        table { border-collapse: collapse; width: 100%; }
        th, td { text-align: left; padding: 0.4rem; border-bottom: 1px solid #ddd; }
        .bar { background: #eee; border-radius: 4px; overflow: hidden; height: 1rem; margin: 0.25rem 0; }
        .bar-fill { height: 100%; }
        .bar-fill.ok { background: #4caf50; }
        .bar-fill.warn { background: #ff9800; }
        .bar-fill.over { background: #f44336; }
    </style>
</head>
<body>
    <nav>
        <a href="/">Home</a>
        <a href="/transactions">Transactions</a>
        <a href="/rules">Rules</a>
        <a href="/trends">Trends</a>
        <a href="/settings">Settings</a>
        <a href="/import">Import CSV</a>
    </nav>
    <hr>
    {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Create `app/templates/home.html`**

```html
{% extends "base.html" %}
{% block content %}
{% if sync_status is none %}
<p style="background:#fff3cd;padding:0.5rem;border-radius:4px">No sync has run yet.</p>
{% elif not sync_status.last_sync_ok %}
<p style="background:#f8d7da;padding:0.5rem;border-radius:4px">
    Last sync failed at {{ sync_status.last_synced_at.strftime("%Y-%m-%d %H:%M") }} UTC: {{ sync_status.last_error }}
</p>
{% else %}
<p style="color:#666">Last synced {{ sync_status.last_synced_at.strftime("%Y-%m-%d %H:%M") }} UTC</p>
{% endif %}

<h1>{{ month_label }}</h1>

<h2>Accounts</h2>
<ul>
{% for account in accounts %}
    <li>{{ account.name }}: {{ format_money(account.balance_cents) }}</li>
{% endfor %}
</ul>

<h2>Budgets</h2>
{% for period in periods %}
    {% if period.limit_cents > 0 %}
    <div>
        <strong>{{ period.category_name }}</strong>
        - {{ format_money(period.spent_cents) }} / {{ format_money(period.limit_cents) }}
        ({{ "%.0f"|format(period.pct_used) }}%)
        <div class="bar">
            <div class="bar-fill {% if period.pct_used >= 100 %}over{% elif period.pct_used >= 80 %}warn{% else %}ok{% endif %}"
                 style="width: {{ [period.pct_used, 100]|min }}%"></div>
        </div>
    </div>
    {% endif %}
{% endfor %}
{% endblock %}
```

- [ ] **Step 4: Create `app/routers/dashboard.py`**

```python
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.budget_calc import compute_budget_period
from app.db import get_session
from app.models import Account, SyncStatus
from app.money import format_money
from app.timeutil import utc_now

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def home(request: Request, session: Session = Depends(get_session)):
    now = utc_now()
    periods = compute_budget_period(session, now.year, now.month)
    accounts = session.exec(select(Account)).all()
    sync_status = session.get(SyncStatus, 1)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "periods": periods,
            "accounts": accounts,
            "format_money": format_money,
            "month_label": now.strftime("%B %Y"),
            "sync_status": sync_status,
        },
    )
```

- [ ] **Step 5: Write the failing test — `tests/test_dashboard_router.py`**

```python
from datetime import datetime

from app.models import Account, Category, SyncStatus, Transaction


def test_home_shows_no_sync_message_when_never_synced(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No sync has run yet" in response.text


def test_home_shows_failure_banner_when_last_sync_failed(session, client):
    session.add(SyncStatus(id=1, last_synced_at=datetime(2026, 9, 14, 6, 0), last_sync_ok=False,
                            last_error="SimpleFIN returned 401"))
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "Last sync failed" in response.text
    assert "SimpleFIN returned 401" in response.text


def test_home_shows_accounts_and_budget_progress(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank", balance_cents=150000)
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    session.add(
        Transaction(account_id=account.id, posted_at=datetime.utcnow(), payee="Store",
                    amount_cents=-1500, category_id=category.id)
    )
    session.commit()

    response = client.get("/")

    assert response.status_code == 200
    assert "Checking" in response.text
    assert "$1,500.00" in response.text
    assert "Groceries" in response.text
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_router.py -v`
Expected: FAIL (404, since `/` isn't registered on `app` yet)

- [ ] **Step 7: Modify `app/main.py`** to include the dashboard router

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import engine, init_db
from app.routers import dashboard
from app.scheduler import create_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = create_scheduler(settings, engine)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Budget Tracker", lifespan=lifespan)
app.include_router(dashboard.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_router.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/routers/__init__.py app/routers/dashboard.py app/templates/base.html app/templates/home.html app/main.py tests/test_dashboard_router.py
git commit -m "feat: add dashboard home view"
```

---

### Task 11: Transactions view with inline recategorize

**Files:**
- Create: `app/routers/transactions.py`
- Create: `app/templates/transactions.html`
- Create: `app/templates/partials/transaction_row.html`
- Modify: `app/main.py`
- Test: `tests/test_transactions_router.py`

**Interfaces:**
- Consumes: `get_session`, `Category`/`Transaction` models, `format_money`.
- Produces: `app/routers/transactions.py:router` at `/transactions`, with `GET /transactions`, `GET /transactions?uncategorized_only=true`, and `POST /transactions/{id}/category`.

- [ ] **Step 1: Create `app/templates/partials/transaction_row.html`**

```html
<tr id="txn-{{ transaction.id }}">
    <td>{{ transaction.posted_at.strftime("%Y-%m-%d") }}</td>
    <td>{{ transaction.payee }}</td>
    <td>{{ format_money(transaction.amount_cents) }}</td>
    <td>
        <select name="category_id"
                hx-post="/transactions/{{ transaction.id }}/category"
                hx-target="#txn-{{ transaction.id }}"
                hx-swap="outerHTML">
            <option value="">Uncategorized</option>
            {% for category in categories %}
            <option value="{{ category.id }}" {% if transaction.category_id == category.id %}selected{% endif %}>
                {{ category.name }}
            </option>
            {% endfor %}
        </select>
    </td>
</tr>
```

- [ ] **Step 2: Create `app/templates/transactions.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Transactions</h1>
<p>
    {% if uncategorized_only %}
        <a href="/transactions">Show all</a>
    {% else %}
        <a href="/transactions?uncategorized_only=true">Show uncategorized only</a>
    {% endif %}
</p>
<table>
    <thead><tr><th>Date</th><th>Payee</th><th>Amount</th><th>Category</th></tr></thead>
    <tbody>
    {% for transaction in transactions %}
        {% include "partials/transaction_row.html" %}
    {% endfor %}
    </tbody>
</table>
{% endblock %}
```

- [ ] **Step 3: Create `app/routers/transactions.py`**

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, Transaction
from app.money import format_money

router = APIRouter(prefix="/transactions")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def list_transactions(
    request: Request,
    uncategorized_only: bool = False,
    session: Session = Depends(get_session),
):
    query = select(Transaction).order_by(Transaction.posted_at.desc())
    if uncategorized_only:
        query = query.where(Transaction.category_id.is_(None))
    transactions = session.exec(query).all()
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": transactions,
            "categories": categories,
            "format_money": format_money,
            "uncategorized_only": uncategorized_only,
        },
    )


@router.post("/{transaction_id}/category")
def set_category(
    transaction_id: int,
    request: Request,
    category_id: str = Form(""),
    session: Session = Depends(get_session),
):
    transaction = session.get(Transaction, transaction_id)
    transaction.category_id = int(category_id) if category_id else None
    transaction.rule_applied_id = None
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "partials/transaction_row.html",
        {"transaction": transaction, "categories": categories, "format_money": format_money},
    )
```

- [ ] **Step 4: Write the failing tests — `tests/test_transactions_router.py`**

```python
from datetime import datetime

from app.models import Account, Category, Transaction


def _seed(session):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    categorized = Transaction(account_id=account.id, posted_at=datetime(2026, 9, 1), payee="Kroger",
                               amount_cents=-1000, category_id=category.id)
    uncategorized = Transaction(account_id=account.id, posted_at=datetime(2026, 9, 2), payee="Mystery Charge",
                                 amount_cents=-500)
    session.add(categorized)
    session.add(uncategorized)
    session.commit()
    session.refresh(categorized)
    session.refresh(uncategorized)
    return category, categorized, uncategorized


def test_list_transactions_shows_all_by_default(session, client):
    _seed(session)

    response = client.get("/transactions")

    assert response.status_code == 200
    assert "Kroger" in response.text
    assert "Mystery Charge" in response.text


def test_list_transactions_filters_to_uncategorized(session, client):
    _seed(session)

    response = client.get("/transactions?uncategorized_only=true")

    assert response.status_code == 200
    assert "Mystery Charge" in response.text
    assert "Kroger" not in response.text


def test_set_category_persists_and_returns_updated_row(session, client):
    category, _categorized, uncategorized = _seed(session)

    response = client.post(
        f"/transactions/{uncategorized.id}/category",
        data={"category_id": str(category.id)},
    )

    assert response.status_code == 200
    assert "selected" in response.text
    assert "Groceries" in response.text

    session.refresh(uncategorized)
    assert uncategorized.category_id == category.id
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python -m pytest tests/test_transactions_router.py -v`
Expected: FAIL (404, `/transactions` not registered yet)

- [ ] **Step 6: Modify `app/main.py`** to include the transactions router

```python
from app.routers import dashboard, transactions
...
app.include_router(dashboard.router)
app.include_router(transactions.router)
```

(Add the `transactions` import alongside `dashboard`, and the `include_router` call after the existing one.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_transactions_router.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/routers/transactions.py app/templates/transactions.html app/templates/partials/transaction_row.html app/main.py tests/test_transactions_router.py
git commit -m "feat: add transactions view with inline recategorize"
```

---

### Task 12: Rules view

**Files:**
- Create: `app/routers/rules.py`
- Create: `app/templates/rules.html`
- Modify: `app/main.py`
- Test: `tests/test_rules_router.py`

**Interfaces:**
- Consumes: `get_session`, `Category`/`Rule`/`Transaction` models.
- Produces: `app/routers/rules.py:router` at `/rules`, with `GET /rules`, `POST /rules`, `POST /rules/from-transaction/{transaction_id}`.

- [ ] **Step 1: Create `app/templates/rules.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Rules</h1>
<table>
<thead><tr><th>Priority</th><th>Match</th><th>Value</th><th>Category</th></tr></thead>
<tbody>
{% for rule in rules %}
<tr>
    <td>{{ rule.priority }}</td>
    <td>{{ rule.match_type }}</td>
    <td>{{ rule.match_value }}</td>
    <td>{{ (categories|selectattr("id", "equalto", rule.category_id)|first).name }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>New rule</h2>
<form method="post" action="/rules">
    <select name="match_type">
        <option value="contains">Contains</option>
        <option value="equals">Equals</option>
        <option value="regex">Regex</option>
    </select>
    <input name="match_value" placeholder="e.g. KROGER" required>
    <select name="category_id">
        {% for category in categories %}
        <option value="{{ category.id }}">{{ category.name }}</option>
        {% endfor %}
    </select>
    <input name="priority" type="number" value="0">
    <button type="submit">Add rule</button>
</form>
{% endblock %}
```

- [ ] **Step 2: Create `app/routers/rules.py`**

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, Rule, Transaction

router = APIRouter(prefix="/rules")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def list_rules(request: Request, session: Session = Depends(get_session)):
    rules = session.exec(select(Rule).order_by(Rule.priority)).all()
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(request, "rules.html", {"rules": rules, "categories": categories})


@router.post("")
def create_rule(
    match_type: str = Form(...),
    match_value: str = Form(...),
    category_id: int = Form(...),
    priority: int = Form(0),
    session: Session = Depends(get_session),
):
    session.add(Rule(match_type=match_type, match_value=match_value, category_id=category_id, priority=priority))
    session.commit()
    return RedirectResponse("/rules", status_code=303)


@router.post("/from-transaction/{transaction_id}")
def create_rule_from_transaction(
    transaction_id: int,
    category_id: int = Form(...),
    session: Session = Depends(get_session),
):
    transaction = session.get(Transaction, transaction_id)
    if transaction is not None:
        session.add(Rule(match_type="contains", match_value=transaction.payee, category_id=category_id, priority=0))
        transaction.category_id = category_id
        session.add(transaction)
        session.commit()
    return RedirectResponse("/rules", status_code=303)
```

- [ ] **Step 3: Write the failing tests — `tests/test_rules_router.py`**

```python
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
    )
    assert response.status_code == 303

    session.refresh(transaction)
    assert transaction.category_id == category.id

    rules = session.exec(select(Rule)).all()
    assert any(r.match_value == "CHIPOTLE 456" for r in rules)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_rules_router.py -v`
Expected: FAIL (404, `/rules` not registered yet)

- [ ] **Step 5: Modify `app/main.py`** to include the rules router

```python
from app.routers import dashboard, rules, transactions
...
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(rules.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules_router.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/rules.py app/templates/rules.html app/main.py tests/test_rules_router.py
git commit -m "feat: add rules view with create-from-transaction shortcut"
```

---

### Task 13: Trends view

**Files:**
- Create: `app/routers/trends.py`
- Create: `app/templates/trends.html`
- Modify: `app/main.py`
- Test: `tests/test_trends_router.py`

**Interfaces:**
- Consumes: `compute_budget_period` (Task 5).
- Produces: `app/routers/trends.py:router` at `/trends`.

- [ ] **Step 1: Create `app/routers/trends.py`**

```python
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.budget_calc import compute_budget_period
from app.db import get_session

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")

MONTHS_BACK = 6


@router.get("")
def trends(request: Request, session: Session = Depends(get_session)):
    today = date.today()
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(MONTHS_BACK):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    months.reverse()

    labels = [f"{y}-{m:02d}" for y, m in months]
    series: dict[str, list[float]] = {}
    for y, m in months:
        periods = compute_budget_period(session, y, m)
        for period in periods:
            if period.limit_cents <= 0:
                continue
            series.setdefault(period.category_name, []).append(period.spent_cents / 100)

    return templates.TemplateResponse(request, "trends.html", {"labels": labels, "series": series})
```

- [ ] **Step 2: Create `app/templates/trends.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Spending trends (last {{ labels|length }} months)</h1>
<canvas id="trends-chart" height="100"></canvas>
<script>
const labels = {{ labels|tojson }};
const series = {{ series|tojson }};
const datasets = Object.entries(series).map(([name, data]) => ({ label: name, data }));
new Chart(document.getElementById("trends-chart"), {
    type: "line",
    data: { labels, datasets },
});
</script>
{% endblock %}
```

- [ ] **Step 3: Write the failing test — `tests/test_trends_router.py`**

```python
from datetime import date, datetime

from app.models import Account, Category, Transaction


def test_trends_includes_budgeted_category_series(session, client):
    account = Account(simplefin_account_id="acc-1", name="Checking", institution="Test Bank")
    category = Category(name="Groceries", monthly_limit_cents=30000)
    session.add(account)
    session.add(category)
    session.commit()
    session.refresh(account)
    session.refresh(category)

    today = date.today()
    session.add(
        Transaction(account_id=account.id, posted_at=datetime(today.year, today.month, 1), payee="Store",
                    amount_cents=-2000, category_id=category.id)
    )
    session.commit()

    response = client.get("/trends")

    assert response.status_code == 200
    assert "Groceries" in response.text
    assert f"{today.year}-{today.month:02d}" in response.text
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_trends_router.py -v`
Expected: FAIL (404, `/trends` not registered yet)

- [ ] **Step 5: Modify `app/main.py`** to include the trends router

```python
from app.routers import dashboard, rules, transactions, trends
...
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(trends.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_trends_router.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/trends.py app/templates/trends.html app/main.py tests/test_trends_router.py
git commit -m "feat: add spending trends view"
```

---

### Task 14: Settings view

**Files:**
- Create: `app/routers/settings.py`
- Create: `app/templates/settings.html`
- Modify: `app/main.py`
- Test: `tests/test_settings_router.py`

**Interfaces:**
- Consumes: `get_session`, `Category` model, `to_cents` (Task 2), `app.config.settings` (Task 9).
- Produces: `app/routers/settings.py:router` at `/settings`.

- [ ] **Step 1: Create `app/templates/settings.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Settings</h1>

<h2>SimpleFIN connection</h2>
<p>{{ "Configured" if simplefin_configured else "Not configured (set SIMPLEFIN_ACCESS_URL in .env and redeploy)" }}</p>

<h2>Notifications</h2>
<p>Warning threshold: {{ warning_threshold_pct }}% &middot; Alert threshold: {{ alert_threshold_pct }}% &middot; Digest: {{ digest_frequency }}</p>
<p><em>Edit these via the .env file and redeploy.</em></p>

<h2>Categories</h2>
<table>
<thead><tr><th>Name</th><th>Monthly limit</th></tr></thead>
<tbody>
{% for category in categories %}
<tr>
    <td>{{ category.name }}</td>
    <td>
        <form method="post" action="/settings/categories/{{ category.id }}" style="display:inline">
            <input name="monthly_limit" value="{{ "%.2f"|format(category.monthly_limit_cents / 100) }}" size="8">
            <button type="submit">Update</button>
        </form>
    </td>
</tr>
{% endfor %}
</tbody>
</table>

<h3>New category</h3>
<form method="post" action="/settings/categories">
    <input name="name" placeholder="e.g. Groceries" required>
    <input name="monthly_limit" placeholder="0.00" value="0.00">
    <button type="submit">Add category</button>
</form>
{% endblock %}
```

- [ ] **Step 2: Create `app/routers/settings.py`**

```python
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.config import settings as app_settings
from app.db import get_session
from app.models import Category
from app.money import to_cents

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_settings(request: Request, session: Session = Depends(get_session)):
    categories = session.exec(select(Category)).all()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "categories": categories,
            "simplefin_configured": bool(app_settings.simplefin_access_url),
            "warning_threshold_pct": app_settings.warning_threshold_pct,
            "alert_threshold_pct": app_settings.alert_threshold_pct,
            "digest_frequency": app_settings.digest_frequency,
        },
    )


@router.post("/categories")
def create_category(
    name: str = Form(...),
    monthly_limit: str = Form("0"),
    session: Session = Depends(get_session),
):
    session.add(Category(name=name, monthly_limit_cents=to_cents(Decimal(monthly_limit))))
    session.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/categories/{category_id}")
def update_category_limit(
    category_id: int,
    monthly_limit: str = Form(...),
    session: Session = Depends(get_session),
):
    category = session.get(Category, category_id)
    if category is not None:
        category.monthly_limit_cents = to_cents(Decimal(monthly_limit))
        session.add(category)
        session.commit()
    return RedirectResponse("/settings", status_code=303)
```

- [ ] **Step 3: Write the failing tests — `tests/test_settings_router.py`**

```python
from sqlmodel import select

from app.models import Category


def test_create_category_persists_limit_in_cents(session, client):
    response = client.post("/settings/categories", data={"name": "Groceries", "monthly_limit": "300.00"})
    assert response.status_code == 303

    category = session.exec(select(Category)).first()
    assert category.name == "Groceries"
    assert category.monthly_limit_cents == 30000


def test_update_category_limit_changes_existing_category(session, client):
    category = Category(name="Dining", monthly_limit_cents=10000)
    session.add(category)
    session.commit()
    session.refresh(category)

    response = client.post(f"/settings/categories/{category.id}", data={"monthly_limit": "150.50"})
    assert response.status_code == 303

    session.refresh(category)
    assert category.monthly_limit_cents == 15050


def test_settings_page_shows_simplefin_not_configured_by_default(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "Not configured" in response.text
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_router.py -v`
Expected: FAIL (404, `/settings` not registered yet)

- [ ] **Step 5: Modify `app/main.py`** to include the settings router

```python
from app.routers import dashboard, rules, settings as settings_router, transactions, trends
...
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(trends.router)
app.include_router(settings_router.router)
```

(Aliased to `settings_router` to avoid clashing with `app.config.settings`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_router.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/settings.py app/templates/settings.html app/main.py tests/test_settings_router.py
git commit -m "feat: add settings view for category limits"
```

---

### Task 15: CSV import fallback

**Files:**
- Create: `app/csv_import.py`
- Create: `app/routers/import_router.py`
- Create: `app/templates/import.html`
- Modify: `app/main.py`
- Test: `tests/test_csv_import.py`
- Test: `tests/test_import_router.py`

**Interfaces:**
- Consumes: `apply_rules` (Task 4), `to_cents` (Task 2), models (Task 3).
- Produces: `RawTransaction`, `CSVImportError`, `parse_csv(file_bytes: bytes) -> list[RawTransaction]`, `import_csv_transactions(session, account_id, rows) -> int`; router at `/import`.

- [ ] **Step 1: Write the failing tests — `tests/test_csv_import.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_csv_import.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.csv_import'`)

- [ ] **Step 3: Create `app/csv_import.py`**

```python
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
        rows.append(RawTransaction(posted_at=posted_at, payee=row["Description"].strip(), amount_cents=amount_cents))
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
        matched_rule = apply_rules(raw.payee, rules)
        session.add(
            Transaction(
                account_id=account_id,
                posted_at=raw.posted_at,
                payee=raw.payee,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_csv_import.py -v`
Expected: PASS

- [ ] **Step 5: Create `app/templates/import.html`**

```html
{% extends "base.html" %}
{% block content %}
<h1>Import CSV</h1>
<p>Expects columns: <code>Date</code> (YYYY-MM-DD), <code>Description</code>, <code>Amount</code>.</p>

{% if error %}<p style="color:#f44336">{{ error }}</p>{% endif %}
{% if result is not none %}<p>Imported {{ result }} new transaction(s).</p>{% endif %}

<form method="post" action="/import" enctype="multipart/form-data">
    <select name="account_id" required>
        {% for account in accounts %}
        <option value="{{ account.id }}">{{ account.name }}</option>
        {% endfor %}
    </select>
    <input type="file" name="file" accept=".csv" required>
    <button type="submit">Import</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Create `app/routers/import_router.py`**

```python
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.csv_import import CSVImportError, import_csv_transactions, parse_csv
from app.db import get_session
from app.models import Account

router = APIRouter(prefix="/import")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def show_import_form(request: Request, session: Session = Depends(get_session)):
    accounts = session.exec(select(Account)).all()
    return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": None, "error": None})


@router.post("")
def import_csv(
    request: Request,
    account_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    accounts = session.exec(select(Account)).all()
    try:
        rows = parse_csv(file.file.read())
        inserted = import_csv_transactions(session, account_id, rows)
        return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": inserted, "error": None})
    except CSVImportError as exc:
        return templates.TemplateResponse(request, "import.html", {"accounts": accounts, "result": None, "error": str(exc)})
```

- [ ] **Step 7: Write the failing test — `tests/test_import_router.py`**

```python
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
```

- [ ] **Step 8: Run test to verify it fails**

Run: `python -m pytest tests/test_import_router.py -v`
Expected: FAIL (404, `/import` not registered yet)

- [ ] **Step 9: Modify `app/main.py`** to include the import router

```python
from app.routers import dashboard, import_router, rules, settings as settings_router, transactions, trends
...
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(rules.router)
app.include_router(trends.router)
app.include_router(settings_router.router)
app.include_router(import_router.router)
```

- [ ] **Step 10: Run test to verify it passes**

Run: `python -m pytest tests/test_import_router.py -v`
Expected: PASS

- [ ] **Step 11: Run the full test suite**

Run: `python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 12: Commit**

```bash
git add app/csv_import.py app/routers/import_router.py app/templates/import.html app/main.py tests/test_csv_import.py tests/test_import_router.py
git commit -m "feat: add CSV import fallback for accounts outside SimpleFIN"
```

---

### Task 16: Docker packaging and deployment verification

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: the finished `app/` package and `requirements.txt` from all prior tasks.
- Produces: a runnable container image exposing port 8000.

- [ ] **Step 1: Create `.dockerignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
.env
tests/
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  budget-tracker:
    build: .
    container_name: budget-tracker
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    env_file:
      - .env
```

- [ ] **Step 4: Build the image**

Run: `docker build -t budget-tracker:local .`
Expected: build completes with no errors

- [ ] **Step 5: Run the container and verify the health check**

Run:
```bash
docker run -d --name budget-tracker-test -p 8000:8000 budget-tracker:local
sleep 2
curl -s http://localhost:8000/health
```
Expected output: `{"status":"ok"}`

- [ ] **Step 6: Stop and remove the test container**

Run: `docker stop budget-tracker-test && docker rm budget-tracker-test`

- [ ] **Step 7: Copy `.env.example` to `.env` and fill in real values**

Run: `cp .env.example .env`, then edit `.env` with your actual SimpleFIN access URL and SMTP credentials (this file is gitignored and must not be committed).

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "chore: add Docker packaging for deployment"
```

---

## Manual Verification Checklist (post-implementation)

Run through these by hand in a browser once all tasks are complete — they cover the UI polish and real-integration aspects automated tests don't reach:

- [ ] Obtain a real SimpleFIN setup token from a linked bank, exchange it for an access URL, set `SIMPLEFIN_ACCESS_URL` in `.env`, and confirm `daily_sync_job` pulls real transactions on the next scheduled run (or trigger it manually via a Python shell: `from app.jobs import daily_sync_job; from app.config import settings; from app.db import engine; daily_sync_job(settings, engine)`)
- [ ] Confirm SMTP credentials work by triggering `digest_job` the same way and checking the inbox
- [ ] Open the dashboard on a phone over Tailscale (not on home WiFi) and confirm it loads and is usable at that width
- [ ] Walk through: create a category with a limit, create a matching rule, re-sync, confirm a transaction gets auto-categorized and the home page progress bar updates
- [ ] Manually recategorize a transaction from the Transactions page and confirm the row updates without a full page reload (HTMX)
- [ ] Upload a CSV export from your bank and confirm the columns match what `parse_csv` expects; adjust the parser if your bank's export format differs from `Date,Description,Amount`
