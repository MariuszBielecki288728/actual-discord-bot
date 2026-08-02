from actual_discord_bot.config import DiscordConfig


def test_discord_error_tracebacks_are_enabled_by_default():
    config = DiscordConfig(token="token", bank_notification_channel="bank")

    assert config.show_error_tracebacks is True


def test_discord_error_tracebacks_can_be_disabled():
    config = DiscordConfig(
        token="token", bank_notification_channel="bank", show_error_tracebacks=False
    )

    assert config.show_error_tracebacks is False


def test_discord_error_tracebacks_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DISCORD_BANK_NOTIFICATION_CHANNEL", "bank")
    monkeypatch.setenv("DISCORD_SHOW_ERROR_TRACEBACKS", "false")

    config = DiscordConfig.from_environ()

    assert config.show_error_tracebacks is False
