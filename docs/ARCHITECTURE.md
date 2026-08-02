# Architecture

This document describes the architecture implemented by the repository. Product
ideas that are not implemented belong in [Future improvements](FUTURE_IMPROVEMENTS.md),
not in this document.

## System context

The bot imports financial activity from three Discord workflows into an Actual
Budget account:

```text
Android bank notification -> Discord message -----> notification handler --+
                                                                         |
Receipt image -> Discord attachment -> image preprocessing -> Tesseract --+--> Actual Budget
Receipt PDF ---> Discord attachment -> PDF text extraction --------------+        |
                                      -> receipt parser -> split transaction -----+
Bank CSV ------> Discord attachment -> bank2ynab worker -> date filter -----------+
```

Bank notifications are forwarded to Discord by an external Android Automate
flow. Receipt images and PDFs are posted directly by users. Discord is the
transport and user-feedback layer; parsing and Actual Budget persistence remain
separate from it.

## Composition and ownership

`actual_discord_bot.bot.main()` is the composition root. It reads environment
configuration and creates one of each shared dependency:

```text
main()
  |-- ActualConnector -------------------+--------------------------+
  |-- shared asyncio write lock ---------+--------------------------+
  |-- NotificationChannelHandler <-------+                          |
  |-- optional BankImportChannelHandler <-+                          |
  |-- ReceiptProcessor                                              |
  |-- ReceiptChannelHandler <-------------- ReceiptProcessor -------+
  `-- ActualDiscordBot
        |-- notification handler
        `-- optional receipt handler
```

The main components have deliberately narrow responsibilities:

- `ActualDiscordBot` owns the Discord lifecycle, commands, and message routing.
- `BaseChannelHandler` owns configured-channel binding and startup help shared
  by every channel workflow.
- `NotificationChannelHandler` owns bank-message parsing, notification imports,
  success reactions, catch-up processing, and creation of recurring schedules
  from successful notification replies.
- `ReceiptChannelHandler` owns attachment selection and limits, Discord
  reactions/replies, receipt-processing concurrency, and receipt persistence.
- `BankImportChannelHandler` owns statement attachment/caption validation,
  account-selection prompts, reactions/replies, conversion concurrency, and
  calls to the Actual import boundary. It does not parse bank-specific columns.
- `ReceiptProcessor` is independent of Discord. It selects OCR or PDF text
  extraction, invokes the parser, supplies a fallback date, and validates item
  totals.
- `ActualConnector` is the boundary around `actualpy` sessions, transaction
  creation, deduplication, and commits.

Dependencies are constructed once and injected into consumers. Channel handlers
do not read environment variables or construct their own connectors or parsing
pipelines.

## Discord routing and lifecycle

At startup, every enabled handler independently searches all guilds and binds to
the first text channel with its configured name. A handler posts its own guide
unless the same guide is present in the last ten messages, and it sends a guide
at most once per process.

For each message, the bot:

1. ignores messages authored by itself;
2. builds command context and gives valid commands precedence;
3. considers handlers whose bound channel matches the message channel;
4. dispatches to the first handler that accepts the message.

Bank CSV handling is ordered before receipt and notification handling. Receipt
handling is ordered before notifications. If workflows share a channel, a CSV is
processed only by the bank-import path and a supported receipt attachment only by
the receipt path; other non-command text can be processed as a notification.
`!help` sends all guides that apply to the current channel. `!catch_up` belongs
to the notification handler and retries messages without the bot's success
reaction; it never scans historical statement attachments. `!make_schedule`
also belongs to that handler. It must be sent as a reply in the configured bank
notification channel and accepts an optional positive `X day(s)`, `X week(s)`,
`X month(s)`, or `X year(s)` recurrence; no argument means monthly. Invalid
duration text does not reach the Actual connector.

Unexpected handler exceptions are logged at the bot boundary so one malformed
message cannot break subsequent routing. Feature handlers translate expected
errors into their own logs and user-facing feedback.

## Bank-notification import

`BaseNotification` separates the forwarded-message envelope from bank-specific
notification wording. `PekaoNotification` supplies patterns for supported Bank
Pekao deposits, transfers, card payments, and phone top-ups and converts a match
to `ActualTransactionData`. It retains the forwarded Unix timestamp, including
scientific-notation seconds, rather than discarding it. The transaction date is
chosen consistently for ordinary imports and schedules in this order: an
explicit Pekao card-payment date, the forwarded timestamp converted using
`BANK_NOTIFICATION_TIMEZONE` (default `Europe/Warsaw`), then the Discord
message creation date in that timezone. A missing or malformed timestamp only
logs a warning and uses the Discord fallback date.

