Commands to run (WSL, venv)

# Activate venv (in InHouseAgents project root)
cd /c/Users/yug.chauhan/Desktop/InHouseAgents
source venv/bin/activate

# ── Step 1: Embed the RTK toolkit into Qdrant ─────────────────────────────
# (full-sync forces re-embed — use this the first time or after chunker changes)
python scripts/embed_toolkit.py --full-sync

# Or incremental (only changed files):
python scripts/embed_toolkit.py

# ── Step 2: Embed the correct_code_examples into Qdrant ───────────────────
python scripts/embed_examples.py --full-sync

# ── Step 3: Build the KUZU semantic graph (must come BEFORE code graph) ───
python scripts/build_graph.py --rebuild

# ── Step 4: Build the KUZU code graph (links source files to components) ──
python scripts/build_rtk_code_graph.py --rebuild \
  --monorepo-path /mnt/c/Users/yug.chauhan/Documents/GitHub/ReactToolKits
View the Kuzu graph in Docker (localhost:8888)

# Run from PowerShell (Windows)
docker run -d -p 8888:8000 `
  -v "C:\Users\yug.chauhan\Desktop\InHouseAgents\data:/database" `
  -e KUZU_DIR=/database `
  -e KUZU_FILE=toolkit_graph.kuzu `
  --name kuzu_explorer `
  kuzudb/explorer:latest
Then open http://localhost:8888 in your browser.

Useful queries to verify the graph:


-- Count all node types
MATCH (n:Component) RETURN count(n);
MATCH (n:SourceFile) RETURN count(n);
MATCH (n:ExportedSymbol) RETURN count(n);

-- Check bridge edges (should be > 0 after both graphs are built)
MATCH ()-[r:SymbolLinkedToComponent]->() RETURN count(r);

-- See ConfigurableDashboard's features
MATCH (c:Component {name: 'ConfigurableDashboard'})-[:ExhibitsFeature]->(f:Feature)
RETURN f.name, f.label;

-- Find examples with search + filters
MATCH (e:Example)-[:ExhibitsFeature]->(f:Feature)
WHERE f.name IN ['has_search', 'has_filters']
WITH e, COUNT(f) AS matched WHERE matched = 2
RETURN e.example_id, e.use_case;
Important: Always run build_graph.py (semantic) before build_rtk_code_graph.py (code graph) — the bridge SymbolLinkedToComponent edges require Component nodes to exist first.