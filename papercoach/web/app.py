from __future__ import annotations

from contextlib import asynccontextmanager
from email.utils import formatdate
from mimetypes import guess_type
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from papercoach.config import ServiceConfig
from papercoach.web.jobs import DiskJobStore, JobProgress, JobRecord, JobRunner, UploadValidationError, build_mock_jobs, is_pdf_upload

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))


def create_app(
    services: ServiceConfig | None = None,
    jobs_root: Path | None = None,
) -> FastAPI:
    active_services = services or ServiceConfig()
    active_jobs_root = jobs_root or Path("runs/web")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = DiskJobStore(active_jobs_root)
        runner = JobRunner(active_services, store)
        app.state.store = store
        app.state.runner = runner
        yield
        runner.shutdown()

    app = FastAPI(title="PaperCoach", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_ROOT / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return _render_home(request)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(PACKAGE_ROOT / "static" / "favicon.svg", media_type="image/svg+xml")

    @app.get("/design-preview", response_class=HTMLResponse)
    async def design_preview(request: Request) -> HTMLResponse:
        return _render_home(request, recent_jobs=build_mock_jobs(), design_preview=True)

    @app.post("/jobs")
    async def create_job(request: Request, file: UploadFile = File(...)):
        if not is_pdf_upload(file.filename, file.content_type):
            return _render_home(
                request,
                error="Please upload a PDF file.",
                status_code=400,
            )

        store: DiskJobStore = request.app.state.store
        job = store.create_job(file.filename or "paper.pdf")
        try:
            await store.save_upload(job.job_id, file)
        except UploadValidationError as exc:
            store.delete_job(job.job_id)
            return _render_home(request, error=str(exc), status_code=400)

        request.app.state.runner.submit(job.job_id)
        return RedirectResponse(url=f"/jobs/{job.job_id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: str) -> HTMLResponse:
        store: DiskJobStore = request.app.state.store
        try:
            job = store.read(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return TEMPLATES.TemplateResponse(
            request,
            "job.html",
            {
                "job": _job_view_model(job, progress=store.progress(job_id)),
                "poll_url": f"/api/jobs/{job_id}",
            },
        )

    @app.get("/api/jobs/{job_id}")
    async def job_status(request: Request, job_id: str) -> JSONResponse:
        store: DiskJobStore = request.app.state.store
        try:
            job = store.read(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(_job_api_payload(job, progress=store.progress(job_id)))

    @app.get("/api/jobs/{job_id}/annotated.pdf")
    async def annotated_pdf_api(request: Request, job_id: str) -> Response:
        return _annotated_pdf_response(request, job_id)

    @app.get("/files/{job_id}/annotated.pdf")
    async def annotated_pdf(request: Request, job_id: str) -> Response:
        return _annotated_pdf_response(request, job_id)

    def _annotated_pdf_response(request: Request, job_id: str) -> Response:
        store: DiskJobStore = request.app.state.store
        try:
            job = store.read(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if job.status != "succeeded":
            raise HTTPException(status_code=409, detail="Annotated PDF is not ready yet.")
        path = store.annotated_path(job_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Annotated PDF is missing.")
        return _range_aware_pdf_response(
            request,
            path,
            filename=f"{job_id}-annotated.pdf",
        )

    return app


def _render_home(
    request: Request,
    *,
    recent_jobs: list[JobRecord] | None = None,
    error: str | None = None,
    status_code: int = 200,
    design_preview: bool = False,
) -> HTMLResponse:
    store = getattr(request.app.state, "store", None)
    jobs = recent_jobs if recent_jobs is not None else (store.list_jobs()[:8] if store is not None else [])
    job_view_models = [
        _job_view_model(job, progress=store.progress(job.job_id) if store is not None else None)
        for job in jobs
    ]
    response = TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "recent_jobs": job_view_models,
            "error": error,
            "design_preview": design_preview,
        },
    )
    response.status_code = status_code
    return response


def _job_view_model(job: JobRecord, progress: JobProgress | None = None) -> dict[str, object]:
    payload = _job_api_payload(job, progress=progress)
    return {
        **payload,
        "detail_url": f"/jobs/{job.job_id}",
        "title_or_filename": job.title or job.filename,
        "status_label": job.status.replace("-", " ").title(),
    }


def _job_api_payload(job: JobRecord, progress: JobProgress | None = None) -> dict[str, object]:
    return job.to_api_payload(
        progress=progress,
        annotated_pdf_url=_annotated_pdf_url(job.job_id) if job.status == "succeeded" else None,
        viewer_url=_annotated_viewer_url(job.job_id) if job.status == "succeeded" else None,
    )


def _annotated_pdf_url(job_id: str) -> str:
    return f"/api/jobs/{job_id}/annotated.pdf"


def _annotated_viewer_url(job_id: str) -> str:
    file_param = quote(_annotated_pdf_url(job_id), safe="")
    return f"/static/pdfjs/web/viewer.html?file={file_param}#zoom=page-width"


def _range_aware_pdf_response(request: Request, path: Path, *, filename: str) -> Response:
    file_size = path.stat().st_size
    media_type = guess_type(str(path))[0] or "application/pdf"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{filename}"',
        "Last-Modified": formatdate(os.path.getmtime(path), usegmt=True),
    }

    range_header = request.headers.get("range")
    if not range_header:
        headers["Content-Length"] = str(file_size)
        return Response(content=path.read_bytes(), media_type=media_type, headers=headers)

    start, end = _parse_range_header(range_header, file_size)
    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            detail="Requested Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    with path.open("rb") as handle:
        handle.seek(start)
        content = handle.read(end - start + 1)

    headers["Content-Length"] = str(len(content))
    headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    return Response(content=content, status_code=206, media_type=media_type, headers=headers)


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    unit, _, raw_range = range_header.partition("=")
    if unit.strip().lower() != "bytes" or not raw_range:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")

    start_raw, _, end_raw = raw_range.partition(",")[0].partition("-")
    if not start_raw and not end_raw:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")

    try:
        if not start_raw:
            suffix_length = int(end_raw)
            if suffix_length <= 0:
                raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
            return start, end

        start = int(start_raw)
        end = int(end_raw) if end_raw else file_size - 1
        return start, min(end, file_size - 1)
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Requested Range Not Satisfiable") from exc
