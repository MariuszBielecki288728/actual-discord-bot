from unittest.mock import MagicMock

import pytest

from actual_discord_bot import ActualDiscordBot
from actual_discord_bot.channel_handlers.notifications import NotificationChannelHandler


@pytest.fixture
def notification_handler():
    return NotificationChannelHandler("bank-notifications", MagicMock())


@pytest.fixture
def bot(notification_handler):
    return ActualDiscordBot(notification_handler)
