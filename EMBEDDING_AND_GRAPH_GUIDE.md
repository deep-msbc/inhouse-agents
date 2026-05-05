# Embedding Pipeline & Kuzu Graph — Implementation Guide

> Purpose: Give Claude Code the full picture of what was built, why, and where the improvement opportunities are.

---

## 1. System Overview

There are **two parallel knowledge stores** that the Stage 2 Frontend Planner queries at generation time:

| Store | What it holds | Used for |
|-------|--------------|----------|
| **Qdrant** (vector DB) | Chunked text embeddings of all RTK source files and code examples | Semantic similarity search — "find components that do X" |
| **Kuzu** (graph DB) | Structural relationships between packages, components, source files, symbols | Graph traversal — "what does ComponentX import?", "which files export HookY?" |

Both stores are populated from the same source: the `ReactToolKits` monorepo at `C:\Users\yug.chauhan\Documents\GitHub\ReactToolKits`.

---

## 2. Qdrant Embedding Pipeline

### 2.1 Files

| File | Role |
|------|------|
| `src/msbc/embedding/schema.py` | Pydantic payload models, collection names, chunk ID helpers |
| `src/msbc/embedding/chunker.py` | AST-aware text chunker (tree-sitter TS/TSX + regex fallback) |
| `src/msbc/embedding/embedder.py` | OpenAI `text-embedding-3-large` wrapper with batching + retry |
| `src/msbc/embedding/store.py` | Qdrant upsert/delete/scroll wrapper |
| `src/msbc/embedding/ingestors/scanner.py` | File discovery + SHA-256 hash diff |
| `src/msbc/embedding/ingestors/toolkit_ingestor.py` | Orchestrates incremental sync → Qdrant |
| `src/msbc/embedding/ingestors/examples_ingestor.py` | Same but for `correct_code_examples/` folder |
| `scripts/embed_toolkit.py` | CLI entry point for toolkit ingest |
| `scripts/embed_examples.py` | CLI entry point for examples ingest |

### 2.2 Two Collections

```
toolkit_openai_large_1536   ← all .ts/.tsx files from the RTK monorepo
examples_openai_large_1536  ← files from correct_code_examples/ folder
```

Both use: `text-embedding-3-large`, `dimensions=1536`, cosine distance.

### 2.3 Chunking Strategy

**Toolkit files** (`chunk_toolkit_file`):
- Min 200 tokens, max 800 tokens per chunk
- Files < 500 tokens → single chunk (no splitting)
- Uses tree-sitter for `.tsx`, regex for `.ts`
- Each chunk's embed text is **prepended with a context header**: package name, file path, exported symbols, msbc imports used — so metadata travels *inside* the vector

**Payload fields per chunk** (stored in Qdrant alongside the vector):
```
file_path, package_name, chunk_index, chunk_text,
exports[], msbc_imports[], file_id (SHA-256), chunk_type
```

**Examples** (`chunk_example_file`):
- Same chunking rules
- Extra payload: `example_id`, `group` (Dashboard/Form), `pattern`, `complexity`
- One synthetic **summary chunk** per example folder (natural-language description)

### 2.4 Incremental Sync Algorithm

```
1. Get stored {file_path → file_id (SHA-256)} from Qdrant
2. Scan disk for all .ts/.tsx files
3. Diff → ADD (new), UPDATE (hash changed), DELETE (removed)
4. DELETE: filter-delete all chunks for that file_path
5. ADD/UPDATE: chunk → embed → upsert
```

### 2.5 Run Commands

```bash
# From project root, WSL venv
source venv/bin/activate
python scripts/embed_toolkit.py
python scripts/embed_examples.py --full-sync   # force re-embed all
```

---

## 3. Kuzu Graph Database

### 3.1 Two Graphs in One DB File

The single file `./data/toolkit_graph.kuzu` holds **two layered graphs**:

| Graph | Script to build | What it captures |
|-------|----------------|-----------------|
| **Semantic graph** | `scripts/build_graph.py` | High-level toolkit knowledge: Package → Component → TypeDef, Feature, FieldType, Examples |
| **Code graph** | `scripts/build_rtk_code_graph.py` | File-level: SourceFile → ExportedSymbol, import/re-export edges |

They are linked by `SymbolLinkedToComponent` edges (ExportedSymbol → Component).

### 3.2 Files

| File | Role |
|------|------|
| `src/msbc/embedding/graph_schema.py` | All DDL constants (24 CREATE statements), DROP_ORDER list |
| `src/msbc/embedding/graph_builder.py` | Builds the **semantic graph** from `toolkit_knowledge.PACKAGES` dict + `correct_code_examples/` |
| `src/msbc/embedding/code_graph_builder.py` | Builds the **code graph** by scanning the monorepo source files |
| `src/msbc/agents/frontend_planner/toolkit_knowledge.py` | `PACKAGES` dict — source of truth for Component/TypeDef/Feature metadata |
| `scripts/build_graph.py` | CLI for semantic graph |
| `scripts/build_rtk_code_graph.py` | CLI for code graph (`--rebuild` flag to drop and recreate) |

### 3.3 Node Tables

**Semantic graph nodes:**
```
Package         — @msbc/* npm package (PK: name)
Component       — React component or hook (PK: "{package}::{name}")
TypeDef         — TS interface/type (PK: "{package}::{name}")
Feature         — capability flag e.g. has_search, has_filters
FieldType       — form field type e.g. fileUpload, select
Example         — one correct_code_examples/{group}/{id}/ folder
ExampleFile     — one source file inside an Example folder
```

