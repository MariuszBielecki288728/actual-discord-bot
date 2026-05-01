from unittest.mock import MagicMock

import pytest

from actual_discord_bot.bot import ActualDiscordBot
from actual_discord_bot.config import DiscordConfig


@pytest.fixture
def bot():
    config = DiscordConfig(
        token="token",
        bank_notification_channel="bank-notifications",
    )
    mock_actual_connector = MagicMock()
    return ActualDiscordBot(config, mock_actual_connector)
