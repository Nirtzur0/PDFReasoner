# Shape Up Audit & Pitch — PaperCoach (PDF Tutor Layer)

## Assumptions I’m making (since you didn’t fill the inputs yet)
- **Idea**: “PaperCoach” — a tool that takes a research PDF and outputs the *same paper* visually enhanced: highlights + margin commentary + symbol glossary + mind map + citation tracing.
- **Target user**: students / researchers / engineers reading math-heavy papers, usually under time pressure (e.g., school, lab, interview prep).
- **Context**: they already have PDFs; they want understanding “at first glance,” not a separate summary doc.
- **Reliability constraint**: for math, we **explain what’s there** and don’t “complete” equations or invent derivations; all commentary must be grounded.
- **Constraints**: small team; must be bettable in one cycle; avoid needing perfect OCR or full LaTeX reconstruction; privacy matters (local-first preferred).

If any of those are off, the shape will drift—but this is a reasonable default framing.

---

# Step 1 — Problem framing (the “raw idea” audit)

### 1) What’s the real problem? (1 sentence)
People waste hours re-deriving context and chasing references just to understand a math-heavy paper’s **core ideas and dependencies**.

### 2) Who feels the pain and when?
- **Primary user**: a student or early-career researcher reading math/ML/CS papers.
- **Scenario**: they open a PDF and hit dense definitions, symbol overload, and “as in [12]” references that block comprehension.

### 3) What’s the job-to-be-done? (Outcome the user wants.)
> “I want to read this paper once and quickly understand what’s going on, what each symbol means, what claims depend on what, and what the cited works contribute—without getting lost.”

### 4) What’s in/out of scope? (Define boundaries early.)

**In scope (MVP bettable slice):**
- Born‑digital PDFs (selectable text)
- Highlight key structures (definitions/theorems/claims/equations/citations)
- Margin notes: plain-language explanation + “why it matters” + grounded pointers
- Symbol glossary (first occurrence + meaning when explicitly stated nearby)
- Reference tracing to metadata + abstracts for the most important citations
- One global mind map (concept dependency graph)

**Out of scope (for this cycle):**
- Scanned/OCR-first PDFs
- “Complete the missing math” / generate new derivations
- Perfect figure/table understanding
- Full citation-graph exploration beyond what the paper directly uses
- A full interactive PDF reading app (start as CLI + output PDF)

### 5) What’s the “no-go” version? (What this should NOT become.)
- Not a “summarize this paper” bot that ignores the paper’s layout.
- Not a math-solver / proof generator.
- Not a giant “read the whole internet” research assistant.
- Not a brittle pipeline that only works on one publisher format.
- Not a cloud-only product that forces uploading copyrighted PDFs.

## Deliverables (Step 1)

### Problem statement (1 sentence)
A tool to make research PDFs understandable at a glance by adding grounded highlights, margin explanations, symbol clarity, and citation tracing.

### Top 3 user pains
1. **Symbol overload**: too many variables/notations introduced implicitly or scattered.
2. **Implicit reasoning**: “clearly/obvious/as in…” hides key conceptual steps.
3. **Reference chasing**: core ideas depend on cited papers, but the user can’t quickly see what is being imported.

### Non-goals (3–5)
- Solve or complete equations / generate missing derivations.
- Guarantee “PhD-perfect correctness” without evidence.
- Support scanned PDFs/OCR in the initial bet.
- Build a full GUI reader (start with output artifacts).
- Do comprehensive literature review beyond the paper’s direct citations.

---

# Step 2 — Appetite (time box, not scope)

## Appetite choice: Standard cycle (4–6 weeks)
**Rationale**: A bettable MVP needs (1) reliable PDF anchoring + (2) plan→render separation + (3) citation tracing + (4) usable visuals. That’s too risky for 1–2 weeks, but reasonable in a standard cycle if we keep hard boundaries.

## “If we only had half the time” cut-list
Cut these first to fit 2–3 weeks:
- Mind map generation and embedding
- External citation enrichment beyond “top N” citations (keep minimal metadata only)
- Fancy multi-column layout handling; support “common” formats only
- Deep commentary breadth; focus on definitions/theorems + section TL;DR
- Proof-skip detection beyond basic phrase triggers

---

# Step 3 — Shaping the solution (not a spec)

## 3A) Core value proposition
**Users can read a math-heavy PDF with highlights and grounded margin commentary so that they grasp key ideas, notation, and citation dependencies in one pass.**

