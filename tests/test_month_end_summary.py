from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.budget_calc import CategoryIncome, CategorySpend, previous_month
from app.config import Settings
from app.jobs import build_month_end_summary, month_end_summary_job
from app.models import Account, Category, MonthEndSummaryLog, Transaction
from app.notifications import (
    MonthEndSummary,
    SMTPConfig,
    send_month_end_summary_email,
)

CONFIG = SMTPConfig(
    host="smtp.example.com", port=587, username="user@example.com",
    password="secret", from_addr="user@example.com", to_addr="user@example.com",
)


def _text_body(message) -> str:
    part = message.get_body(preferencelist=("plain",))
    return part.get_content() if part is not None else ""


def _html_body(message) -> str:
    part = message.get_body(preferencelist=("html",))
    return part.get_content() if part is not None else ""


def _make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


# ----- previous_month ---------------------------------------------------------

def test_previous_month_within_year():
    assert previous_month(2026, 11) == (2026, 10)


def test_previous_month_wraps_january_to_prior_december():
    assert previous_month(2026, 1) == (2025, 12)


# ----- MonthEndSummary derived properties -------------------------------------

def _summary(**overrides) -> MonthEndSummary:
    defaults = dict(year=2026, month=10, periods=[], month_label="October 2026")
    defaults.update(overrides)
    return MonthEndSummary(**defaults)


def test_biggest_category_picks_largest_spender():
    s = _summary(periods=[
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=30000, spent_cents=15000),
        CategorySpend(category_id=2, category_name="Rent", limit_cents=100000, spent_cents=95000),
        CategorySpend(category_id=3, category_name="Dining", limit_cents=20000, spent_cents=8000),
    ])
    assert s.biggest_category.category_name == "Rent"


def test_biggest_category_is_none_when_no_spend():
    s = _summary(periods=[
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=30000, spent_cents=0),
    ])
    assert s.biggest_category is None


def test_biggest_overage_picks_largest_dollar_amount_over_limit():
    s = _summary(periods=[
        # Dining is a bigger % over, but Rent is a bigger $ over.
        CategorySpend(category_id=1, category_name="Dining", limit_cents=10000, spent_cents=15000),  # +$50
        CategorySpend(category_id=2, category_name="Rent", limit_cents=100000, spent_cents=110000),  # +$100
    ])
    assert s.biggest_overage.category_name == "Rent"


def test_biggest_overage_is_none_when_nothing_over():
    s = _summary(periods=[
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=30000, spent_cents=15000),
    ])
    assert s.biggest_overage is None


def test_missed_fixed_bills_are_fixed_categories_with_limit_and_zero_spend():
    s = _summary(periods=[
        CategorySpend(category_id=1, category_name="Rent", limit_cents=100000, spent_cents=0, is_fixed=True),
        CategorySpend(category_id=2, category_name="Phone", limit_cents=5000, spent_cents=5000, is_fixed=True),
        CategorySpend(category_id=3, category_name="Insurance", limit_cents=15000, spent_cents=0, is_fixed=True),
        CategorySpend(category_id=4, category_name="Groceries", limit_cents=30000, spent_cents=0, is_fixed=False),
    ])
    names = [p.category_name for p in s.missed_fixed_bills]
    assert names == ["Insurance", "Rent"]


# ----- send_month_end_summary_email ------------------------------------------

