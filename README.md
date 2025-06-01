# Actual Discord Bot

[![Unit tests](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Unit%20tests/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/unit_tests.yml)
[![Ruff](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/Ruff/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/ruff.yml)
[![CodeQL](https://github.com/MariuszBielecki288728/actual-discord-bot/workflows/CodeQL/badge.svg)](https://github.com/MariuszBielecki288728/actual-discord-bot/actions/workflows/codeql-analysis.yml)
[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

A Discord bot that reads receipts from Discord channels, parses them, and converts them to Actual Budget split transactions.

## Features

- Integration with Discord to monitor and process messages
- Parsing of bank notification messages
- Support for multiple banks including Pekao
- Automatic conversion of receipt data to Actual Budget transaction format
- Dockerized for easy deployment

## Installation

### Prerequisites

- Python 3.13+
- [Poetry](https://python-poetry.org/docs/#installation)
- [Actual Budget server](https://actualbudget.com/) instance


### Using Docker

```bash
# Clone the repository
git clone https://github.com/MariuszBielecki288728/actual-discord-bot.git
cd actual-discord-bot

docker-compose up bot
```

## Development

### Setting up the development environment

```bash
# Create virtual env.
python3.13 -m venv ./venv
# Activate virtual env.
source ./venv/bin/activate
# Install the project dependencies
poetry install --with dev,linters,tests
# Install pre-commit hooks
poetry run pre-commit install
```

### Running tests

```bash
# Run tests using tox
poetry run tox

# Or run tests directly with pytest
pytest .
```

### Code linting

```bash
pre-commit run --all-files
```

## Configuration

Create an environment file with your Discord bot token and Actual Budget credentials:

```bash
# Example .env file
DISCORD_TOKEN=your_discord_bot_token
ACTUAL_SERVER_URL=http://your-actual-server:5006
ACTUAL_PASSWORD=your_actual_password
```

## Usage

Run the bot:

```bash
python -m actual_discord_bot.bot
```

or if you are using Docker, refer to the [Using Docker](#using-docker) section for instructions.
## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