`NotificationChannelHandler` receives the notification class as a dependency,
which keeps the Pekao default replaceable in tests or by a future bank selector.
It performs the synchronous Actual write in a worker thread and reacts with a
check mark only after persistence succeeds. Expected parse failures are logged
without echoing the full financial message.

The catch-up command walks the complete bound-channel history and skips messages
that already contain the bot's check-mark reaction. The reaction is therefore
the Discord-side processing marker.

### Recurring schedules

A member may reply `!make_schedule` to a notification only after the bot added
its own ✅, which proves the notification was imported successfully. The handler
resolves either Discord's embedded reply message or fetches it from the bound
channel. Missing/deleted/unavailable references, references from another
channel, unsupported notification text, missing success reaction, and blank
payees receive stable Discord errors without details from Discord or Actual.

The handler reuses the exact transaction-data helper used for imports. It creates
a project-owned schedule request with the source date, account, exact signed
amount, and trimmed payee as both payee and name. The resulting Actual schedule
repeats forever at the requested daily/weekly/monthly/yearly interval, does not
move weekend dates, matches the amount exactly, and never auto-posts a
transaction—transactions always need manual approval. The source transaction is
not retroactively attached to the schedule.

`ActualConnector.create_schedule` performs the complete case-insensitive,
exact-name duplicate check and create operation in one disposable Actual session.
It explicitly resolves the account and payee before constructing the ActualPy
schedule, then commits once only when a schedule is created. An existing same
name returns unchanged even when its schedule details differ. Schedule creation
uses the shared write lock across the check and create and runs in a worker
thread, so it cannot race another Actual write or block Discord's event loop.

## Receipt import

### Input and resource boundaries

The Discord handler accepts the first supported attachment on a message. Images
and PDFs follow different extraction paths:

- JPG, JPEG, PNG, WebP, BMP, and TIFF images are decoded with Pillow, limited to
  25 million pixels, converted to grayscale, sharpened, binarized, and sent to
  the configured OCR provider.
- PDFs are read directly with `pdfplumber` and limited to ten pages; scanned PDFs
  without embedded text are not OCRed.

Discord receipt attachments are limited to 10 MB, checked both from attachment
metadata and after download. Only one receipt is processed concurrently by
default. CPU-bound image/PDF work and synchronous Actual operations run in
worker threads rather than blocking the Discord event loop.

### OCR and parsing

`OCRProvider` is the backend interface. `TesseractProvider` is the only working
implementation and is configured with `OCR_TESSERACT_LANG` and
`OCR_TESSERACT_PSM`. The provider factory recognizes cloud-provider names, but
those classes are placeholders; see [Future improvements](FUTURE_IMPROVEMENTS.md).

`ReceiptParser` produces a `ParsedReceipt` containing the merchant, items,
total, optional date, and source. It handles common Polish fiscal and digital
receipt forms, including:

- single-line and wrapped product names;
- `x`, `*`, and related quantity/price layouts;
- leading article codes;
- comma or dot decimal separators;
- `OBNIŻKA`, `RABAT`, and `UPUST` discount lines;
- tax-summary and discount-summary lines that must not become products;
- ISO and `DD.MM.YYYY` dates.

When no date is extracted, the Discord message date is used. A receipt is valid
only when it has items, has a positive total, and the difference between its
declared total and item sum is no more than PLN 0.02. A non-zero difference
inside that tolerance becomes a rounding split named `Zaokrąglenie`; a larger
difference is reported to Discord and is not persisted.

### Split transactions and deduplication

Each receipt item becomes a child transaction. The parent split contains the
merchant in its notes and a deterministic receipt-prefixed financial ID derived
from merchant, date, and total.

Both import directions guard against duplicates. Matching uses:

- the configured Actual account;
- the signed expense amount;
- a date window of one day on either side;
- a normalized merchant-name containment match; and
- parent transactions only, never individual split children.

Receipt imports can therefore detect an earlier bank transaction, while expense
notifications specifically look for earlier receipt imports. Deposits are not
deduplicated against receipts. Merchant matching prevents unrelated same-value
purchases from being discarded.

## Bank CSV import

The optional `DISCORD_BANK_IMPORT_CHANNEL` is intended to be private. The
handler accepts exactly one `.csv` attachment and an empty caption or an exact
`1 months` through `24 months` caption. It checks the 10 MiB limit both before
and after download, retains the safe original basename, and runs one conversion
at a time by default. No payees, amounts, raw CSV text, attachment URLs, or
upstream diagnostics are included in Discord replies or logs.

