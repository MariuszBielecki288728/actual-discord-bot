---
description: General project conventions and guidelines for the actual-discord-bot repository
applyTo: '**/*.py'
---

# Project: actual-discord-bot

A Discord bot that creates Actual Budget transactions from bank push notifications forwarded via Android's Automate app, and from receipt photos/PDFs posted to a dedicated channel.

## Tech Stack

- **Python 3.13** with **Poetry** for dependency management
- **discord.py** for Discord integration
- **actualpy** for Actual Budget API interaction
- **Pillow** + **pytesseract** for image preprocessing and OCR
- **pdfplumber** for PDF text extraction
- **pytest** (async mode) for testing
- **Ruff** for linting/formatting, **black** for code style
- **Docker Compose** for deployment and integration tests

## Project Structure

```
actual_discord_bot/           # Main package
├── bot.py                    # Discord bot class and event handlers
├── config.py                 # environ-config based configuration
├── actual_connector.py       # Wrapper around actualpy
├── dataclasses_definitions.py # Data models (ActualTransactionData)
├── enums.py                  # TransactionType enum
├── errors.py                 # Custom exceptions
├── bank_notifications/       # Bank-specific notification parsers
│   ├── base_notification.py  # Base class with regex parsing
│   └── pekao_notification.py # Bank Pekao implementation
└── receipts/                 # Receipt parsing pipeline
    ├── handler.py            # Orchestrates processing (image/PDF → parse → transaction)
    ├── models.py             # ParsedReceipt, ReceiptItem dataclasses
    ├── ocr_provider.py       # OCR abstraction (Tesseract, cloud providers)
    ├── parser.py             # Receipt text parser (regex-based, multi-format)
    ├── pdf_extractor.py      # PDF text extraction (pdfplumber)
    ├── preprocessing.py      # Image preprocessing (grayscale, sharpen, binarize)
    └── transaction.py        # Split transaction creation & deduplication

tests/
├── unit_tests/               # Fast tests, no network/docker needed
├── integration_tests/        # Run against real Actual server in Docker
└── receipts/                 # Test receipt images and PDFs
```

## Coding Conventions

- Use **dataclasses** for data models
- Use **`typing.Self`** for classmethods returning the class instance
- Regex-based parsing with `re.compile` — define patterns as class-level tuples of `NotificationTemplate`
- Use `environ-config` for configuration — prefix-based env var mapping
- Use `decimal.Decimal` for monetary amounts (parsed via `babel.numbers.parse_decimal` with `locale="pl"`)
- Amounts in Actual are stored as integers (cents) — actualpy handles the conversion

## Adding a New Bank

1. Create `actual_discord_bot/bank_notifications/<bank>_notification.py`
2. Subclass `BaseNotification` with a `_notification_regexes` tuple of `NotificationTemplate`
3. Each template has a compiled regex with named groups `amount` and `payee`, plus a `TransactionType`
4. Export from `bank_notifications/__init__.py`
5. Add tests in `tests/unit_tests/test_bank_notification.py`

## Testing

- **Unit tests**: `pytest tests/unit_tests/` — use mocks for Discord and Actual
- **Integration tests**: `docker-compose --profile testing run --rm integration_tests` — tests against a real Actual server
- pytest config: `asyncio_mode = "auto"`, coverage enabled by default
- Fixtures in `conftest.py` per test directory

## Docker Services

- `bot` — The Discord bot (main service)
- `actual_server` — Actual Budget server (production, port 12012)
- `test_actual_server` — Actual Budget server (testing, port 12013, `testing` profile)
- `integration_tests` — Runs integration test suite (`testing` profile)

## Pre-commit Hooks

- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`
- `ruff` (with `--fix`) + `ruff-format`
- `black`

## Key Dependencies

- `actualpy` — Python API for Actual Budget (supports `create_transaction`, `create_splits`, `reconcile_transaction`)
- `discord.py` — Discord API
- `cogwatch` — Hot-reload for development
- `babel` — Polish locale number parsing
- `environ-config` — Environment variable configuration
- `Pillow` — Image preprocessing (grayscale, sharpen, binarize)
- `pytesseract` — Tesseract OCR Python bindings (Polish language)
- `pdfplumber` — PDF text extraction for digital receipts

## Common Commands

**Important:** Poetry and all tooling live inside the local venv. Always activate it first:

```bash
source ./venv/bin/activate
```

```bash
# Development
poetry install --with dev,linters,tests
pre-commit install
pre-commit run --all-files

# Testing
pytest tests/unit_tests/
docker-compose --profile testing run --rm integration_tests

# Running
docker-compose up bot

# Rebuilding after dependency changes
poetry lock
docker-compose build --no-cache
```
