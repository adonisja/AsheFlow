class ADPClientError(Exception):
    """Raised when ADP returns a 4xx response to a timecard write.

    Indicates a non-retryable failure — the request payload is structurally
    invalid. The caller should mark the adjustment as non-retryable and notify
    managers to inspect and correct the data before re-submitting.

    Attributes:
        status_code: HTTP status code returned by ADP (400–499).
        body: Parsed JSON response body from ADP.
    """

    def __init__(self, status_code: int, body: dict):
        super().__init__(str(status_code))
        self.status_code = status_code
        self.body = body


class ADPServerError(Exception):
    """Raised when ADP returns a 5xx response or a network-level failure occurs.

    Indicates a transient failure — ADP was unavailable or the request could not
    be delivered. The caller should increment the attempt counter and leave the
    adjustment retryable for the next scheduled retry window.

    A status_code of 0 means the request never reached ADP (connection timeout,
    DNS failure, etc.) and no HTTP response was received.

    Attributes:
        status_code: HTTP status code returned by ADP (500–599), or 0 for
            network-level failures where no response was received.
        body: Parsed JSON response body from ADP, or an empty dict for
            network-level failures.
    """

    def __init__(self, status_code: int, body: dict):
        super().__init__(str(status_code))
        self.status_code = status_code
        self.body = body


class ADPAuthError(Exception):
    """Raised when the ADP OAuth token exchange fails.

    This is distinct from ADPServerError because an auth failure does not mean
    the timecard write was attempted — the request never reached the ADP API.
    Callers should not increment write_attempt_count; the underlying cause is
    a credential or certificate issue that requires human intervention.

    Attributes:
        status_code: HTTP status code from the token endpoint, or 0 for
            network-level failures.
        message: Human-readable description of the failure.
    """

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message