**Code graph nodes:**
```
SourceFile      — one .ts/.tsx file (PK: "{package_name}::{rel_path}")
ExportedSymbol  — named export from a file (PK: "{package_name}::{symbol_name}")
```

### 3.4 Relationship Tables

**Semantic edges:**
```
BelongsTo           Component → Package
InternallyUses      Component → Component   (composition)
UsesType            Component → TypeDef
UsesHook            Component → Component   (data-layer hooks)
ExhibitsFeature     Component → Feature
SupportsFieldType   Component → FieldType
DemonstratesComponent Example → Component
ExhibitsFieldType   Example → FieldType
HasFile             Example → ExampleFile
```

**Code graph edges:**
```
FileBelongsTo        SourceFile → Package
ImportsFrom          SourceFile → SourceFile    (intra-package resolved import)
ImportsPackage       SourceFile → Package        (cross-package @msbc/* import)
ExportsSymbol        SourceFile → ExportedSymbol
ReExportsFrom        SourceFile → SourceFile     (export * from '...')
SymbolLinkedToComponent ExportedSymbol → Component  (bridge: code ↔ semantic)
```

### 3.5 How the Code Graph is Built

`code_graph_builder.py` does **regex-based** TypeScript scanning (no compiler):

1. Walk every `.ts`/`.tsx` file in each `packages/*` directory
2. Skip: `node_modules/`, `dist/`, `.test.ts`, `.stories.tsx`, etc.
3. For each file → insert `SourceFile` node + `FileBelongsTo` edge
4. Parse `import { X } from './path'` → resolve relative path → `ImportsFrom` edge
5. Parse `import { X } from '@msbc/pkg'` → `ImportsPackage` edge
6. Parse `export const/function/class/type X` → `ExportedSymbol` node + `ExportsSymbol` edge
7. Parse `export * from './path'` → `ReExportsFrom` edge
8. Match each `ExportedSymbol.name` against existing `Component` nodes → `SymbolLinkedToComponent` bridge

### 3.6 Current Graph Counts (after last build)

```
SourceFile:      97
ExportedSymbol: 178
Package:          6
FileBelongsTo:   97
ImportsFrom:     86
ImportsPackage:  43
ReExportsFrom:   78
ExportsSymbol:  179
SymbolLinkedToComponent: 0   ← 0 because semantic graph needs to be rebuilt first
```

`SymbolLinkedToComponent = 0` because `build_graph.py` (semantic graph) was not run after the last `--rebuild`. Run order must be: **semantic graph first, then code graph**.

### 3.7 Run Commands

```bash
# Build order — semantic first, then code graph
source venv/bin/activate

# Step 1: semantic graph (from toolkit_knowledge.PACKAGES + examples)
python scripts/build_graph.py

# Step 2: code graph (scans monorepo source)
python scripts/build_rtk_code_graph.py --rebuild \
  --monorepo-path /mnt/c/Users/yug.chauhan/Documents/GitHub/ReactToolKits
```

### 3.8 Kuzu Explorer (visualization)

```powershell
# From PowerShell — must use KUZU_DIR env var
docker run -d -p 8888:8000 `
  -v "C:\Users\yug.chauhan\Desktop\InHouseAgents\data:/database" `
  -e KUZU_DIR=/database `
  -e KUZU_FILE=toolkit_graph.kuzu `
  --name kuzu_explorer `
  kuzudb/explorer:latest
# Access: http://localhost:8888
```

**Critical**: `KUZU_DIR` must be set. Without it, the Explorer opens an in-memory (empty) database.

---

## 4. Known Weaknesses / Improvement Areas

### Qdrant
- **Chunk boundaries are arbitrary** — splits happen at blank lines, not at semantic unit boundaries (e.g., a component's JSX + props split across two chunks)
- **Context header is hand-crafted** — exports/imports are regex-extracted; TypeScript type information (prop types, generic constraints) is not captured in the embed text
- **No re-ranking** — retrieval is pure cosine similarity, no cross-encoder re-rank pass
- **Examples summary chunk** is generated heuristically, not by an LLM — may miss the actual intent of the example

### Kuzu Graph
- **Regex-based import parsing** — does not resolve re-exported symbols across package boundaries (e.g., `@msbc/react-toolkit` re-exports from `@msbc/config-ui`; the resolved chain is not followed)
- **`SymbolLinkedToComponent` depends on name matching** — if a Component in `toolkit_knowledge.py` uses a different casing or alias than the actual export, the bridge edge is missing
- **`toolkit_knowledge.py` is hand-maintained** — Component metadata (description, when_to_use, do_not_use_when) is written by hand and may be outdated vs. the actual source
- **No prop-type nodes** — component props/config shapes are not in the graph; this would be very valuable for generation
- **ReExportsFrom chain not followed** — a file that does `export * from './a'` and `./a` does `export * from './b'` does not create a transitive edge

---

## 5. Source of Truth for Component Metadata

`src/msbc/agents/frontend_planner/toolkit_knowledge.py` → `PACKAGES` dict.

This dict is the **only** place where human-authored component metadata lives. The semantic graph and Qdrant payloads are both derived from it. If the RTK library adds a new component, it must be manually added here before either build step picks it up.

---

## 6. Config Keys (app/core/config.py)

```python
QDRANT_URL: str = "http://localhost:6333"
QDRANT_API_KEY: str = ""
OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
EMBEDDING_DIMENSIONS: int = 1536
RTK_MONOREPO_PATH: str = ""          # path to ReactToolKits repo
EXAMPLES_DIR: str = "correct_code_examples"
KUZU_DB_PATH: str = "./data/toolkit_graph.kuzu"
```
