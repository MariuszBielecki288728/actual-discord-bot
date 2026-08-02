class ParseNotificationError(RuntimeError):
    def __init__(self, text: str) -> None:
        super().__init__(
            f'Error while parsing notification. "{text}" did not match any regexp.',
        )


class ScheduleSourceNotFound(RuntimeError):  # noqa: N818
    """Raised when a schedule's source account or payee no longer exists."""
