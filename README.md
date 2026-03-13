# PaperCoach

PaperCoach is a phase-1 study tool for research papers. It reads a born-digital PDF, sends the paper text to a `ChatMock` backend using model `gpt-5`, aligns the model-selected highlight quotes back to PDF text coordinates, and writes native PDF highlights plus right-margin study notes into a new PDF.

## Setup

```bash
python3 -m pip install -e .
python3 -m pip install -e '.[dev]'
```

## Backend

PaperCoach expects an OpenAI-compatible endpoint. By default it talks to a local
ChatMock instance at `http://127.0.0.1:8000/v1` using a placeholder API key. If
`OPENAI_API_KEY` is set, PaperCoach switches to the OpenAI API by default instead.
Use `PAPERCOACH_*` to override either default explicitly.

### Local ChatMock default

No extra backend environment variables are required if ChatMock is already running
on its default local endpoint.

### OpenAI default

```bash
export OPENAI_API_KEY=your-key
export PAPERCOACH_MODEL=gpt-5
```

### Custom compatible backend

```bash
export PAPERCOACH_BASE_URL=http://127.0.0.1:8001/v1
export PAPERCOACH_API_KEY=dummy
export PAPERCOACH_MODEL=gpt-5
```

## Web app

The web UI serves on `http://127.0.0.1:8080` by default so it does not collide
with ChatMock's default `127.0.0.1:8000` listener.

The implementation is based on:

- [PyMuPDF text extraction recipes](https://pymupdf.readthedocs.io/en/latest/recipes-text.html)
- [PyMuPDF annotation recipes](https://pymupdf.readthedocs.io/en/latest/recipes-annotations.html)
- [OpenAI Chat Completions API reference](https://platform.openai.com/docs/api-reference/chat)
- [ChatMock README](https://github.com/RayBytes/ChatMock)

## CLI

```bash
papercoach highlight papers/example.pdf --out output/pdf/example-highlighted.pdf --workdir runs/example
papercoach highlight-plan papers/example.pdf --workdir runs/example
papercoach render-highlights papers/example.pdf runs/example/highlight_plan.json --out output/pdf/example-highlighted.pdf --workdir runs/example
```

### Phase-1 constraints

- Only born-digital PDFs are supported.
- The backend is strict: if the configured model is not available through ChatMock, the run fails.
- Highlights and concise study notes are implemented in this phase.

## Outputs

For each run:

- `runs/<paper-slug>/highlight_plan.json`
- `runs/<paper-slug>/run_manifest.json`
- `runs/<paper-slug>/trace.jsonl`
- `output/pdf/<paper-slug>-highlighted.pdf`
