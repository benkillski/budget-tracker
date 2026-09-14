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
