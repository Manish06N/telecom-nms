"""How business code refuses a request.

Routes turn this into JSON. The domain does not import FastAPI.
"""


class AppError(Exception):
    def __init__(self, detail: str, status_code: int = 400, code: str = "bad_request"):
        self.detail = detail
        self.status_code = status_code
        self.code = code
        super().__init__(detail)
