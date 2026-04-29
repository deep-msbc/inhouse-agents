"""
Custom application exceptions.

All modules raise these instead of bare exceptions so that error handling
middleware can catch them uniformly and return consistent API responses.
"""

from app.core.helpers.message import FILE_ERRORS, GENERAL_ERRORS, LLM_ERRORS, MODE_ERRORS


class AppException(Exception):
    """Base exception for all custom application errors."""

    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"error": self.message, "code": self.code}


# ── General ───────────────────────────────────────────────────────────────────

class NotFoundError(AppException):
    def __init__(self, detail: str = ""):
        msg = detail or GENERAL_ERRORS["not_found"]
        super().__init__(msg, code=404)


class InternalServerError(AppException):
    def __init__(self, detail: str = ""):
        msg = detail or GENERAL_ERRORS["internal_server_error"]
        super().__init__(msg, code=500)


# ── File handling ─────────────────────────────────────────────────────────────

class UnsupportedFileTypeError(AppException):
    def __init__(self, ext: str, allowed: set[str]):
        msg = FILE_ERRORS["unsupported_type"].format(allowed=", ".join(sorted(allowed)))
        super().__init__(f"Unsupported file type '{ext}'. {msg}", code=400)


class FileTooLargeError(AppException):
    def __init__(self, actual_mb: float, limit_mb: int):
        msg = FILE_ERRORS["file_too_large"].format(actual_mb=actual_mb, limit_mb=limit_mb)
        super().__init__(msg, code=413)


class FileExtractionError(AppException):
    def __init__(self, detail: str = ""):
        msg = FILE_ERRORS["extraction_failed"].format(detail=detail)
        super().__init__(msg, code=422)


class EmptyDocumentError(AppException):
    def __init__(self):
        super().__init__(FILE_ERRORS["extraction_empty"], code=422)


# ── LLM / extraction ──────────────────────────────────────────────────────────

class LLMExtractionError(AppException):
    def __init__(self, exc_type: str = "", detail: str = ""):
        msg = LLM_ERRORS["extraction_failed"].format(exc_type=exc_type, detail=detail)
        super().__init__(msg, code=500)


class LLMSchemaValidationError(AppException):
    def __init__(self, attempts: int = 1):
        msg = LLM_ERRORS["schema_invalid"].format(attempts=attempts)
        super().__init__(msg, code=502)


# ── Mode ──────────────────────────────────────────────────────────────────────

class InvalidModeError(AppException):
    def __init__(self, mode: str, allowed: set[str]):
        msg = MODE_ERRORS["invalid_mode"].format(mode=mode, allowed=", ".join(sorted(allowed)))
        super().__init__(msg, code=400)
