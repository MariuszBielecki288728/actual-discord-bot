# Architecture

This document describes the architecture implemented by the repository. Product
ideas that are not implemented belong in [Future improvements](FUTURE_IMPROVEMENTS.md),
not in this document.

## System context

The bot imports financial activity from two Discord workflows into one Actual
Budget account:

```text
Android bank notification -> Discord message -----> notification handler --+
                                                                         |
Receipt image -> Discord attachment -> image preprocessing -> Tesseract --+--> Actual Budget
Receipt PDF ---> Discord attachment -> PDF text extraction --------------+        |
                                      -> receipt parser -> split transaction -----+
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
  success reactions, and catch-up processing.
- `ReceiptChannelHandler` owns attachment selection and limits, Discord
  reactions/replies, receipt-processing concurrency, and receipt persistence.
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

Receipt handling is ordered before notification handling. If both workflows are
configured for one channel, a supported receipt attachment is processed only as
a receipt; other non-command text can be processed as a notification. `!help`
sends all guides that apply to the current channel. `!catch_up` belongs to the
notification handler and retries messages without the bot's success reaction.

Unexpected handler exceptions are logged at the bot boundary so one malformed
message cannot break subsequent routing. Feature handlers translate expected
errors into their own logs and user-facing feedback.

## Bank-notification import

`BaseNotification` separates the forwarded-message envelope from bank-specific
notification wording. `PekaoNotification` supplies patterns for supported Bank
Pekao deposits, transfers, card payments, and phone top-ups and converts a match
to `ActualTransactionData`.

`NotificationChannelHandler` receives the notification class as a dependency,
which keeps the Pekao default replaceable in tests or by a future bank selector.
It performs the synchronous Actual write in a worker thread and reacts with a
check mark only after persistence succeeds. Expected parse failures are logged
without echoing the full financial message.

The catch-up command walks the complete bound-channel history and skips messages
that already contain the bot's check-mark reaction. The reaction is therefore
the Discord-side processing marker.

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

## Actual Budget write serialization

`main()` injects the same `asyncio.Lock` into both handlers. The lock serializes
all notification and receipt writes through the shared `ActualConnector`, while
each blocking connector call runs in a worker thread. This avoids overlapping
use of the shared Actual manager without blocking unrelated Discord processing.

## Package map

```text
actual_discord_bot/
|-- bot.py                       # lifecycle, commands, composition, routing
|-- config.py                    # environment-backed configuration
|-- actual_connector.py          # Actual Budget boundary
|-- bank_notifications/
|   |-- base_notification.py     # envelope and parser abstraction
|   `-- pekao_notification.py    # Bank Pekao patterns
|-- channel_handlers/
|   |-- base.py                  # shared channel lifecycle
|   |-- notifications.py         # notification Discord workflow
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
