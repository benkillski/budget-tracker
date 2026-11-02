from unittest.mock import MagicMock, patch

from app.budget_calc import CategoryIncome, CategorySpend
from app.notifications import DigestContent, SMTPConfig, send_alert_email, send_digest_email
from app.sync_service import ThresholdCrossing

CONFIG = SMTPConfig(
    host="smtp.example.com", port=587, username="user@example.com",
    password="secret", from_addr="user@example.com", to_addr="user@example.com",
)


def _text_body(message) -> str:
    """Extract the text/plain part of a multipart message."""
    part = message.get_body(preferencelist=("plain",))
    return part.get_content() if part is not None else ""


def _html_body(message) -> str:
    """Extract the text/html part of a multipart message."""
    part = message.get_body(preferencelist=("html",))
    return part.get_content() if part is not None else ""


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
    text = _text_body(sent_message)
    assert "$35.00" in text
    assert "$30.00" in text


@patch("app.notifications.smtplib.SMTP")
def test_send_digest_email_lists_only_budgeted_categories(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = DigestContent(
        periods=[
            CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),
            CategorySpend(category_id=2, category_name="Unbudgeted", limit_cents=0, spent_cents=500),
        ],
    )

    send_digest_email(CONFIG, content)

    sent_message = mock_smtp.send_message.call_args[0][0]
    text = _text_body(sent_message)
    assert "Groceries" in text
    assert "Unbudgeted" not in text


@patch("app.notifications.smtplib.SMTP")
def test_send_digest_email_groups_by_status_in_text_and_html(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = DigestContent(
        periods=[
            CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),  # 50% on track
            CategorySpend(category_id=2, category_name="Dining", limit_cents=2000, spent_cents=1800),    # 90% approaching
            CategorySpend(category_id=3, category_name="Rent", limit_cents=100000, spent_cents=120000),  # 120% over
        ],
        incomes=[CategoryIncome(category_id=10, category_name="Salary", received_cents=500000)],
        uncategorized_count=3,
        month_label="November 2026",
    )

    send_digest_email(CONFIG, content)

    sent_message = mock_smtp.send_message.call_args[0][0]
    # Subject surfaces the over-count and the month label
    assert "November 2026" in sent_message["Subject"]
    assert "1 over budget" in sent_message["Subject"]

    text = _text_body(sent_message)
    # Section headers
    assert "Over budget (1)" in text
    assert "Approaching limit (1)" in text
    assert "On track (1)" in text
    # Summary numbers
    assert "$5,000.00" in text  # income
    assert "Uncategorized transactions: 3" in text

    html = _html_body(sent_message)
    assert "Over budget" in html
    assert "Approaching limit" in html
    assert "On track" in html
    assert "3</strong> transaction" in html  # uncategorized banner


@patch("app.notifications.smtplib.SMTP")
def test_send_digest_email_subject_omits_over_count_when_none(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = DigestContent(
        periods=[CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500)],
        month_label="November 2026",
    )

    send_digest_email(CONFIG, content)

    sent_message = mock_smtp.send_message.call_args[0][0]
    assert "over budget" not in sent_message["Subject"].lower()


@patch("app.notifications.smtplib.SMTP")
def test_send_alert_email_includes_html_alternative(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    crossing = ThresholdCrossing(
        category_id=1, category_name="Groceries", threshold_pct=100,
        spent_cents=3500, limit_cents=3000,
    )

    send_alert_email(CONFIG, crossing)

    sent_message = mock_smtp.send_message.call_args[0][0]
    html = _html_body(sent_message)
    assert "Groceries" in html
    assert "$35.00" in html
    assert "$30.00" in html
    # Over by $5.00 — the alert surfaces this amount.
    assert "$5.00" in html
    # Inline styles present (we use color on the % number).
    assert "color:#dc2626" in html


@patch("app.notifications.smtplib.SMTP")
def test_send_digest_email_includes_html_alternative(mock_smtp_class):
    mock_smtp = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp
    content = DigestContent(
        periods=[
            CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),
            CategorySpend(category_id=2, category_name="Dining", limit_cents=2000, spent_cents=2500),
        ],
    )

    send_digest_email(CONFIG, content)

    sent_message = mock_smtp.send_message.call_args[0][0]
    html = _html_body(sent_message)
    assert "Groceries" in html
    assert "Dining" in html
    # Dining is at 125% — rendered red.
    assert "color:#dc2626" in html
    # Groceries at 50% — rendered green.
    assert "color:#16a34a" in html
