Plan: Fix Requirement Extractor — Module Detection & Reliability
TL;DR: Two independent root causes. Problem A (wrong modules) is a heading detection gap where the DOCX extractor only reads Word paragraph styles, missing all bold/numbered sections without styles. Problem B (timeouts) is a cascade: bad segmentation → giant text slices → too many parallel LLM calls → rate limit → timeout. Problem C (0 APIs) is the LLM dropping api_endpoints to fit within output token limits when the both prompt is too large. Each has a targeted, layered fix.

Root Cause Deep Dive
Why Hardware Tab was missed (and similar gaps in all docs):

The flow is: extract_heading_hierarchy() → heading hierarchy JSON → segmentation LLM → _slice_module_text() → extraction LLM.

The DOCX files use plain bold/numbered paragraphs like "3.2.4 Hardware Tab" that are NOT styled as "Heading 4" in Word. Since these docs DO have at least some proper heading styles (e.g. Title), extract_heading_hierarchy() returns a non-empty list and never triggers the heuristic fallback. So "3.2.4 Hardware Tab" never reaches the segmentation LLM. The segmentation LLM only sees Positions Tab, Profiles Tab, Glass Tab, Accessories Tab — skips Hardware. Then _slice_module_text() slices from "Glass Tab" to "Accessories Tab", which includes Hardware Tab's full text — but since the module_name is "Glass Tab", the extraction LLM ignores it entirely.

Why Stock 2, Stock 3, PO Module time out:

Same segmentation failure → a 1,200+ line document gets identified as 1-2 giant modules → each module slice exceeds the 12,000-token budget → split into 8–10 chunks → "both" mode runs 2 LLM calls per chunk (FE + BE) + 1 summary → up to 21 concurrent LLM calls per module → OpenAI 429 rate limits → exponential backoff → MODULE_EXTRACTION_TIMEOUT=600s fires → job fails.

Why backend APIs are always 0:

both_extraction.yaml is 200+ lines — the system prompt alone is ~3,000+ tokens. With TOTAL_INPUT_TOKEN_LIMIT=16,000 and ~4,000 token prompt overhead, the module text budget shrinks. When the LLM has to produce both FE screens (large) AND BE api_endpoints (also large), it drops api_endpoints silently to stay within output token limits. This is systematic, not random — every single module across every successful response has exactly 0 APIs.

Phase 1 — Fix Heading Detection (docx_extractor.py)
Change extract_heading_hierarchy() from single-layer to dual-layer:

Currently: style-based ONLY → if no styles, heuristic fallback (mutually exclusive).

New: ALWAYS run both, merge results:

Layer 1 (existing): para.style.name contains "heading" → level from style number
Layer 2 (NEW): Scan every paragraph regardless of style for:
All runs bold (para.runs[0].bold) AND text matches ^\d+(\.\d+)*\.?\s+
Font size ≥ 14pt inferred from XML (w:sz attribute ≥ 28 half-points)
w:outlineLvl XML attribute set (Word's internal outline level, independent of style name)
Merge both layers, deduplicate by text, preserve document order
Result: "3.2.4 Hardware Tab" now appears in hierarchy → segmentation LLM sees it → correct module identified.

Phase 2 — Enhance Segmentation Prompt (segmentation.yaml)
Pass richer context to the segmentation LLM — not just heading text:

For each heading candidate, include its first 2 lines of body text (gives the LLM enough context to understand if it's a real functional module or just an introductory paragraph)
Add domain rule: "numbered sections like 8., 9., 10. in ERP/business documents are ALWAYS separate functional modules — never group them together"
Add explicit rule: "if you see tab names like 'Profiles Tab', 'Glass Tab', 'Hardware Tab' — each is its own module"
Add constraint: "produce at least one module per top-level numbered section (1., 2., 3. etc.)"
Phase 3 — Python Pre-Segmentation Layer (node_definitions.py — segmentation_node)
Before calling the LLM, run a Python structural outline pass:

Regex-scan document text for top-level numbered sections: ^\s*(\d+)\.\s+[A-Z]
These become guaranteed module boundaries — the LLM cannot merge them
Pass these as "seed modules" in the segmentation prompt: "The following sections MUST remain as separate modules; you may split further but not merge them:"
This gives the LLM a hard constraint derived from document structure itself, not from what it guesses.

Phase 4 — Stop Running FE and BE in Full Parallel (node_definitions.py — _extract_chunk_for_mode)
In "both" mode, the code currently launches fe_prompt and be_prompt as two parallel coroutines per chunk. For a module with N=8 chunks: 16 LLM calls + 1 summary = 17 simultaneous calls.

Fix: run FE chunks in parallel (fine), then BE chunks in parallel (separately). This halves peak concurrency from 2N+1 to N+1 and gives each call more of the rate limit budget.

Phase 5 — Batched Module Fan-out for Large Documents (build_slices_node)
If total modules > 6 OR estimated document tokens > 40,000 (≈300 lines): process modules in batches of 3 using asyncio.gather in groups rather than one big Send fan-out. Each batch completes before the next starts, capping concurrent calls at 3 modules × 3 calls = 9 at any time.

This is the key fix for Stock 2, Stock 3, PO Module.

Phase 6 — Numbered-Section-Aware Chunking (_split_module_into_chunks)
Current splitter looks for ## heading Markdown markers or blank lines. These docs don't produce Markdown headings for numbered sections (they're plain text).

Fix: add numbered section boundary as a primary split point:

Pattern: ^\s*\d+(\.\d+)+\.?\s+[A-Z] (sub-sections like 8.1, 8.2, 9.1...)
Never split a numbered section mid-way — each becomes its own logical unit
This ensures "8.16 Transaction History Impact" and "8.17 Print Format" are in the same chunk as "8. Material Issue With Job", not separated across chunks where the LLM loses context of what they belong to
Phase 7 — Fix Backend API Generation (both_extraction.yaml + normalizer)
Three-pronged fix:

Prompt-level: Move the API extraction instruction near the top of the system prompt (currently buried in the middle), and add: "An empty api_endpoints array is ALWAYS incorrect. Every toolbar action in the frontend requires at least one corresponding API endpoint."
Token space: Raise TOTAL_INPUT_TOKEN_LIMIT from 16,000 to 24,000 (the model supports 128k context; 16k was a conservative legacy setting) — gives the LLM more output space
Validation retry: In _extract_chunk_for_mode, after merging chunk results, check: if api_endpoints is empty but models is not empty → trigger one retry with an explicit note appended to the user prompt: "Your previous response omitted api_endpoints. You MUST generate them now."
Relevant Files
docx_extractor.py — Phase 1: dual-layer heading detection
segmentation.yaml — Phase 2: prompt enhancement
node_definitions.py — Phase 3, 4, 5, 6: pre-segmentation, FE/BE split, batching, chunking
both_extraction.yaml — Phase 7: API enforcement
config.py — Phase 7: raise TOTAL_INPUT_TOKEN_LIMIT
Verification
Run Job Module 1 → Hardware Tab appears as Module 4 (not missing)
Run Job Module 1 → JobMaterialLedger has all 5 tabs populated, not 0
Run Stock Module 2 → completes without timeout, all 6 sections (2–7) as separate modules
Run PO Module → all major section groups (MR types, PO flows, GRN) as separate modules
Any completed response → api_endpoints is non-empty for at least 1 module
Job Module 1 → be.api_endpoints count > 0
Decisions and Priorities
Phase 1 + 3 together are the highest-priority fixes — they address the root cause of both module detection failures AND cascade timeouts. Fix segmentation → smaller, better-defined slices → fewer chunks → less concurrent load → timeouts stop.
Phase 5 (batching) is a safety net that should be implemented alongside Phase 1+3 as a guard for future large documents.
Phase 7 (API fix) is independent and lower-risk — it improves quality of already-succeeding responses.
Phase 2 (segmentation prompt) should be done after Phase 1 so the LLM gets the richer heading input first.
Phase 4 and 6 are secondary refinements once the above stabilize results.