from __future__ import annotations

from pathlib import Path

from papercoach.web.jobs import DiskJobStore, JobCounts, JobRecord, is_pdf_upload


def test_job_record_api_payload_sets_pdf_url_only_for_completed_runs() -> None:
    queued = JobRecord(
        job_id="job-1",
        filename="paper.pdf",
        status="queued",
        created_at="2026-03-10T10:00:00+00:00",
        updated_at="2026-03-10T10:00:00+00:00",
    )
    succeeded = queued.model_copy(update={"status": "succeeded"})

    assert queued.to_api_payload()["annotated_pdf_url"] is None
    assert succeeded.to_api_payload()["annotated_pdf_url"] == "/files/job-1/annotated.pdf"


def test_disk_job_store_roundtrips_and_updates_job_state(tmp_path: Path) -> None:
    store = DiskJobStore(tmp_path / "jobs")

    created = store.create_job("paper.pdf")
    assert store.job_file(created.job_id).exists()
    assert created.status == "queued"

    updated = store.update(
        created.job_id,
        status="succeeded",
        title="A Study",
        counts=JobCounts(highlights=3, notes=2, equations=1, equation_notes=1),
    )

    reloaded = store.read(created.job_id)
    assert updated == reloaded
    assert reloaded.title == "A Study"
    assert reloaded.counts.highlights == 3


def test_is_pdf_upload_accepts_pdf_extension_or_content_type() -> None:
    assert is_pdf_upload("paper.pdf", "application/octet-stream")
    assert is_pdf_upload("paper.bin", "application/pdf")
    assert not is_pdf_upload("notes.txt", "text/plain")
