import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.budget_calc import CategoryIncome, CategorySpend
from app.money import format_money
from app.sync_service import ThresholdCrossing

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
_env.globals["format_money"] = format_money


@dataclass
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    to_addr: str


@dataclass
class RecentTransaction:
    """Slim snapshot of a transaction for display in alert emails. Carries
    just what the template needs so we don't drag ORM state into the email path."""

    posted_at_label: str  # "2026-11-02"
    payee: str
    amount_cents: int


@dataclass
class AlertContext:
    """Everything an enriched alert email needs: the crossing, recent
    transactions that pushed into the threshold, and projection math."""

    crossing: ThresholdCrossing
    recent_transactions: list[RecentTransaction] = field(default_factory=list)
    days_elapsed: int = 1
    days_in_month: int = 30

    @property
    def days_remaining(self) -> int:
        return max(0, self.days_in_month - self.days_elapsed)

    @property
    def projected_cents(self) -> int:
        """Linear extrapolation of current pace to end of month."""
        if self.days_elapsed <= 0:
            return self.crossing.spent_cents
        return int(self.crossing.spent_cents / self.days_elapsed * self.days_in_month)

    @property
    def projected_pct(self) -> float:
        if self.crossing.limit_cents <= 0:
            return 0.0
        return self.projected_cents / self.crossing.limit_cents * 100

    @property
    def over_by_cents(self) -> int:
        return self.crossing.spent_cents - self.crossing.limit_cents


@dataclass
class DigestContent:
    """Snapshot of a month's budget state assembled by digest_job and consumed
    by send_digest_email. Carries both the raw periods list and summary stats
    so the template can group by over/warn/on-track and show totals."""

    periods: list[CategorySpend]
    incomes: list[CategoryIncome] = field(default_factory=list)
    uncategorized_count: int = 0
    month_label: str = ""

    @property
    def total_spent_cents(self) -> int:
        return sum(p.spent_cents for p in self.periods)

    @property
    def total_income_cents(self) -> int:
        return sum(i.received_cents for i in self.incomes)

    @property
    def net_cents(self) -> int:
        return self.total_income_cents - self.total_spent_cents

    @property
    def budgeted(self) -> list[CategorySpend]:
        """Only periods with a non-zero limit; what the digest actually renders."""
        return [p for p in self.periods if p.limit_cents > 0]

    @property
    def over_budget(self) -> list[CategorySpend]:
        return sorted(
            (p for p in self.budgeted if p.pct_used >= 100),
            key=lambda p: p.pct_used,
            reverse=True,
        )

    @property
    def approaching(self) -> list[CategorySpend]:
        return sorted(
            (p for p in self.budgeted if 80 <= p.pct_used < 100),
            key=lambda p: p.pct_used,
            reverse=True,
        )

    @property
    def on_track(self) -> list[CategorySpend]:
        return sorted(
            (p for p in self.budgeted if p.pct_used < 80),
            key=lambda p: p.category_name,
        )

    @property
    def over_count(self) -> int:
        return len(self.over_budget)


def _render_html(template_name: str, context: dict) -> str:
    """Render an email HTML template under app/templates/email/."""
    template = _env.get_template(f"email/{template_name}")
    return template.render(**context)


