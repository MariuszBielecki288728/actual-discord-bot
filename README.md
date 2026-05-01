# Actual Discord Bot

[![Unit tests](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Unit%20tests/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/unit_tests.yml)
[![Ruff](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Ruff/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/ruff.yml)
[![CodeQL](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/CodeQL/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/codeql-analysis.yml)
[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

A Discord bot that automatically creates transactions in [Actual Budget](https://actualbudget.org/) from bank push notifications forwarded via the [Automate](https://llamalab.com/automate/) app on Android, and from receipt photos/PDFs posted to a dedicated channel.

## How It Works

### Bank Notifications

1. **Android phone** receives a bank push notification (e.g., from Bank Pekao)
2. **Automate app** captures the notification and forwards it to a Discord channel as a message with the format:
   ```
   Title: <notification title>
   Text: <notification body>
   Timestamp: <unix timestamp>
   ```
3. **This bot** monitors the Discord channel, parses the message using bank-specific regex patterns, and creates a corresponding transaction in Actual Budget via the [actualpy](https://github.com/bvanelli/actualpy) library
4. The bot reacts with ✅ to mark successfully processed messages

### Receipt Parsing

1. User posts a **receipt photo** (JPG/PNG/WebP) or a **digital PDF receipt** (from shop apps like Kaufland, Lidl) to a dedicated Discord channel
2. Bot detects the attachment type:
   - **Image** → preprocesses (grayscale, sharpen, binarize) → OCR via Tesseract (Polish language)
   - **PDF** → text extraction via pdfplumber (no OCR needed)
3. Extracted text is parsed to identify product line items, discounts, and total
4. Bot creates a **split transaction** in Actual Budget where each product is a sub-transaction
5. Bot reacts with ✅/⚠️/❌ and replies with a summary

## Features

### Implemented
- **Bank notification processing** — Monitors a Discord channel for forwarded bank notifications and creates transactions in Actual Budget
- **Pekao bank support** — Parses card payments, incoming transfers, outgoing transfers, and phone top-ups from Bank Pekao S.A. notifications
- **Receipt photo parsing** — OCR via Tesseract (Polish language) extracts products from receipt photos and creates split transactions
- **Digital PDF receipt parsing** — Extracts text from digital receipts (Kaufland, Lidl, Żabka apps) without OCR
- **Transaction deduplication** — Prevents duplicate transactions when both a receipt and bank notification arrive for the same purchase
- **Split transactions** — Each product line item becomes a sub-transaction in Actual Budget
- **Discount handling** — Recognizes OBNIŻKA/RABAT/UPUST discount lines and includes them as negative sub-transactions
- **Idempotent catch-up** — `!catch_up` command processes all unprocessed messages in the channel (skips already-reacted ones)
- **Hot-reload** — Uses [cogwatch](https://github.com/robertwayne/cogwatch) for live code reloading during development
- **Dockerized deployment** — Full Docker Compose setup with bot, Actual server, and integration test services

### Planned
- **Multi-bank support** — Extensible architecture for adding more bank notification formats
- **Category assignment** — Pluggable pipeline for automatic product categorization
- **Item name expansion** — Dictionary-based abbreviation expansion for receipt product names
- **Cloud OCR providers** — AWS Textract and Google Cloud Vision as alternative OCR backends

## Architecture

```
actual_discord_bot/
├── bot.py                  # Discord bot: event handling, message routing
├── config.py               # Environment-based configuration (environ-config)
├── actual_connector.py     # Actual Budget API wrapper (actualpy)
├── dataclasses_definitions.py  # Transaction data models
├── enums.py                # TransactionType enum (DEPOSIT/PAYMENT)
├── errors.py               # Custom exceptions
├── bank_notifications/
│   ├── base_notification.py    # Abstract base with regex matching logic
│   └── pekao_notification.py   # Bank Pekao notification parser
└── receipts/
    ├── handler.py          # Orchestrates receipt processing pipeline
    ├── models.py           # ParsedReceipt/ReceiptItem dataclasses
    ├── ocr_provider.py     # OCR abstraction (Tesseract, cloud providers)
    ├── parser.py           # Receipt text parser (regex-based)
    ├── pdf_extractor.py    # PDF text extraction (pdfplumber)
    ├── preprocessing.py    # Image preprocessing for OCR
    └── transaction.py      # Split transaction creation & deduplication
```

## Installation

### Prerequisites

- Python 3.13+
- [Poetry](https://python-poetry.org/docs/#installation) (v1.8+)
- [Actual Budget server](https://actualbudget.org/docs/install/docker) instance
- A Discord bot token ([guide](https://discord.com/developers/docs/getting-started))

### Using Docker (recommended)

```bash
# Clone the repository
git clone https://github.com/MariuszBielecki288728/actual-discord-bot.git
cd actual-discord-bot

# Create .env file (see Configuration section)
cp .env.example .env  # edit with your values

# Start the bot and Actual server
docker-compose up bot
```

### Local Development

```bash
# Create virtual env
python3.13 -m venv ./venv
source ./venv/bin/activate

# Install Poetry (if not already in venv)
pip install poetry

# Install all dependencies
poetry install --with dev,linters,tests

# Install pre-commit hooks
pre-commit install
```

> **Note:** Poetry is installed inside the venv. Always run `source ./venv/bin/activate` before using `poetry`, `pytest`, `pre-commit`, or any other project tooling.

## Configuration

The bot is configured via environment variables. Create a `.env` file in the project root:

```bash
# Discord
DISCORD_TOKEN=your_discord_bot_token
DISCORD_BANK_NOTIFICATION_CHANNEL=bank-notifications  # channel name (not ID)
DISCORD_RECEIPT_CHANNEL=receipts                      # optional: channel for receipt photos/PDFs

# Actual Budget
ACTUAL_URL=http://localhost:5006        # URL of your Actual server
ACTUAL_PASSWORD=your_actual_password    # Actual server password
ACTUAL_FILE=My Budget                   # Budget file name or ID
ACTUAL_ENCRYPTION_PASSWORD=             # Optional: E2E encryption password
ACTUAL_ACCOUNT=Pekao                    # Account name for transactions

# OCR (only needed if receipt_channel is set)
OCR_PROVIDER=tesseract                  # tesseract (default) | textract | google_vision
OCR_TESSERACT_LANG=pol                  # Tesseract language (default: pol)
OCR_TESSERACT_PSM=6                     # Tesseract page segmentation mode (default: 6)
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `DISCORD_BANK_NOTIFICATION_CHANNEL` | Yes | Name of the channel to monitor for bank notifications |
| `DISCORD_RECEIPT_CHANNEL` | No | Name of the channel for receipt photos/PDFs |
| `ACTUAL_URL` | Yes | Actual Budget server URL |
| `ACTUAL_PASSWORD` | Yes | Actual server password |
| `ACTUAL_FILE` | Yes | Budget file name or sync ID |
| `ACTUAL_ENCRYPTION_PASSWORD` | No | File encryption password (if enabled) |
| `ACTUAL_ACCOUNT` | No | Account name for transactions (default: `Pekao`) |
| `OCR_PROVIDER` | No | OCR backend: `tesseract`, `textract`, or `google_vision` |
| `OCR_TESSERACT_LANG` | No | Tesseract language pack (default: `pol`) |
| `OCR_TESSERACT_PSM` | No | Page segmentation mode (default: `6`) |

## Usage

### Running the bot

```bash
# Via Docker (recommended)
docker-compose up bot

# Or directly
python -m actual_discord_bot.bot
```

### Bot Commands

| Command | Description |
|---------|-------------|
| `!catch_up` | Process all unprocessed messages in the notification channel |

### Discord Channel Setup

1. Create a text channel (e.g., `bank-notifications`) in your Discord server
2. Set up the Automate app on your Android phone to forward bank notifications to this channel
3. (Optional) Create a second channel (e.g., `receipts`) for posting receipt photos and PDF receipts
4. The bot will automatically process new messages and create transactions

## Development

### Running Tests

```bash
# Unit tests
pytest tests/unit_tests/

# Integration tests (requires Docker)
docker-compose --profile testing run --rm integration_tests
```

### Linting & Formatting

```bash
# Run all pre-commit hooks
pre-commit run --all-files

# Or individually
ruff check .
ruff format .
```

### Project Structure

```
├── actual_discord_bot/     # Main package
│   ├── bank_notifications/ # Bank-specific notification parsers
│   └── receipts/           # Receipt parsing pipeline (OCR, PDF, parser)
├── tests/
│   ├── unit_tests/         # Fast tests, no external deps
│   ├── integration_tests/  # Tests against real Actual server (Docker)
│   └── receipts/           # Test receipt images and PDFs
├── docker-compose.yml      # Bot + Actual server + test services
├── Dockerfile              # Multi-stage: base → builder → development → testing
├── pyproject.toml          # Poetry config, pytest, coverage settings
└── .pre-commit-config.yaml # Ruff + black + pre-commit-hooks
```

## Tech Stack

- **[discord.py](https://discordpy.readthedocs.io/)** — Discord API wrapper
- **[actualpy](https://actualpy.readthedocs.io/)** — Python client for Actual Budget API
- **[cogwatch](https://github.com/robertwayne/cogwatch)** — Hot-reload for discord.py cogs
- **[environ-config](https://environ-config.readthedocs.io/)** — Typed environment configuration
- **[Babel](https://babel.pocoo.org/)** — Number/locale parsing (Polish decimal format)
- **[Pillow](https://pillow.readthedocs.io/)** — Image preprocessing for OCR
- **[pytesseract](https://github.com/madmaze/pytesseract)** — Tesseract OCR Python bindings
- **[pdfplumber](https://github.com/jsvine/pdfplumber)** — PDF text extraction
- **[Ruff](https://docs.astral.sh/ruff/)** — Linting and formatting
- **[pytest](https://docs.pytest.org/)** — Testing framework

## License

This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.
