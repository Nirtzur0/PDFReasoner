from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from typing import Literal
import uuid

from pydantic import BaseModel, Field

from papercoach.config import RunConfig, ServiceConfig
from papercoach.pipeline import PaperCoachPipeline

JobStatus = Literal["queued", "running", "succeeded", "failed"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobCounts(BaseModel):
    highlights: int = 0
    notes: int = 0
    equations: int = 0
    equation_notes: int = 0


class JobRecord(BaseModel):
    job_id: str
    filename: str
    title: str | None = None
    status: JobStatus
    error: str | None = None
    created_at: str
    updated_at: str
    counts: JobCounts = Field(default_factory=JobCounts)

    def to_api_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "job_id": self.job_id,
            "status": self.status,
            "filename": self.filename,
            "title": self.title,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "counts": self.counts.model_dump(),
            "annotated_pdf_url": None,
        }
        if self.status == "succeeded":
            payload["annotated_pdf_url"] = f"/files/{self.job_id}/annotated.pdf"
        return payload


class UploadValidationError(ValueError):
    """Raised when an uploaded file cannot be accepted."""


class DiskJobStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def create_job(self, filename: str) -> JobRecord:
        job_id = uuid.uuid4().hex[:12]
        timestamp = utc_now_iso()
        record = JobRecord(
            job_id=job_id,
            filename=filename,
            status="queued",
            created_at=timestamp,
            updated_at=timestamp,
        )
        job_dir = self.job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        self.write(record)
        return record

    def delete_job(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def list_jobs(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for job_file in self._root.glob("*/job.json"):
            jobs.append(JobRecord.model_validate_json(job_file.read_text(encoding="utf-8")))
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs

    def read(self, job_id: str) -> JobRecord:
        path = self.job_file(job_id)
        if not path.exists():
            raise FileNotFoundError(f"Unknown job: {job_id}")
        return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, record: JobRecord) -> JobRecord:
        target = self.job_file(record.job_id)
        temp_path = target.with_name(f"{target.stem}.tmp")
        temp_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(target)
        return record

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        title: str | None = None,
        error: str | None = None,
        counts: JobCounts | None = None,
    ) -> JobRecord:
        record = self.read(job_id)
        changed = record.model_copy(deep=True)
        if status is not None:
            changed.status = status
        if title is not None:
            changed.title = title
        changed.error = error
        if counts is not None:
            changed.counts = counts
        changed.updated_at = utc_now_iso()
        return self.write(changed)

    def job_dir(self, job_id: str) -> Path:
        return self._root / job_id

    def job_file(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def input_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "input.pdf"

    def annotated_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "annotated.pdf"

    async def save_upload(self, job_id: str, upload) -> None:
        target = self.input_path(job_id)
        total_bytes = 0
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                handle.write(chunk)
        await upload.close()
        if total_bytes == 0:
            raise UploadValidationError("Uploaded PDF is empty.")


class JobRunner:
    def __init__(self, services: ServiceConfig, store: DiskJobStore, max_workers: int = 2) -> None:
        self._services = services
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="papercoach-web")

    def submit(self, job_id: str) -> Future[None]:
        return self._executor.submit(self._run, job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, job_id: str) -> None:
        self._store.update(job_id, status="running", error=None)
        try:
            run = RunConfig(
                input_pdf=self._store.input_path(job_id),
                out_pdf=self._store.annotated_path(job_id),
                workdir=self._store.job_dir(job_id),
            )
            plan = PaperCoachPipeline(self._services).highlight(run)
            counts = JobCounts(
                highlights=sum(len(page.highlights) for page in plan.pages),
                notes=sum(len(page.notes) for page in plan.pages),
                equations=sum(len(page.equations) for page in plan.pages),
                equation_notes=sum(len(page.equation_notes) for page in plan.pages),
            )
            self._store.update(job_id, status="succeeded", title=plan.meta.title, counts=counts, error=None)
        except Exception as exc:
            self._store.update(job_id, status="failed", error=str(exc))


def is_pdf_upload(filename: str | None, content_type: str | None) -> bool:
    normalized_name = (filename or "").strip().lower()
    normalized_type = (content_type or "").strip().lower()
    return normalized_name.endswith(".pdf") or normalized_type == "application/pdf"


def build_mock_jobs() -> list[JobRecord]:
    now = utc_now_iso()
    return [
        JobRecord(
            job_id="preview-success",
            filename="Reliable Highlighting.pdf",
            title="A Small Study of Reliable Highlighting",
            status="succeeded",
            created_at=now,
            updated_at=now,
            counts=JobCounts(highlights=7, notes=5, equations=1, equation_notes=1),
        ),
        JobRecord(
            job_id="preview-running",
            filename="Explaining Predictions.pdf",
            title=None,
            status="running",
            created_at=now,
            updated_at=now,
            counts=JobCounts(),
        ),
    ]
