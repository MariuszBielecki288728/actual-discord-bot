# Actual Discord Bot

[![Unit tests](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Unit%20tests/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/unit_tests.yml)
[![Ruff](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Ruff/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/ruff.yml)
[![CodeQL](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/CodeQL/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/codeql-analysis.yml)
[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

A Discord bot that automatically creates transactions in [Actual Budget](https://actualbudget.org/) from bank push notifications forwarded via the [Automate](https://llamalab.com/automate/) app on Android, and from receipt photos/PDFs posted to a dedicated channel.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — current component boundaries, message
  routing, receipt processing, concurrency, and deduplication behavior
- [Future improvements](docs/FUTURE_IMPROVEMENTS.md) — ideas that are not yet
  implemented

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

Receipt processing is intentionally bounded to one attachment at a time, 10 MB
per attachment, 25 million image pixels, and 10 PDF pages. Deduplication requires
the account, signed amount, date window, and a normalized merchant-name match;
same-value purchases from different merchants are therefore kept separate. The
Discord reply explicitly reports whether a transaction was created or skipped as
an existing receipt.

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
- **In-channel guidance** — Posts a complete usage guide on startup and provides it on demand with `!help`
- **Hot-reload** — Uses [cogwatch](https://github.com/robertwayne/cogwatch) only in the development Compose stack
- **Dockerized deployment** — Full Docker Compose setup with bot, Actual server, and integration test services

## Architecture

The bot is a thin Discord router around independently owned notification and
receipt workflows. The receipt path further separates input processing, text
parsing, and Actual Budget persistence. Both workflows share one connector and
serialize writes with one asynchronous lock.

See [Architecture](docs/ARCHITECTURE.md) for the authoritative design and current
runtime behavior. Unimplemented extensions are tracked separately in
[Future improvements](docs/FUTURE_IMPROVEMENTS.md).

## Home LAN Deployment

This is the recommended real-life setup: one always-on Linux machine on your home
LAN runs Actual Server and the Discord bot with Docker Compose. Phones and
computers on the same LAN open Actual using that machine's private IP address.
This guide deliberately does not expose Actual to the internet or cover domains,
DNS, TLS, VPNs, or cloud hosting.

### Prerequisites

- An always-on Linux machine connected to the home router by Ethernet or Wi-Fi
- Docker Engine with the Compose plugin (`docker compose version` must work)
- A static DHCP lease for the Linux machine, recommended so its LAN IP does not change
- A Discord account and a server where you can create channels and invite a bot
- An Android phone if bank notifications will be forwarded with Automate

### 1. Prepare the Linux host

```bash
git clone https://github.com/MariuszBielecki288728/actual-discord-bot.git
cd actual-discord-bot
cp deployment/lan/.env.example deployment/lan/.env
hostname -I
```

Record the private address printed by the last command, for example
`192.168.1.50`. Reserve that address for this machine in the router's DHCP
settings if possible. Port `12012` must be allowed by the Linux firewall for the
local subnet, but should not be forwarded on the router.

### 2. Start and configure Actual Server

Start only Actual first:

```bash
docker compose --env-file deployment/lan/.env \
  -f deployment/lan/compose.yml up -d actual_server
```

On a device in the same LAN, open `http://192.168.1.50:12012`, substituting the
host IP. Complete Actual's first-run setup, set a strong server password, and
create or upload the budget that the bot will use. Create an account for imported
transactions—for example `Pekao`.

Edit `deployment/lan/.env`:

- `ACTUAL_PASSWORD` is the Actual server password.
- `ACTUAL_FILE` is the budget file name shown in Actual (for example `My Finances`).
- `ACTUAL_ENCRYPTION_PASSWORD` is only needed if that budget uses end-to-end encryption.
- `ACTUAL_ACCOUNT` must exactly match the destination account name in the budget.

The Actual mobile experience is the same web application: connect the phone to
home Wi-Fi and open `http://192.168.1.50:12012`. Add it to the home screen if
desired. This address is intentionally available only while connected to the LAN.

### 3. Create and invite the Discord bot

1. In the Discord Developer Portal, create an application and add a bot.
2. On the bot page, enable the privileged **Message Content Intent**. The bot
   needs it to read forwarded notifications and commands.
3. Copy the bot token into `DISCORD_TOKEN` in `deployment/lan/.env`. Treat it like
   a password and never commit the `.env` file.
4. In the OAuth2 URL Generator, select the `bot` scope and grant **View Channels**,
   **Send Messages**, **Read Message History**, **Add Reactions**, and
   **Attach Files**. Open the generated URL and invite the bot to your server.
5. Create `bank-notifications` and, optionally, `receipts` text channels. Give the
   bot the permissions above in both. If different names are used, put the exact
   names (without `#`) in `DISCORD_BANK_NOTIFICATION_CHANNEL` and
   `DISCORD_RECEIPT_CHANNEL`.

### 4. Forward bank notifications

Create an incoming Discord webhook for the bank notification channel and copy its
URL. In Android Automate, build a flow that waits for notifications from the bank
app and sends an HTTP POST to that webhook with a JSON body whose `content` is:

```text
Title: <notification title>
Text: <notification body>
Timestamp: <notification timestamp>
```

Set the request content type to `application/json`. Restrict the flow to the bank
app's package so unrelated phone notifications are never uploaded. The parser
currently supports Bank Pekao notification wording; test with one notification
and confirm the transaction in Actual before leaving the flow enabled.

### 5. Start the complete stack

Finish editing `deployment/lan/.env`, then run:

```bash
docker compose --env-file deployment/lan/.env \
  -f deployment/lan/compose.yml up -d --build
docker compose -f deployment/lan/compose.yml logs -f bot
```

When connected, the bot posts a friendly, channel-specific guide in every
configured channel. Send `!help` to retrieve the appropriate guide later. Post a
receipt in the receipt channel or forward a test bank message, then verify both
the Discord response and the transaction in Actual.

Useful operating commands:

```bash
# Status and logs
docker compose -f deployment/lan/compose.yml ps
docker compose -f deployment/lan/compose.yml logs --tail=100 bot actual_server

# Pull code and rebuild the bot
git pull
docker compose --env-file deployment/lan/.env \
  -f deployment/lan/compose.yml up -d --build

# Stop services without deleting budget data
docker compose -f deployment/lan/compose.yml down
```

Actual data lives in the named Docker volume `actual-budget-home_actual_data`.
Back it up regularly. Do not run `docker compose down -v` unless you intend to
delete that volume. A backup should be tested before relying on it.

### Troubleshooting

- No startup message: check `docker compose ... logs bot`, channel spelling, bot
  permissions, Message Content Intent, and the token.
- Actual cannot be opened from a phone: confirm both devices are on the same LAN,
  use the Linux host's IP rather than `localhost`, and check the host firewall.
- Actual connection errors in bot logs: verify password, budget name, account
  name, and encryption password. Inside Compose the bot correctly uses
  `http://actual_server:5006`; do not replace it with the host's LAN IP.
- A bank message has no ✅: its format or wording was not recognized. Inspect the
  logs, then use `!catch_up` after correcting the cause.
- OCR results are wrong: use a sharp, evenly lit, straight-on photo and verify the
  resulting split transaction manually.

## Development Installation

For modifying or testing the project locally, install Python 3.13 and Poetry:

```bash
python3.13 -m venv ./venv
source ./venv/bin/activate
pip install poetry
poetry install --with dev,linters,tests
pre-commit install
```

> Poetry and project tooling live inside the venv. Activate it before running
> `poetry`, `pytest`, or `pre-commit`.

The root `docker-compose.yml` supports development and integration testing. For a
real installation, prefer the isolated `deployment/lan/compose.yml` described
above.

## Configuration Reference

The bot is configured with these environment variables:

```bash
# Discord
DISCORD_TOKEN=your_discord_bot_token
DISCORD_BANK_NOTIFICATION_CHANNEL=bank-notifications  # channel name (not ID)
DISCORD_RECEIPT_CHANNEL=receipts                      # optional: channel for receipt photos/PDFs
DISCORD_HOT_RELOAD=false                              # development-only source watcher

# Actual Budget
ACTUAL_URL=http://actual_server:5006    # Compose service URL used by the bot
ACTUAL_PASSWORD=your_actual_password    # Actual server password
ACTUAL_FILE=My Budget                   # Budget file name or ID
ACTUAL_ENCRYPTION_PASSWORD=             # Optional: E2E encryption password
ACTUAL_ACCOUNT=Pekao                    # Account name for transactions

# OCR (only needed if receipt_channel is set)
OCR_PROVIDER=tesseract                  # only supported backend; cloud providers are future work
OCR_TESSERACT_LANG=pol                  # Tesseract language (default: pol)
OCR_TESSERACT_PSM=6                     # Tesseract page segmentation mode (default: 6)
```

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `DISCORD_BANK_NOTIFICATION_CHANNEL` | Yes | Name of the channel to monitor for bank notifications |
| `DISCORD_RECEIPT_CHANNEL` | No | Name of the channel for receipt photos/PDFs |
| `DISCORD_HOT_RELOAD` | No | Enable source watching in a development checkout (default: `false`) |
| `ACTUAL_URL` | Yes | Actual Budget server URL |
| `ACTUAL_PASSWORD` | Yes | Actual server password |
| `ACTUAL_FILE` | Yes | Budget file name or sync ID |
| `ACTUAL_ENCRYPTION_PASSWORD` | No | File encryption password (if enabled) |
| `ACTUAL_ACCOUNT` | No | Account name for transactions (default: `Pekao`) |
| `OCR_PROVIDER` | No | OCR backend (default and currently supported value: `tesseract`) |
| `OCR_TESSERACT_LANG` | No | Tesseract language pack (default: `pol`) |
| `OCR_TESSERACT_PSM` | No | Page segmentation mode (default: `6`) |

## Usage

### Running the development stack

```bash
# Via Docker (recommended)
docker compose up bot

# Or directly
DISCORD_HOT_RELOAD=true python -m actual_discord_bot.bot
```

The development Compose stack enables `DISCORD_HOT_RELOAD=true` and watches the
mounted `actual_discord_bot/` source tree. Production leaves it disabled by default.
If the development source tree is unavailable, the bot logs a warning and continues
without hot reload rather than blocking Discord startup.

### Bot Commands

| Command | Description |
|---------|-------------|
| `!help` | Show the full channel guide, reactions, supported inputs, and commands |
| `!catch_up` | Process all unprocessed messages in the notification channel |

### Discord Channel Setup

1. Create a text channel (e.g., `bank-notifications`) in your Discord server
2. Set up the Automate app on your Android phone to forward bank notifications to this channel
3. (Optional) Create a second channel (e.g., `receipts`) for posting receipt photos and PDF receipts
4. The bot posts its usage guide on startup and automatically processes new messages

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
- **[cogwatch](https://github.com/robertwayne/cogwatch)** — Development-only source watcher
- **[environ-config](https://environ-config.readthedocs.io/)** — Typed environment configuration
- **[Babel](https://babel.pocoo.org/)** — Number/locale parsing (Polish decimal format)
- **[Pillow](https://pillow.readthedocs.io/)** — Image preprocessing for OCR
- **[pytesseract](https://github.com/madmaze/pytesseract)** — Tesseract OCR Python bindings
- **[pdfplumber](https://github.com/jsvine/pdfplumber)** — PDF text extraction
- **[Ruff](https://docs.astral.sh/ruff/)** — Linting and formatting
- **[pytest](https://docs.pytest.org/)** — Testing framework

## License

This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.
