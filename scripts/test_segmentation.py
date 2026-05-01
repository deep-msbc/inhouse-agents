"""
scripts/test_segmentation.py
─────────────────────────────
Quick diagnostic tool for the segmentation phase (Phase 0) of the extraction
pipeline.  Lets you validate module detection on any DOCX/PDF without running
the full API server.

Usage
-----
  # Test with an actual document file:
  python scripts/test_segmentation.py --file "path/to/document.docx"
  python scripts/test_segmentation.py --file "path/to/document.docx" --full

  # Test with a pre-extracted heading-hierarchy JSON file:
  python scripts/test_segmentation.py --headings-json "path/to/headings.json"
  python scripts/test_segmentation.py --headings-json "path/to/headings.json" --full

Modes
-----
  (default)  Python-only: extract heading hierarchy and run the Python
             pre-clean step.  Shows what the LLM will receive.  Fast, no LLM call.

  --full     Also call the LLM classification node and show which headings
             are marked as MODULE.  Requires OPENAI_API_KEY to be set.

Options
-------
  --file FILE             Path to the DOCX or PDF file.
  --headings-json FILE    Path to a JSON file containing a heading hierarchy
                          ([{"level": N, "text": "…"}, …]).
  --full                  Also run the LLM classification call.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# ── Force UTF-8 stdout on Windows (avoids cp1252 UnicodeEncodeError) ─────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Make sure the project root is on sys.path ──────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_file(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _print_section(title: str) -> None:
    width = 70
    print()
    print("-" * width)
    print(f"  {title}")
    print("-" * width)


async def run_llm_segmentation(document_text: str, heading_hierarchy: list[dict]) -> list[dict]:
    """Call the actual segmentation_node with a minimal ExtractionState."""
    from src.msbc.orchestration.nodes.node_definitions import segmentation_node

    state = {
        "document_text":    document_text,
        "heading_hierarchy": heading_hierarchy,
        "mode":             "frontend",
    }
    result = await segmentation_node(state)  # type: ignore[arg-type]
    return result.get("modules", [])


def _print_headings_and_precleaned(
    heading_hierarchy: list[dict],
    document_text: str,
    args: argparse.Namespace,
) -> None:
    """Shared: print heading stats and the pre-cleaned list that goes to the LLM."""
    from collections import Counter

    _print_section("Heading Hierarchy")
    print(f"  Total headings: {len(heading_hierarchy)}")

    level_counts = Counter(h.get("level", "?") for h in heading_hierarchy)
    for lvl in sorted(level_counts):
        print(f"    Level {lvl}: {level_counts[lvl]} heading(s)")

    if heading_hierarchy:
        print("\n  First 15 headings:")
        for h in heading_hierarchy[:15]:
            indent = "    " + "  " * max(0, (h.get("level", 1) - 1))
            print(f"{indent}[L{h.get('level','?')}] {h.get('text', '')[:80]}")
        if len(heading_hierarchy) > 15:
            print(f"    … ({len(heading_hierarchy) - 15} more)")

    _print_section("Python Pre-Clean — Headings sent to LLM")
    from src.msbc.orchestration.nodes.node_definitions import _pre_clean_headings

    cleaned = _pre_clean_headings(heading_hierarchy)
    print(f"  Pre-cleaned count: {len(cleaned)} (of {len(heading_hierarchy)} total)")
    for i, h in enumerate(cleaned, 1):
        print(f"    {i:3d}. [L{h['level']}] {h['text'][:80]}")
    if not cleaned:
        print("  (no headings after pre-clean — check document structure)")
    print()
    print("  NOTE: Run with --full to see which of these the LLM marks as MODULE.")


def _run_llm(document_text: str, heading_hierarchy: list[dict]) -> None:
    """Run the full LLM classification call and print results."""
    _print_section("LLM Classification (full call)")
    try:
        modules = asyncio.run(run_llm_segmentation(document_text, heading_hierarchy))
        print(f"  Modules identified by LLM: {len(modules)}")
        for i, m in enumerate(modules, 1):
            print(
                f"    {i:2d}. [{m.get('heading', '?')[:60]}]"
                f"  →  {m.get('name', '?')}"
            )
            desc = m.get("description", "")
            if desc:
                print(f"         {desc[:100]}")
    except Exception as exc:
        print(f"  ERROR during LLM call: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test the segmentation (module-detection) step of the pipeline."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file", help="Path to a DOCX or PDF file.")
    input_group.add_argument(
        "--headings-json",
        metavar="FILE",
        help=(
            "Path to a JSON file containing a heading hierarchy "
            '([{"level": N, "text": "…"}, …]).  Skips text/heading extraction.'
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also run the LLM classification call (requires OPENAI_API_KEY).",
    )
    args = parser.parse_args()

    # ── Mode A: heading hierarchy JSON ────────────────────────────────────────
    if args.headings_json:
        json_path = Path(args.headings_json).expanduser().resolve()
        if not json_path.exists():
            print(f"ERROR: File not found: {json_path}", file=sys.stderr)
            sys.exit(1)
        with open(json_path, encoding="utf-8") as fh:
            heading_hierarchy = json.load(fh)
        document_text = ""
        print(f"\nInput: heading-hierarchy JSON — {json_path.name}")
        print(f"Mode : {'Python + LLM' if args.full else 'Python only (fast)'}")
        _print_headings_and_precleaned(heading_hierarchy, document_text, args)
        if args.full:
            _run_llm(document_text, heading_hierarchy)
        print()
        return

    # ── Mode B: document file ─────────────────────────────────────────────────
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    suffix = file_path.suffix.lower()
    if suffix not in {".docx", ".pdf"}:
        print(f"ERROR: Unsupported file type '{suffix}'. Use .docx or .pdf.", file=sys.stderr)
        sys.exit(1)

    from src.msbc.utils.extractors import extract_heading_hierarchy, extract_text_from_file

    print(f"\nFile : {file_path.name}")
    print(f"Mode : {'Python + LLM' if args.full else 'Python only (fast)'}")

    file_bytes = _load_file(file_path)
    mime = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".docx"
        else "application/pdf"
    )

    _print_section("Step 1 — Extract document text")
    document_text = extract_text_from_file(file_bytes, file_path.name, mime)
    print(f"  Characters: {len(document_text):,}")
    print(f"  Preview   : {document_text[:200].replace(chr(10), ' ')!r}")

    _print_section("Step 2 — Extract heading hierarchy")
    heading_hierarchy = extract_heading_hierarchy(file_bytes, file_path.name, mime)

    _print_headings_and_precleaned(heading_hierarchy, document_text, args)

    if args.full:
        _run_llm(document_text, heading_hierarchy)

    print()


if __name__ == "__main__":
    main()
