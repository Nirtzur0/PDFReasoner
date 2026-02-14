# PaperCoach — Implementation Prompt (Python)

Use this prompt to implement a Python project that **reads an academic PDF** and produces a **visually enhanced PDF** with:

- highlights (definitions, theorems, key claims/equations),
- **reliable margin commentary** (plain-language explanations + intuition),
- **symbol/notation glossary** (auto-built),
- **reference tracing** (track ideas back to cited papers, with evidence),
- **mind maps** (concept graph per paper + optional per section).

The output should feel like a careful PhD tutor annotated the paper—**without inventing math** or making unsupported claims.

---

## 0) Role and Output

**You are a senior engineer** building a production-grade MVP. Deliver working code, a CLI, and a reproducible pipeline.

### Primary deliverable
A CLI command:

```bash
papercoach annotate input.pdf --out enhanced.pdf --workdir runs/paper1 --level medium
```

that produces:

- `enhanced.pdf` (original paper + right-side margin notes + highlights + mind map pages)
- `annotation_plan.json` (the authoritative structured plan used to render the PDF)
- `evidence_ledger.jsonl` (one record per annotation, containing evidence pointers)
- `mindmap.png` (and optional per-section maps)
- logs + a minimal HTML report (optional) showing any low-confidence notes

---

## 1) Hard Constraints (Do Not Violate)

### 1.1 Reliability guardrails
- **Never “complete” missing math** or invent derivation steps.
- You may explain what is present, and you may outline *possible* intermediate steps only when clearly labeled as *hypothesis* and when supported by standard identities (and ideally verified).
- Every margin note must be backed by an **evidence ledger entry**:
  - either a quote/snippet from the paper itself,
  - or a specific referenced paper (DOI / Semantic Scholar paperId) with a snippet/abstract sentence.

If the system cannot find evidence, it must output a note like:
> “Interpretation likely X, but I can’t ground it in the text or references I retrieved.”

### 1.2 Reference tracing requirement
When the paper says “as in [12]” / “following Smith (2019)”:
- create a margin note that:
  1) explains what’s being imported (method/definition/assumption),
  2) links to the reference entry,
  3) optionally summarizes the cited work **using retrieved metadata/abstract** (not hallucinations),
  4) stores evidence links in the ledger.

### 1.3 PDF anchoring requirement
All annotations must be anchored to **page coordinates** (bounding boxes).
No “floating” commentary without a known anchor.

---

## 2) Scope (MVP First)

### MVP must support
- **Born-digital PDFs** (selectable text)
- Layout extraction using PyMuPDF
- Highlights for:
  - Abstract, key definitions, theorems/lemmas/propositions, proof blocks,
  - key equations (displayed math blocks, by layout heuristics)
- Margin commentary:
  - “TL;DR” for each section,
  - “What this means” for definitions and theorem statements,
  - proof-skips detector (phrases like “obvious”, “clearly”, “we omit”)
- Symbol glossary (first occurrence + definition guess from nearby text)
- References:
  - parse bibliography entries,
  - in-text citation linkage and tracing notes
- Mind map:
  - global concept map of sections → definitions → theorems → methods → references

### Optional later (V2/V3)
- OCR/scanned PDFs
- equation OCR (pix2tex) / Nougat
- arXiv LaTeX source ingestion

---

## 3) Recommended Tech Stack

- **PyMuPDF (`pymupdf`)**: text blocks, coordinates, rendering, and PDF composition.
- **GROBID** (via local Docker or service): references + structure (optional in MVP, but recommended).
- **Crossref + Semantic Scholar** APIs for citation resolution/enrichment (make this optional + cache results).
- **Graphviz** for mind map rendering.
- **Pydantic** models for validated internal data structures.
- **typer** or **argparse** for CLI.

> Important: Implement caching for all external API calls.

---

## 4) System Architecture

Implement as a two-step pipeline:

1) **Analyze** → produce `annotation_plan.json` (no PDF drawing here)
2) **Render** → produce `enhanced.pdf` from the plan

This separation makes debugging reliable.

### 4.1 Core artifact: AnnotationPlan
The plan must contain:

- `paper_id` (hash of input PDF bytes)
- per page:
  - highlights: rectangles with tags
  - anchors: text spans / block IDs with bounding boxes
  - margin notes: note title/body + anchor bbox + evidence pointers + confidence