@patch("app.notifications.smtplib.SMTP")
def test_subject_includes_month_label_and_net_amount(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = MonthEndSummary(
        year=2026, month=10, month_label="October 2026",
        periods=[CategorySpend(category_id=1, category_name="Rent", limit_cents=100000, spent_cents=100000)],
        incomes=[CategoryIncome(category_id=10, category_name="Salary", received_cents=500000)],
    )

    send_month_end_summary_email(CONFIG, content)

    sent = mock_smtp.send_message.call_args[0][0]
    assert "October 2026" in sent["Subject"]
    # net = 5000 - 1000 = +4000 → "+$4,000.00"
    assert "+$4,000.00" in sent["Subject"]
    assert "Budget recap" in sent["Subject"]


@patch("app.notifications.smtplib.SMTP")
def test_subject_shows_negative_net_without_plus_sign(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = MonthEndSummary(
        year=2026, month=10, month_label="October 2026",
        periods=[CategorySpend(category_id=1, category_name="Rent", limit_cents=100000, spent_cents=600000)],
        incomes=[CategoryIncome(category_id=10, category_name="Salary", received_cents=500000)],
    )

    send_month_end_summary_email(CONFIG, content)

    sent = mock_smtp.send_message.call_args[0][0]
    # net = 5000 - 6000 = -1000 → "-$1,000.00" with no leading plus
    assert "-$1,000.00" in sent["Subject"]
    assert "+-" not in sent["Subject"]


@patch("app.notifications.smtplib.SMTP")
def test_test_mode_prefixes_subject(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = MonthEndSummary(year=2026, month=10, month_label="October 2026", periods=[])

    send_month_end_summary_email(CONFIG, content, test=True)

    sent = mock_smtp.send_message.call_args[0][0]
    assert sent["Subject"].startswith("[TEST] ")


@patch("app.notifications.smtplib.SMTP")
def test_body_surfaces_biggest_category_and_missed_bills(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = MonthEndSummary(
        year=2026, month=10, month_label="October 2026",
        periods=[
            CategorySpend(category_id=1, category_name="Rent", limit_cents=100000, spent_cents=100000, is_fixed=True),
            CategorySpend(category_id=2, category_name="Insurance", limit_cents=15000, spent_cents=0, is_fixed=True),
            CategorySpend(category_id=3, category_name="Groceries", limit_cents=30000, spent_cents=40000),
        ],
    )

    send_month_end_summary_email(CONFIG, content)

    sent = mock_smtp.send_message.call_args[0][0]
    text = _text_body(sent)
    assert "Biggest category: Rent" in text
    assert "Biggest overage: Groceries" in text
    assert "over by $100.00" in text
    assert "Insurance" in text  # listed as missed fixed bill

    html = _html_body(sent)
    assert "Rent" in html
    assert "Insurance" in html
    assert "may be worth checking" in html


@patch("app.notifications.smtplib.SMTP")
def test_body_omits_highlights_block_when_nothing_to_show(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    # No spending at all, no fixed bills — highlight panel should be absent.
    content = MonthEndSummary(year=2026, month=10, month_label="October 2026", periods=[])

    send_month_end_summary_email(CONFIG, content)

    sent = mock_smtp.send_message.call_args[0][0]
    text = _text_body(sent)
    assert "Biggest category" not in text
    assert "Biggest overage" not in text
    assert "Fixed bills" not in text
    html = _html_body(sent)
    assert "may be worth checking" not in html


# ----- build_month_end_summary -----------------------------------------------

def test_build_month_end_summary_counts_uncategorized_only_in_target_month():
    engine = _make_engine()
    with Session(engine) as session:
        account = Account(simplefin_account_id="a1", name="Checking", institution="Bank")
        session.add(account)
        session.commit()
        session.refresh(account)

        # October — uncategorized (should count)
        session.add(Transaction(account_id=account.id, posted_at=datetime(2026, 10, 15),
                                payee="Mystery A", amount_cents=-500))
        # October — categorized (shouldn't count)
        cat = Category(name="Dining", monthly_limit_cents=10000)
        session.add(cat)
        session.commit()
        session.refresh(cat)
        session.add(Transaction(account_id=account.id, posted_at=datetime(2026, 10, 20),
                                payee="Chipotle", amount_cents=-1500, category_id=cat.id))
        # November — uncategorized (outside target month)
        session.add(Transaction(account_id=account.id, posted_at=datetime(2026, 11, 2),
                                payee="Mystery B", amount_cents=-800))
        session.commit()

        summary = build_month_end_summary(session, 2026, 10)
        assert summary.uncategorized_count == 1


# ----- month_end_summary_job --------------------------------------------------

@patch("app.jobs.send_month_end_summary_email")
@patch("app.jobs.utc_now")
def test_month_end_summary_job_sends_for_prior_month_and_logs(mock_utc_now, mock_send):
    # November 5, 2026 → should send for October 2026.
    mock_utc_now.return_value = datetime(2026, 11, 5, 11, 30)
    engine = _make_engine()
    settings = Settings()

    month_end_summary_job(settings, engine)

    mock_send.assert_called_once()
    summary = mock_send.call_args[0][1]
    assert summary.year == 2026
    assert summary.month == 10

    with Session(engine) as session:
        log = session.exec(select(MonthEndSummaryLog)).first()
        assert log is not None
        assert log.year == 2026 and log.month == 10


@patch("app.jobs.send_month_end_summary_email")
@patch("app.jobs.utc_now")
def test_month_end_summary_job_skips_when_already_sent(mock_utc_now, mock_send):
    mock_utc_now.return_value = datetime(2026, 11, 5, 11, 30)
    engine = _make_engine()
    with Session(engine) as session:
        session.add(MonthEndSummaryLog(year=2026, month=10, sent_at=datetime(2026, 11, 5, 11, 30)))
        session.commit()
    settings = Settings()

    month_end_summary_job(settings, engine)

    mock_send.assert_not_called()


@patch("app.jobs.send_month_end_summary_email")
@patch("app.jobs.utc_now")
def test_month_end_summary_job_wraps_january_to_december(mock_utc_now, mock_send):
    # January 5, 2027 → should send for December 2026.
    mock_utc_now.return_value = datetime(2027, 1, 5, 11, 30)
    engine = _make_engine()
    settings = Settings()

    month_end_summary_job(settings, engine)

    summary = mock_send.call_args[0][1]
    assert summary.year == 2026
    assert summary.month == 12


@patch("app.jobs.send_month_end_summary_email")
@patch("app.jobs.utc_now")
def test_month_end_summary_job_does_not_log_on_smtp_failure(mock_utc_now, mock_send):
    mock_utc_now.return_value = datetime(2026, 11, 5, 11, 30)
    mock_send.side_effect = RuntimeError("SMTP down")
    engine = _make_engine()
    settings = Settings()

    try:
        month_end_summary_job(settings, engine)
    except RuntimeError:
        pass

    with Session(engine) as session:
        log = session.exec(select(MonthEndSummaryLog)).first()
        assert log is None  # dedupe log not written — next run will retry
