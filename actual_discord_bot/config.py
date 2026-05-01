import environ


@environ.config(prefix="ACTUAL")
class ActualConfig:
    url: str = environ.var(default="http://localhost:5006")
    password: str = environ.var()
    file: str = environ.var()
    encryption_password: str = environ.var(default=None)
    account: str = environ.var(default="Pekao")


@environ.config(prefix="DISCORD")
class DiscordConfig:
    token: str = environ.var()
    bank_notification_channel: str = environ.var()
    receipt_channel: str = environ.var(default="")
