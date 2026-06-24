class ADPClientError(Exception):
    def __init__(self, status_code: int, body: dict):
        super().__init__(str(status_code))
        self.status_code = status_code
        self.body = body


class ADPServerError(Exception):
    def __init__(self, status_code: int, body:dict):
        super().__init__(str(status_code))
        self.status_code = status_code
        self.body = body