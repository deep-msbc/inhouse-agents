# Technology Stack

**Analysis Date:** 2026-04-29

## Languages

**Primary:**
- Python >=3.12 - All application code (API, agents, database, LLM clients)

## Runtime

**Environment:**
- CPython >=3.12 (required by `pyproject.toml`)

**Package Manager:**
- `uv` / `pip` (pyproject.toml-based, PEP 517)
- Lockfile: Not detected (no `uv.lock` or `requirements.txt` committed)

## Frameworks

**Core:**
- FastAPI >=0.135.1 - HTTP API server (`main.py`, `src/msbc/api/`)
- Uvicorn >=0.42.0 - ASGI server for running FastAPI
- Pydantic / pydantic-settings >=2.6.0 - Settings management via env vars (`app/core/config.py`)

**AI / Orchestration:**
- LangChain >=1.2.12 - LLM chain primitives
- LangChain-OpenAI >=1.1.11 - `ChatOpenAI` client (`src/msbc/llm/clients/openai_client.py`)
- LangChain-Community >=0.4.1 - Community integrations
- LangChain-HuggingFace >=1.2.1 - HuggingFace model adapters
- LangGraph >=1.1.3 - Agent/graph orchestration for multi-step extraction pipelines
- LangChain-Core >=1.2.26 - Core message/prompt abstractions

**Embeddings / Vector:**
- sentence-transformers >=5.3.0 - Local embedding models
- transformers >=5.3.0 - HuggingFace model loading
- accelerate >=1.13.0 - Hardware-accelerated model inference
- torch >=2.10.0 - PyTorch backend for transformer models
- einops >=0.8.2 - Tensor rearrangement utility
- huggingface-hub >=1.9.0 - Model download from HuggingFace Hub
- voyageai >=0.3.7 - Voyage AI embedding API client
- qdrant-client >=1.17.1 - Qdrant vector store client

**Database:**
- SQLAlchemy >=2.0.0 - ORM and engine (`src/msbc/database/base.py`, `src/msbc/database/session.py`)
- Alembic >=1.13.0 - Database migrations (`src/msbc/database/migrations/`)
- psycopg2-binary >=2.9.0 - PostgreSQL driver

**Document Parsing:**
- python-docx >=1.2.0 - `.docx` file text extraction
- pdfplumber >=0.11.9 - PDF text extraction
- pymupdf >=1.27.2.2 - PDF rendering/parsing fallback

**Code Parsing:**
- tree-sitter >=0.25.2 - Language-agnostic code parsing
- tree-sitter-javascript >=0.25.0 - JavaScript grammar
- tree-sitter-typescript >=0.23.2 - TypeScript grammar

**Utilities:**
- openai >=2.29.0 - Direct OpenAI SDK (also used via LangChain wrapper)
- tiktoken >=0.12.0 - Token counting for OpenAI models (`src/msbc/llm/clients/openai_client.py`)
- jsonschema >=4.26.0 - JSON schema validation of LLM outputs (Draft202012)
- numpy >=2.4.3 - Numeric computation
- pandas >=3.0.1 - Tabular data manipulation
- httpx >=0.28.1 - Async HTTP client
- python-multipart >=0.0.22 - Multipart file upload support for FastAPI
- anyio >=4.13.0 - Async I/O compatibility layer
- pyyaml >=6.0.2 - YAML prompt template loading
- truststore >=0.10.0 - System certificate trust store
- pip-system-certs >=5.3 - Inject system certificates into pip/requests

## Configuration

**Settings System:**
- `pydantic-settings` `BaseSettings` class at `app/core/config.py`
- All settings loaded from environment variables or `.env` file in project root
- Settings singleton accessed via `get_settings()` (LRU-cached)

**Static Defaults:**
- `config/settings.yaml` — human-readable defaults (app name, API port, LLM model, CORS, log level)
- Values in YAML are documentation/defaults only; `app/core/config.py` is the authoritative runtime source

**Build / Run:**
- `pyproject.toml` — project metadata, dependency declarations
- Entry point: `main.py` — `uvicorn.run("main:app", ...)` when executed directly
- Migrations: `alembic upgrade head` using `alembic.ini` + `src/msbc/database/migrations/`

## Platform Requirements

**Development:**
- Python >=3.12
- PostgreSQL (default) or SQLite (auto-detected via `DATABASE_URL` prefix for dev)
- `OPENAI_API_KEY` environment variable required for all LLM calls

**Production:**
- PostgreSQL (primary target per `alembic.ini` and `psycopg2-binary` dependency)
- ASGI host (Uvicorn)

---

*Stack analysis: 2026-04-29*