- global additions:
  - symbol glossary entries (symbol → meaning → first_occurrence_page/bbox)
  - reference table (bib entries + resolved IDs)
  - mind map outputs (paths to images)

---

## 5) Data Models (Pydantic)

Create these models (minimum):

- `TextBlock(page:int, block_id:str, bbox:Rect, text:str, font_meta:dict)`
- `Citation(bib_key:str|None, raw:str, in_text_spans:[SpanRef], resolved:ResolvedRef|None)`
- `ResolvedRef(doi:str|None, s2_paper_id:str|None, title:str|None, year:int|None, venue:str|None, url:str|None)`
- `Highlight(page:int, bbox:list[float], tag:str)`
- `MarginNote(page:int, anchor_bbox:list[float], note_bbox:list[float], title:str, body:str, evidence:list[EvidenceRef], confidence:float, flags:list[str])`
- `EvidenceRef(type:"paper"|"external", pointer:dict, quote:str|None)`
- `AnnotationPlan(paper_id:str, meta:dict, pages:dict[int, PagePlan], references:list[Citation], glossary:list[GlossaryItem], mindmaps:list[MindmapArtifact])`

---

## 6) Analysis Stage Details

### 6.1 Extract text blocks + coordinates
Using PyMuPDF:
- `page.get_text("blocks")` or `page.get_text("dict")` to get blocks/spans.
- Preserve reading order heuristics (y then x).
- Store block IDs deterministically (page + index + hash of text).

### 6.2 Detect structure (sections, headings)
Heuristics MVP:
- headings often have larger font sizes / bold
- numbered headings: `^\d+(\.\d+)*\s+`
- detect Abstract / Introduction / Related Work / Methods / Experiments / Conclusion / References

If GROBID available:
- parse TEI for sections + bibliography.

### 6.3 Identify key items to highlight
Rules:
- highlight theorem-like lines:
  - regex: `^(Theorem|Lemma|Proposition|Corollary|Definition|Assumption)\b`
- highlight displayed equations:
  - blocks with high math symbol density and centered alignment
- highlight proof starts:
  - `^Proof\b`

### 6.4 Symbol glossary extraction
- Parse inline math delimiters if available (may be imperfect in PDFs).
- Also detect common symbols using regex:
  - Greek letters, subscripts, `\mathbb{R}`, matrices, `||`, `\lambda`, etc. (approximate)
- For each symbol:
  - locate first occurrence block + bbox,
  - attempt meaning extraction from nearby text window:
    - patterns: “Let X be…”, “where X denotes…”, “X is defined as…”
- Confidence scoring:
  - high if explicit “denotes/where/defined as” pattern found
  - medium if inferred from repeated context
  - low otherwise (must label as “likely”)

### 6.5 Proof-skip / missing-explanation detector (NO equation completion)
Detect phrases indicating skipped reasoning:
- “clearly”, “obvious”, “straightforward”, “we omit”, “it follows”, “by standard arguments”
For each match:
- add a margin note:
  - explain what kind of step is being skipped (algebraic manipulation, known lemma, standard theorem)
  - provide a *conceptual expansion*:
    - “This step likely uses [tool] because [evidence], so the argument is: …”
  - if you can’t ground it, mark low confidence

### 6.6 Reference parsing + tracing
Goal: connect in-text citations → bibliography → external metadata.

#### MVP approach (if no GROBID)
- find “References” section by heading heuristic
- split bibliography entries by numbering patterns:
  - `[12] ...` or `12. ...` or `Smith, J. (2019) ...`
- find in-text citations:
  - numeric: `\[\d+(,\s*\d+)*\]`
  - author-year: `(Smith, 2019)` style (best-effort)
- link citations to bib entries; store anchors (page/bbox of in-text citation)

#### Enrichment (optional but recommended)
- For each bib entry:
  - call Crossref to resolve DOI (cache)
  - call Semantic Scholar to get paperId + abstract + citation count (cache)
- In annotation notes, only summarize what you retrieved.

#### Tracing idea origin
When you detect phrases:
- “as in [k]”, “following [k]”, “based on [k]”, “using the method of [k]”
Create a margin note that:
- states “Imported from [k]”
- includes 1–2 sentences summarizing what [k] contributes (based on abstract/metadata)
- includes evidence refs:
  - quote containing “as in [k]”
  - external abstract snippet if available

---

## 7) Commentary Generation (Grounded, Reliable)

Implement commentary as a deterministic function:

**Input:** anchor text + nearby context + (optional) retrieved reference snippets  
**Output:** `MarginNote` with confidence + evidence.

