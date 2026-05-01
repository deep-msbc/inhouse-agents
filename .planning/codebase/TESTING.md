# TESTING.md

## Current State

**No tests exist.** As of the codebase map date, there are zero test files (`test_*.py` or `*_test.py`) anywhere in the repository.

- No `pytest`, `unittest`, or any test runner configured in `pyproject.toml`
- No CI/CD configuration (no `.github/` directory, no `.azure-pipelines.yml`)
- No test fixtures, factories, or mock data

## Running Tests

No test command exists yet. Once tests are added, the expected command will be:
```bash
uv run pytest
uv run pytest tests/path/to/test_file.py::test_name   # single test
```

## What Needs Test Coverage (Priority Order)

1. **LLM client** (`openai_client.py`) — schema validation retry logic, normalizer functions
2. **Document extractors** (`docx_extractor.py`, `pdf_extractor.py`) — heading extraction, text chunking
3. **TOON serializer** (`toon_serializer.py`) — compression correctness and round-trip fidelity
4. **Repository layer** — CRUD operations against a test database
5. **API endpoints** — job creation, polling, error cases (FastAPI `TestClient`)
