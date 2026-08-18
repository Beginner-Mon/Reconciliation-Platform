class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class BadRequest(AppError):
    status_code = 400


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class RateLimitError(Exception):
    """Lỗi tạm thời từ nhà cung cấp AI (429/quota). Step Functions Retry bắt lỗi này."""
