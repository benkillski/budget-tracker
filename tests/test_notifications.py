from unittest.mock import MagicMock, patch

from app.budget_calc import CategorySpend
from app.notifications import SMTPConfig, send_alert_email, send_digest_email
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
    periods = [
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),
        CategorySpend(category_id=2, category_name="Unbudgeted", limit_cents=0, spent_cents=500),
    ]

    send_digest_email(CONFIG, periods)

    sent_message = mock_smtp.send_message.call_args[0][0]
    text = _text_body(sent_message)
    assert "Groceries" in text
    assert "Unbudgeted" not in text


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
    periods = [
        CategorySpend(category_id=1, category_name="Groceries", limit_cents=3000, spent_cents=1500),
        CategorySpend(category_id=2, category_name="Dining", limit_cents=2000, spent_cents=2500),
    ]

    send_digest_email(CONFIG, periods)

    sent_message = mock_smtp.send_message.call_args[0][0]
    html = _html_body(sent_message)
    assert "Groceries" in html
    assert "Dining" in html
    # Dining is at 125% — rendered red.
    assert "color:#dc2626" in html
    # Groceries at 50% — rendered green.
    assert "color:#16a34a" in html