`BankStatementConverter` creates a unique temporary input/config directory,
then starts `bank2ynab_worker` without a shell and with a 30-second timeout. The
worker is the only application module that imports `bank2ynab`; it emits a
versioned JSON result and never configures its YNAB API. The parent validates
that exactly one file and no more than 50,000 rows were converted, translates
YNAB milliunits through `Decimal`, and removes the temporary directory in all
outcomes.

The project pins `bank2ynab` to commit
`3e2bf71d27031f06172e7ea8ad583f5a7ac3bf78` in both `pyproject.toml` and the
lock file. Upgrades are deliberate dependency changes: review a new immutable
commit, update and lock it, run synthetic conversion contract tests, manually
smoke-test a private current export, and confirm the container build before
merging. Git is present only in the Docker builder stage to resolve this VCS
dependency; the production stage does not clone upstream at runtime.

The current supported Pekao export is the 11-column layout without the optional
`Kategoria` column. Its `Lista_operacji_YYYYMMDD_HHMMSS.csv` filename must not
be changed. A recognized 12-column export is rejected rather than locally
reparsed.

Date filtering happens after conversion. The configured
`BANK_IMPORT_TIMEZONE` (default `Europe/Warsaw`) determines today; the inclusive
window begins on the first day of the current month minus `X - 1` calendar
months and ends today. Future-dated and older rows are counted as outside the
window.

Before writing, the handler lists open, non-tombstoned Actual accounts. It
reuses a process-memory uploader-approved mapping only while that account is
still open, accepts a sole account, or accepts a unique exact normalized match.
Normalization is Unicode case-folding, accent/punctuation removal, and
whitespace collapse; a core-token comparison removes only generic words such as
country codes, `bank`, `checking`, `savings`, `credit`, and `account`. It never
uses fuzzy or substring matching. Ambiguous cases present a paginated (25 per
page), uploader-only select view that expires after five minutes. No Actual
write lock is held during conversion or that interaction.

`ActualConnector.import_bank_transactions` revalidates the chosen account while
holding the shared write lock. It assigns deterministic IDs of the form
`bank2ynab:<sha256(format + NUL + upstream ID)[:32]>`, then first matches those
IDs in the selected account. If no ID exists, it conservatively compares parent
transactions with exact amount, a one-day date window, and merchant containment
across imported description, Actual payee, and notes. Rows without a payee need
an exact date. A fallback candidate can suppress only one source row, so a
legitimate repeated payment is retained. Existing rows are never modified;
missing rows are created as cleared transactions and committed once.

## Actual Budget write serialization

`main()` injects the same `asyncio.Lock` into all handlers. The lock serializes
notification, receipt, and bank-CSV writes through the shared `ActualConnector`, while
each blocking connector call runs in a worker thread. This avoids overlapping
use of the shared Actual manager without blocking unrelated Discord processing.

## Package map

```text
actual_discord_bot/
|-- bot.py                       # lifecycle, commands, composition, routing
|-- config.py                    # environment-backed configuration
|-- actual_connector.py          # Actual Budget boundary, including schedules
|-- schedules.py                 # recurrence values and strict duration parser
|-- bank_notifications/
|   |-- base_notification.py     # envelope and parser abstraction
|   `-- pekao_notification.py    # Bank Pekao patterns
|-- bank_imports/
|   |-- models.py                # immutable converted/import values
|   |-- caption.py               # strict captions and calendar windows
|   |-- account_matcher.py       # conservative pure account resolution
|   |-- converter.py             # bounded parent-side worker adapter
|   `-- bank2ynab_worker.py      # isolated pinned upstream adapter
|-- channel_handlers/
|   |-- base.py                  # shared channel lifecycle
|   |-- notifications.py         # notification Discord workflow
|   |-- bank_imports.py          # CSV Discord workflow and account selector
|   `-- receipts.py              # receipt Discord workflow
`-- receipts/
    |-- models.py                # parsed receipt data
    |-- ocr_provider.py          # OCR interface, factory, Tesseract backend
    |-- preprocessing.py         # image preparation
    |-- pdf_extractor.py         # bounded PDF text extraction
    |-- parser.py                # Polish receipt parsing
    |-- processor.py             # input pipeline and validation
    `-- transaction.py           # matching and split creation
```

Unit tests mirror these boundaries. Integration tests exercise OCR with real
receipt fixtures and Actual Budget persistence through the development Compose
stack.