## 3B) Solution outline (high-level)
- **Analyzer**: reads PDF text + layout (blocks/spans with coordinates) and identifies anchor points (definitions, theorems, citations, key equations).
- **Evidence Builder**: constructs a symbol table and citation map; resolves top references to stable identifiers (DOI / Semantic Scholar / OpenAlex) and retrieves minimal, cacheable evidence (title/year/abstract snippet).
- **Commentary Shaper**: generates short explanations attached to anchors and backed by evidence; produces an Annotation Plan (structured JSON) with confidence flags.
- **Renderer**: composes a new PDF with a right margin, draws highlights, places notes without covering original text, and appends a glossary + references summary + (optional) mind map.

## 3C) Breadboarding (key flows)
1. User runs `papercoach annotate paper.pdf`.
2. System extracts layout-aware text and detects structure (sections, definitions, theorems, citations).
3. System builds a symbol glossary from first occurrences and “where/denotes/defined as” patterns.
4. System parses references and links in-text citations → bibliography entries.
5. System enriches the top cited references (e.g., top 10 by mentions) to fetch title/year/abstract snippet (cached).
6. System generates grounded margin notes for anchors (definition/theorem/citation import + section TL;DR).
7. System outputs `annotation_plan.json` + `evidence_ledger` showing what each note is grounded on.
8. Renderer produces `enhanced.pdf` with highlights + margin notes + glossary appendix (+ optional mind map page).

## 3D) Fat Marker Sketch (rough CLI/API surface)
**CLI surfaces**
- `papercoach annotate INPUT.pdf --out enhanced.pdf --level light|medium --no-web`
- `papercoach plan INPUT.pdf --out annotation_plan.json` (analysis only)
- `papercoach render INPUT.pdf annotation_plan.json --out enhanced.pdf` (render only)

**Core artifact types**
- `AnnotationPlan` (pages → anchors → highlights → margin notes; plus glossary + citations)
- `EvidenceLedger` (one entry per note: paper quote pointers + external reference snippet pointers)

**Output pages**
- Original pages with a right margin of notes
- Appendix: symbol glossary + “references imported here” summary
- Optional: mind map page

---

# Step 4 — Risks, rabbit holes, and unknowns (pre-mortem)

| Risk | Why it’s risky | De-risk test (fast) | Fallback |
|---|---|---|---|
| PDF layout variability | Multi-column, floats, weird fonts break anchor detection | Test on 15 diverse PDFs; measure % anchors correctly located | Narrow supported formats in v1; warn “layout unsupported” |
| “PhD-like commentary” expectation | Scope can explode; hard to meet without hallucination | Force evidence ledger; sample 50 notes; audit grounding rate | Reposition: “grounded guide,” not “PhD replacement” |
| Hallucinated citation tracing | Easy to claim origins without proof | Require external snippet/metadata + quote from “as in [k]” line | If no proof, output “unverified; see reference” |
| Note placement collisions | Margin notes can overlap or become unreadable | Render on dense pages; set max notes/page; layout algorithm test | Cap notes per page + carry overflow to end-of-section summary page |
| Evaluation is subjective | “Understandable” is hard to measure | Define proxy metrics: time-to-answer comprehension quiz; user rating | Use acceptance tests: “can locate meaning of 10 symbols quickly” |
| API limits / privacy concerns | External enrichment might leak PDFs or hit rate limits | Ensure only bib strings are sent; add `--no-web`; cache | Default local-only mode; optional enrichment toggle |

---

# Step 5 — Define “Done” (integration-level, not tasks)

## Done means (acceptance criteria)
1. Given a born‑digital research PDF, the tool outputs `enhanced.pdf` that preserves original pages and adds a readable right margin.
2. At least **one section TL;DR note per section** (or per major heading) appears, anchored correctly.
3. Definitions/theorems are highlighted and have margin notes explaining meaning + why it matters, grounded in nearby text.
4. A **symbol glossary appendix** is generated with first occurrence page references for at least the top 20 symbols detected.
5. In-text citations are detected and linked to bibliography entries; at least the top 10 referenced works are summarized using retrieved metadata/abstract snippets (unless `--no-web`).
6. Every margin note has an evidence ledger entry; low-confidence notes are clearly labeled.
7. Runs end-to-end in a single command, producing stable artifacts in a work directory.

## Success metrics (measurable outcomes)
- **Time-to-orient**: median time for users to answer 5 “what does X mean?” questions drops by ≥40%.
- **Grounding rate**: ≥85% of notes have explicit paper evidence and/or external snippet evidence.
- **User usefulness score**: ≥4/5 average on “helped me understand faster” (pilot n≈10–20).
- **Anchor accuracy**: ≥90% of highlights overlap the intended text blocks in evaluation PDFs.

