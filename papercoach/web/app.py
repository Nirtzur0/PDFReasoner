from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from papercoach.config import ServiceConfig
from papercoach.web.jobs import DiskJobStore, JobRecord, JobRunner, UploadValidationError, build_mock_jobs, is_pdf_upload

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
                "job": _job_view_model(job),
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
        return JSONResponse(job.to_api_payload())

    @app.get("/files/{job_id}/annotated.pdf")
    async def annotated_pdf(request: Request, job_id: str) -> FileResponse:
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
        return FileResponse(path, media_type="application/pdf", filename=f"{job_id}-annotated.pdf")

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
    response = TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "recent_jobs": [_job_view_model(job) for job in jobs],
            "error": error,
            "design_preview": design_preview,
        },
    )
    response.status_code = status_code
    return response


def _job_view_model(job: JobRecord) -> dict[str, object]:
    payload = job.to_api_payload()
    return {
        **payload,
        "detail_url": f"/jobs/{job.job_id}",
        "title_or_filename": job.title or job.filename,
        "status_label": job.status.replace("-", " ").title(),
    }
