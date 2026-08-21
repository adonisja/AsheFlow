"""ADP integration custom exceptions."""


class ADPException(Exception):
    """Base exception for all ADP integration errors."""

    pass


class ADPAuthError(ADPException):
    """Raised when OAuth authentication fails."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"ADP Auth Error ({status_code}): {message}")


class ADPValidationError(ADPException):
    """Raised when ADP rejects a request (400 Bad Request)."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        super().__init__(f"ADP Validation Error ({status_code}): {body}")


class ADPPermissionError(ADPException):
    """Raised when client lacks permission (403 Forbidden)."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(f"ADP Permission Error: {message}")


class ADPNotFoundError(ADPException):
    """Raised when resource not found (404 Not Found)."""

    def __init__(self, resource: str):
        self.resource = resource
        super().__init__(f"ADP Resource Not Found: {resource}")


class ADPRateLimitError(ADPException):
    """Raised when rate limited (429 Too Many Requests)."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"ADP Rate Limited. Retry after {retry_after}s")


class ADPServerError(ADPException):
    """Raised when ADP server returns 5xx error."""

    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        super().__init__(f"ADP Server Error ({status_code}): {body}")


class ADPNetworkError(ADPException):
    """Raised when network request fails."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(f"ADP Network Error: {message}")
