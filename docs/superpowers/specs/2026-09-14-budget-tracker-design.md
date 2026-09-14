# Budget Tracker & Finance Dashboard — Design Spec

Date: 2026-09-14
Status: Approved for implementation planning

## Problem

The user currently tracks spending in an Excel spreadsheet, manually
transcribing transactions from bank statements. This is time-consuming,
error-prone, and the friction causes the habit to lapse. The goal is a
low-friction, self-hosted system that automatically pulls bank
transactions, categorizes them, tracks spending against monthly budget
limits, and proactively alerts the user when they're off track — so
staying on budget requires near-zero manual effort.

## Goals

- Automatically ingest bank transactions with minimal manual entry
- Categorize transactions via user-defined rules, with a clear
  "Uncategorized" queue for anything unmatched
- Track spending against per-category monthly budget limits
- Proactively alert on overspending and provide periodic digests
- Run entirely on the user's existing home infrastructure, accessible
  from anywhere via Tailscale, with financial data staying under the
  user's control

## Non-goals

- Multi-user / shared household budgeting (single user only)
- Envelope/zero-based budgeting methodology
- Investment tracking, bill-pay, or money movement of any kind
  (read-only transaction data only)
- Mobile native app (responsive web dashboard only)

## Context & constraints

- User has an existing Proxmox homelab with Tailscale already running
  as a subnet router (LAN is reachable over the tailnet without a
  per-service Tailscale sidecar)
- Deployment target: a Docker container on whichever LXC/VM already
  hosts the user's other Docker workloads
- Single user, a handful of bank/card accounts

## Bank data source: SimpleFIN

Evaluated Plaid, Teller.io, and SimpleFIN:

- **Plaid**: industry standard, broadest bank coverage, but designed
  for commercial products — production access requires a sales-led
  approval process and per-account pricing. Poor fit for a personal,
  single-user tool.
- **Teller.io**: free tier up to 100 live connections, developer
  friendly, but a general indie-fintech platform whose personal-use
  terms could shift over time.
- **SimpleFIN** (chosen): $15/year flat, read-only, purpose-built for
  personal/DIY finance tools (used by Actual Budget, Firefly III).
  Rate limit of ~24 requests/day per account, which comfortably
  supports once-daily automated sync plus occasional manual
  "sync now" requests.

A CSV import fallback is included for any account SimpleFIN doesn't
support, or one-off statement imports, reusing the same categorization
pipeline as the automated sync.

## Architecture

Single Docker container running a Python/FastAPI application, deployed
on the user's existing Proxmox Docker host, reachable at its LAN IP
over the existing Tailscale subnet router — no additional Tailscale
sidecar needed.

```
┌─────────────────────────────────────────────┐
│  Docker container (Proxmox Docker host)      │
│                                               │
│  FastAPI app                                 │
│   ├─ Web dashboard (HTMX + Chart.js)         │
│   ├─ REST endpoints (rules, budgets, etc.)   │
│   └─ In-process scheduler (APScheduler)      │
│        ├─ Daily: pull transactions from      │
│        │   SimpleFIN, apply rules,           │
│        │   check budgets, send alerts        │
│        └─ Daily/weekly: digest email         │
│                                               │
│  SQLite database (volume-mounted, survives   │
│  container restarts/rebuilds)                │
└───────────────┬───────────────────────────────┘
                │ HTTPS
        ┌───────┴────────┐         ┌─────────────┐
        │ SimpleFIN Bridge │         │ SMTP relay  │
        │ (bank data)      │         │ (email)     │
        └──────────────────┘         └─────────────┘
```

### Why this stack

Python + FastAPI + HTMX + SQLite was chosen over a Next.js/TypeScript
stack or a Go/HTMX stack because it minimizes long-term maintenance
for a solo-maintained homelab service: no separate frontend build
pipeline, no second deploy artifact, one container, one data file to
back up. HTMX + Chart.js provides a dynamic-feeling dashboard without
a JS framework. SQLite is sufficient (and simpler to operate/back up)
for a single-user, low-write-volume workload.

## Data model

- **Account** — synced bank/card account: name, type, institution,
  SimpleFIN account id, current balance
- **Transaction** — date, payee/description, amount, account,
  pending/posted status, SimpleFIN transaction id (dedup key),
  nullable `category_id` (null = Uncategorized), nullable
  `rule_applied_id` (audit trail)
- **Category** — name, optional parent category (for grouping, e.g.
  Food → Groceries/Dining), monthly budget limit
- **Rule** — match condition (payee contains/equals/regex, optional
  amount range or account filter), target category, priority order
  (first match wins)
- **BudgetPeriod** — computed on read from Category limits +
  Transactions for a given month; not persisted, so editing a limit
  never rewrites history
- **AlertLog** — records which category/month/threshold combinations
  have already triggered an alert, to prevent duplicate notifications

### Categorization flow

On each sync, new transactions are run through Rules in priority
order; the first match sets `category_id`. No match leaves the
transaction Uncategorized, surfaced prominently on the dashboard as an
action queue. Transactions can be recategorized manually at any time,
with a one-click "create a rule from this transaction" shortcut so
future similar transactions auto-categorize.

## Sync & alerting flow

**Daily sync job** (in-process APScheduler, ~6am default):

1. Pull new transactions per account from SimpleFIN
2. Dedup against stored `simplefin_transaction_id`s; insert new ones
3. Run categorization rules against new transactions
4. Recompute month-to-date spend per category vs. limit
5. For any category crossing its alert threshold (default: 100%,
   configurable, e.g. an 80% warning) for the first time in the
   current month, write an AlertLog entry and send an email alert
6. Refresh account balances shown on the dashboard

**Digest job** (in-process APScheduler, daily or weekly per user
preference): sends one email summarizing spend-vs-budget across all
categories, regardless of threshold crossings.

**Notification channel**: SMTP email for both instant over-budget
alerts and periodic digests (no separate push-notification service
required — one less container to operate).

## Dashboard

- **Home**: current month, per-category progress bars (spent/limit,
  color-coded), total income vs. spend, account balances
- **Transactions**: filterable/sortable list, inline recategorize via
  HTMX, "Uncategorized" filter surfaced as the primary action queue
- **Rules**: list/create/edit rules; "create rule from transaction"
  shortcut
- **Trends**: category spend over the past N months (Chart.js)
- **Settings**: category limits, SimpleFIN connection management,
  notification thresholds and digest frequency

## Error handling

- **Sync failures** (SimpleFIN down, token expired, rate-limited):
  logged; dashboard shows a "last synced X ago / sync failed" banner
  rather than silently showing stale data as current
- **Duplicate/pending transactions**: deduped by SimpleFIN transaction
  id; pending transactions shown distinctly and reconciled when they
  post
- **CSV import fallback**: reuses the same categorization pipeline as
  automated sync, for accounts SimpleFIN doesn't support or one-off
  statement imports

## Testing strategy

- Unit tests for the rules engine and budget-calculation logic (the
  areas where a bug would silently corrupt financial data)
- Integration test for the sync pipeline against SimpleFIN's
  sandbox/demo data
- Manual verification for the dashboard UI

## Open items for implementation planning

- Exact SimpleFIN setup steps (account linking via their bridge UI,
  token storage)
- SMTP provider/credentials the user wants to use for sending email
- Default budget category set (or start empty and let the user define
  their own)
