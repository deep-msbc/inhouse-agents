"""
Centralised error and success message strings.

Import the relevant dict in any module that needs to raise or return
a standard message — keeps user-facing text out of business logic.
"""

# ── General errors ────────────────────────────────────────────────────────────
GENERAL_ERRORS = {
    "invalid_input": "The input provided is invalid.",
    "bad_request": "The request could not be understood or was missing parameters.",
    "not_found": "The requested resource was not found.",
    "internal_server_error": "An unexpected error occurred. Please try again later.",
    "service_unavailable": "The service is temporarily unavailable. Please try again later.",
    "too_many_requests": "Too many requests. Please slow down and try again.",
}

# ── Validation errors ─────────────────────────────────────────────────────────
VALIDATION_ERRORS = {
    "missing_fields": "Required fields are missing.",
    "invalid_type": "Invalid data type provided.",
    "invalid_format": "Data format is incorrect.",
    "value_out_of_range": "Input value is out of the allowed range.",
}

# ── File errors ───────────────────────────────────────────────────────────────
FILE_ERRORS = {
    "no_filename": "No filename provided.",
    "unsupported_type": "Unsupported file type. Allowed: {allowed}",
    "unexpected_content_type": "Unexpected content type '{content_type}' for file '{filename}'. Proceeding by extension.",
    "file_too_large": "File size {actual_mb:.1f} MB exceeds the maximum allowed {limit_mb} MB.",
    "read_failed": "Could not read the uploaded file: {detail}",
    "extraction_empty": "No text could be extracted from the uploaded document.",
    "extraction_failed": "Text extraction failed: {detail}",
    "unsupported_extraction": "Unsupported file type '{ext}' for extraction.",
}

# ── LLM / extraction errors ───────────────────────────────────────────────────
LLM_ERRORS = {
    "extraction_failed": "Requirement extraction via LLM failed ({exc_type}): {detail}",
    "invalid_json": "LLM returned invalid JSON after {attempts} attempt(s).",
    "schema_invalid": "LLM response did not match the expected schema after {attempts} attempt(s).",
}

# ── Mode errors ───────────────────────────────────────────────────────────────
MODE_ERRORS = {
    "invalid_mode": "Invalid extraction mode '{mode}'. Allowed values: {allowed}.",
}

# ── Success messages ──────────────────────────────────────────────────────────
SUCCESS_MESSAGES = {
    "extraction_complete": "Requirements extracted successfully.",
}
