from threading import Lock


class ErrorProducer:
    """Mixin de objetos que produzem erros (`report_error`/`collect_errors`), seguro entre threads."""

    errors: list[Exception]
    errors_lock: Lock

    def __init__(self) -> None:
        self.errors = []
        self.errors_lock = Lock()

    def report_error(self, error: Exception) -> None:
        with self.errors_lock:
            self.errors.append(error)

    def collect_errors(self) -> list[Exception]:
        with self.errors_lock:
            errors = self.errors.copy()
            self.errors.clear()
        return errors