### 7.1 Prompts / generation style
Even if you use an LLM, enforce structured JSON outputs:
- `title`
- `body` (max 80–120 words per note for MVP)
- `key_points` (bullets)
- `evidence_used` (IDs)
- `confidence` 0–1
- `uncertainties` array

### 7.2 Safety against hallucination
- Hard rule: if `evidence_used` is empty → confidence must be <= 0.35 and note must include uncertainty language.
- Never claim “paper X proves Y” unless retrieved snippet supports it.

### 7.3 Explanation style requirements
- Explain in plain language first, then technical.
- For math blocks:
  - explain *what the equation is expressing* (relationship, objective, constraint)
  - identify what each symbol means (using glossary)
  - mention assumptions (domain, positivity, differentiability) if stated nearby
- Do NOT add new theorems or derivations.

---

## 8) Mind Map Generation

Build a concept graph:

### Nodes
- Sections
- Definitions
- Theorems/Lemmas
- Methods/Algorithms
- Key references (top N by mentions)

### Edges
- “defines” (section → definition)
- “proves” (proof → theorem)
- “uses” (theorem/method → definition)
- “cites” (section → reference)

Render with Graphviz to `mindmap.png`, then embed into PDF:
- either as a cover page (page 1)
- or as an appendix

---

## 9) Rendering Stage Details (PDF)

### 9.1 Create margin pages
For each source page:
- Create a new page width = original_width + margin_width
- Place original page on the left via `show_pdf_page`
- Add highlights on the left region (same coordinates)
- Place margin notes in the right margin with consistent layout:
  - vertical stacking
  - avoid overlaps
  - draw callout lines from note box to anchor bbox

### 9.2 Typography / readability
- Use consistent font and size in margin notes.
- Notes should be short; prefer multiple small notes over one giant block.
- Provide “legend” page: color meaning for highlights.

### 9.3 Output files
- Save `enhanced.pdf`
- Save `annotation_plan.json`
- Save `evidence_ledger.jsonl` (append one JSON record per note)

---

## 10) CLI and Config

Implement:

```bash
papercoach annotate INPUT.pdf --out enhanced.pdf \
  --workdir runs/foo \
  --level {light,medium,heavy} \
  --margin-width 180 \
  --max-notes-per-page 8 \
  --no-web  # disables external lookups
```

Behavior:
- `--no-web` must still produce usable commentary, but without external reference summaries.

---

## 11) Testing and Acceptance Criteria

### 11.1 Unit tests (must have)
- parsing of headings / theorems
- bibliography split + in-text citation detection
- plan generation produces valid schema
- renderer produces a PDF with:
  - same number of pages as input (or +1 if mindmap cover is enabled)
  - correct page sizes
  - at least one highlight + note on sample inputs

### 11.2 End-to-end acceptance
Given a known PDF:
- output PDF opens in standard viewers
- highlights align with the correct text
- notes are readable and do not cover the original page content
- at least:
  - 1 section TL;DR
  - 3 definition/theorem notes
  - 1 citation tracing note
  - glossary exists

---

## 12) Implementation Order (Recommended)

1. **Renderer skeleton**: margin pages + note placement + highlights (hardest UX piece)
2. **Text extraction + anchors**: reliable bounding boxes
3. **Heuristic structure**: sections + theorem blocks
4. **AnnotationPlan**: serialize + render
5. **Citations MVP**: parse refs section + in-text citation matching
6. **Citation tracing notes**
7. **Glossary**
8. **Mind map**
9. **(Optional) GROBID integration**
10. **(Optional) Web enrichment with caching**

---

## 13) Non-goals (for MVP)
- Solving/deriving missing equations
- Fully accurate LaTeX reconstruction
- Perfect figure/table understanding
- Multi-column reading order perfection for every layout (handle most common cases)

---

## 14) Deliverables Checklist

- [ ] `papercoach/` package with modules and Pydantic models
- [ ] CLI `papercoach annotate`
- [ ] `annotation_plan.json` generation
- [ ] `enhanced.pdf` rendering with margin layout
- [ ] symbol glossary page
- [ ] citation tracing notes
- [ ] mind map image + embedded page
- [ ] tests + sample run instructions in README

---

## 15) README must include

- Setup instructions
- Running the CLI
- What features work in MVP
- Known limitations
- How to enable/disable web lookups
- How to add your own API keys (if needed) and caching location

