# PaperCoach

PaperCoach reads an academic born-digital PDF and produces an enhanced PDF with highlights, right-margin notes, citation tracing, and a mind map page.

## Setup

```bash
python3 -m pip install -e .
python3 -m pip install -e '.[dev]'
```

Required local services:

- GROBID at `http://localhost:8070` (override with `PAPERCOACH_GROBID_URL`)
- Ollama at `http://localhost:11434` with model `llama3.1:8b-instruct-q8_0` (override with `PAPERCOACH_OLLAMA_URL`, `PAPERCOACH_OLLAMA_MODEL`)

Optional system tool for visual QA:

- `pdftoppm` (Poppler)

## CLI

```bash
papercoach annotate INPUT.pdf --out enhanced.pdf --workdir runs/paper1 --level medium
papercoach plan INPUT.pdf --workdir runs/paper1 --out runs/paper1/annotation_plan.json
papercoach render INPUT.pdf runs/paper1/annotation_plan.json --out enhanced.pdf --workdir runs/paper1
```

### Flags

- `--level {light,medium,heavy}` controls top-N citation enrichment (5/10/20)
- `--no-web` disables Crossref and Semantic Scholar lookups
- `--margin-width` controls right note column width
- `--max-notes-per-page` caps notes with overflow page
- `--mindmap-position {cover,appendix}` controls where mind map page is inserted

## Output Artifacts

Written under `--workdir`:

- `annotation_plan.json`
- `evidence_ledger.jsonl`
- `mindmap.png`
- `run.log`
- `report.html`

Main output:

- `enhanced.pdf`

## MVP Features

- Two-stage pipeline: analyze then render
- Page-coordinate anchored highlights and notes
- Section/theorem/proof/equation heuristics
- Citation parsing, linking, and optional web enrichment
- Tracing notes for imported ideas (`as in`, `following`, etc.)
- Mind map PNG generation + embedding
- Low-confidence HTML report

## Reliability and Safety Rules

- Notes without evidence must have confidence <= 0.35.
- Unsupported generated claims fail the run.
- Commentary must map to known evidence IDs.
- No equation/proof completion.

## Known Limitations

- Born-digital PDFs only (no OCR pipeline)
- Heuristic structure detection for layout-heavy papers can be imperfect
- Multi-column reading order is best-effort
- Figure/table semantic understanding is limited

## Tests

```bash
pytest
```
