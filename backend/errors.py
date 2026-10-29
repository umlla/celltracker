"""统一 API 错误类型与处理。"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 400,
        code: str = "bad_request",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return body


class NotFound(ApiError):
    def __init__(self, message: str = "记录不存在") -> None:
        super().__init__(message, status=404, code="not_found")


class Conflict(ApiError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, status=409, code="conflict", details=details)


class ValidationError(ApiError):
    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message, status=400, code="validation_error", details=details)


def require(condition: Any, message: str, details: Any = None) -> None:
    if not condition:
        raise ValidationError(message, details)