def _send(config: SMTPConfig, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send an email. If html_body is provided, send multipart (text + HTML).
    Email clients that can render HTML will show that; others fall back to text."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_addr
    message["To"] = config.to_addr
    message.set_content(text_body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(config.host, config.port) as smtp:
        smtp.starttls()
        smtp.login(config.username, config.password)
        smtp.send_message(message)


def send_sync_failure_email(config: SMTPConfig, error_message: str) -> None:
    subject = "Budget Tracker: sync failed"
    text_body = (
        "The scheduled SimpleFIN sync failed. New transactions have not been pulled since.\n\n"
        f"Error: {error_message}\n\n"
        "Try 'Sync now' on the Settings page to diagnose, or check the dashboard for the last successful sync time.\n"
        "You won't get another sync-failure email for 24 hours unless the sync starts working again first.\n"
    )
    html_body = _render_html("sync_failure.html", {"error_message": error_message})
    _send(config, subject, text_body, html_body)


def send_sync_recovery_email(config: SMTPConfig, last_error: str | None = None) -> None:
    subject = "Budget Tracker: sync is working again"
    text_body = "The SimpleFIN sync just completed successfully. New transactions are being pulled again.\n"
    if last_error:
        text_body += f"\nPrevious error: {last_error}\n"
    html_body = _render_html("sync_recovery.html", {"last_error": last_error})
    _send(config, subject, text_body, html_body)


def send_alert_email(config: SMTPConfig, context: AlertContext) -> None:
    crossing = context.crossing
    subject = f"Budget alert: {crossing.category_name} at {crossing.threshold_pct}%"
    text_body = _render_alert_text(context)
    html_body = _render_html("alert.html", {"c": context})
    _send(config, subject, text_body, html_body)


def _render_alert_text(c: AlertContext) -> str:
    """Plain text fallback for alert emails — same information as the HTML."""
    crossing = c.crossing
    lines = [
        f"{crossing.category_name} has reached {crossing.threshold_pct}% of its monthly budget.",
        "",
        f"Spent:   {format_money(crossing.spent_cents)}",
        f"Limit:   {format_money(crossing.limit_cents)}",
    ]
    if c.over_by_cents > 0:
        lines.append(f"Over by: {format_money(c.over_by_cents)}")
    lines.append("")
    if c.projected_cents and c.days_elapsed > 0:
        lines.append(
            f"At this pace, you'll finish the month at {format_money(c.projected_cents)} "
            f"({c.projected_pct:.0f}%)."
        )
    lines.append(f"{c.days_remaining} day{'s' if c.days_remaining != 1 else ''} left in the budget period.")

    if c.recent_transactions:
        lines.append("")
        lines.append("Recent transactions this month:")
        for t in c.recent_transactions:
            lines.append(f"  {t.posted_at_label}  {t.payee} — {format_money(t.amount_cents)}")

    return "\n".join(lines) + "\n"


def send_digest_email(config: SMTPConfig, content: DigestContent) -> None:
    # Subject line surfaces the over-budget count so a scan of the inbox tells
    # you whether to open it.
    label = content.month_label or "digest"
    if content.over_count:
        suffix = f" — {content.over_count} over budget"
    else:
        suffix = ""
    subject = f"Budget digest ({label}){suffix}"

    html_body = _render_html("digest.html", {"c": content})
    text_body = _render_digest_text(content)
    _send(config, subject, text_body, html_body)


def _render_digest_text(c: DigestContent) -> str:
    """Plain text fallback — same information as the HTML digest, laid out
    for a terminal mail client."""
    lines = []
    if c.month_label:
        lines.append(c.month_label)
        lines.append("=" * len(c.month_label))
        lines.append("")

    lines.append("Summary")
    lines.append(f"  Income: {format_money(c.total_income_cents)}")
    lines.append(f"  Spent:  {format_money(c.total_spent_cents)}")
    lines.append(f"  Net:    {format_money(c.net_cents)}")
    if c.uncategorized_count:
        lines.append(f"  Uncategorized transactions: {c.uncategorized_count}")
    lines.append("")

    def _fmt(p: CategorySpend) -> str:
        return (
            f"  {p.category_name}: {format_money(p.spent_cents)} / "
            f"{format_money(p.limit_cents)} ({p.pct_used:.0f}%)"
        )

    if c.over_budget:
        lines.append(f"Over budget ({len(c.over_budget)})")
        lines.extend(_fmt(p) for p in c.over_budget)
        lines.append("")
    if c.approaching:
        lines.append(f"Approaching limit ({len(c.approaching)})")
        lines.extend(_fmt(p) for p in c.approaching)
        lines.append("")
    if c.on_track:
        lines.append(f"On track ({len(c.on_track)})")
        lines.extend(_fmt(p) for p in c.on_track)
        lines.append("")

    if not c.budgeted:
        lines.append("No budgeted categories yet.")

    return "\n".join(lines).rstrip() + "\n"