## Demo script (5 steps)
1. Show the original PDF page (dense math section).
2. Run `papercoach annotate`.
3. Open `enhanced.pdf`: point out definition highlight + margin explanation + symbol meanings.
4. Show a citation tracing note that explains what was imported from [12].
5. Jump to glossary appendix and demonstrate fast symbol lookup; (optional) show mind map.

## Out of bounds (this cycle)
- Scanned PDFs + OCR
- Equation completion or proof generation
- Full figure/table extraction
- Full web-scale literature mapping
- GUI reader app

---

# Step 6 — Betting decision (Shape Up “bet or not”)

## Decision: RESHAPE
### Rationale
The raw idea is strong, but not yet bettable as stated because “PhD-like explanation” + “math gap filling” + “mind maps” + “reference tracing” + “works on any PDF” is too broad and risks a cycle ending in a brittle demo. We need a tighter slice with a clear definition of reliability and supported inputs.

### Smallest bettable slice (MVP-with-boundaries)
**Born‑digital PDF Enhancer: Highlights + Grounded Margin Notes + Symbol Glossary + Citation Tracing (Top N)**

- Only born-digital PDFs
- Notes limited to definition/theorem/section/citation-import anchors
- Evidence-first commentary with confidence flags
- External enrichment limited to top N references (optional)

### What to cut to fit appetite
- Mind map page (move to next cycle) — or keep only a very simple “section dependency” diagram
- Any OCR / Nougat / equation OCR
- Anything beyond top‑N citation enrichment

### Pitch summary (one paragraph)
Build a local-first tool that outputs the same research PDF with highlights and a right-margin “guided reading layer,” focused on definitions, theorems, symbols, and citation imports. All notes are grounded in the paper or retrieved reference metadata/abstract snippets, with confidence labeling. Ship as CLI with plan→render separation and produce stable artifacts for iteration.

---

# Final deliverable — A one-page Shape Up pitch

## Pitch Title
**PaperCoach MVP: Grounded PDF Annotations for Math-Heavy Papers**

## Problem
Reading research PDFs is slow because key notation and imported ideas from references are implicit, forcing readers to re-derive context and chase citations.

## Appetite
**Standard cycle (4–6 weeks)** — enough to nail PDF anchoring + grounded notes + citation tracing with clear boundaries.

## Solution (shaped)
Create a pipeline that analyzes a born‑digital PDF into a structured **Annotation Plan** (highlights + anchored notes + glossary + citation map), then renders an enhanced PDF with a right margin. Notes are evidence-backed and explicitly labeled when uncertain. Citation notes trace “as in [k]” imports back to the referenced work’s retrieved metadata/abstract.

## Breadboard
1. User runs annotate command on a PDF.  
2. System extracts layout-aware text + anchors.  
3. System highlights definitions/theorems/equations/citations.  
4. System builds a symbol glossary and citation map.  
5. System optionally resolves top‑N citations to DOI/S2 and fetches abstracts (cached).  
6. System generates grounded margin notes + confidence flags.  
7. System renders enhanced PDF with right-margin notes + glossary appendix.  
8. Outputs plan + evidence ledger for auditing.

## Fat Marker Sketch
- CLI: `annotate`, `plan`, `render`  
- Outputs: `enhanced.pdf`, `annotation_plan.json`, `evidence_ledger.jsonl`, glossary appendix  
- Page layout: original page on left + margin notes on right; overflow notes go to end-of-section summary pages.

## Risks & Rabbit Holes
- Layout variability → limit to born-digital + common formats; test suite of diverse PDFs.
- “PhD-level” expectation → define grounded notes and confidence labeling; avoid proof/equation completion.
- Citation origin tracing → only claim what’s supported by “as in [k]” text + retrieved abstract/metadata.

## Done / Acceptance Criteria
Enhanced PDF produced with correct anchoring, readable margins, glossary appendix, citation tracing notes, and evidence ledger entries for each note.

## Success Metrics
- ≥40% improvement in time-to-answer symbol/claim questions  
- ≥85% grounded notes  
- ≥90% highlight anchor accuracy  
- ≥4/5 usefulness rating in pilot

## Betting Decision
**RESHAPE** → then **BET** on the narrowed MVP slice above for a standard cycle.

---

## Optional: Two alternative bets (if priorities change)
1. **Reader UX first**: focus on rendering + layout + note placement + glossary, minimal citation enrichment.
2. **Scholar graph first**: focus on citation tracing + “imported ideas” notes + reference summaries, minimal layout polish.
