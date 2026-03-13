from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from papercoach.config import ServiceConfig
from papercoach.web.app import create_app
from papercoach.web.jobs import JobRecord


def _wait_for_terminal_status(client: TestClient, job_id: str) -> dict:
    for _ in range(120):
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("Job did not reach a terminal state")


def test_web_app_processes_pdf_and_serves_annotation(
    sample_pdf: Path,
    tmp_path: Path,
    fake_chatmock_base_url: str,
) -> None:
    app = create_app(
        services=ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5"),
        jobs_root=tmp_path / "web-runs",
    )

    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Browse files" in home.text
        assert "No file selected yet" in home.text

        response = client.post(
            "/jobs",
            files={"file": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        job_url = response.headers["location"]
        job_id = job_url.rsplit("/", 1)[-1]

        payload = _wait_for_terminal_status(client, job_id)
        assert payload["status"] == "succeeded"
        assert payload["counts"]["highlights"] >= 1
        assert payload["annotated_pdf_url"] == f"/api/jobs/{job_id}/annotated.pdf"
        assert payload["viewer_url"] == (
            f"/static/pdfjs/web/viewer.html?file=%2Fapi%2Fjobs%2F{job_id}%2Fannotated.pdf#zoom=page-width"
        )

        detail = client.get(job_url)
        assert detail.status_code == 200
        assert "Annotated PDF" in detail.text
        assert payload["filename"] in detail.text
        assert payload["viewer_url"] in detail.text
        assert payload["annotated_pdf_url"] in detail.text

        pdf_response = client.get(payload["annotated_pdf_url"])
        assert pdf_response.status_code == 200
        assert pdf_response.headers["content-type"].startswith("application/pdf")
        assert pdf_response.headers["content-disposition"] == f'inline; filename="{job_id}-annotated.pdf"'
        assert pdf_response.content.startswith(b"%PDF")

        alias_response = client.get(f"/files/{job_id}/annotated.pdf")
        assert alias_response.status_code == 200
        assert alias_response.headers["content-type"].startswith("application/pdf")
        assert alias_response.content.startswith(b"%PDF")

        range_response = client.get(
            payload["annotated_pdf_url"],
            headers={"Range": "bytes=0-99"},
        )
        assert range_response.status_code == 206
        assert range_response.headers["accept-ranges"] == "bytes"
        assert range_response.headers["content-range"].startswith("bytes 0-99/")
        assert range_response.content.startswith(b"%PDF")

        home = client.get("/")
        assert home.status_code == 200
        assert payload["filename"] in home.text


def test_web_app_surfaces_pipeline_failures(
    sample_pdf: Path,
    tmp_path: Path,
) -> None:
    app = create_app(
        services=ServiceConfig(base_url="http://127.0.0.1:9/v1", api_key="dummy", model="gpt-5"),
        jobs_root=tmp_path / "web-runs",
    )

    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            files={"file": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
            follow_redirects=False,
        )
        assert response.status_code == 303
        job_id = response.headers["location"].rsplit("/", 1)[-1]

        payload = _wait_for_terminal_status(client, job_id)
        assert payload["status"] == "failed"
        assert "Could not reach ChatMock" in payload["error"]
        pdf_response = client.get(f"/api/jobs/{job_id}/annotated.pdf")
        assert pdf_response.status_code == 409


def test_web_app_rejects_invalid_upload_and_preserves_recent_runs(
    sample_pdf: Path,
    tmp_path: Path,
    fake_chatmock_base_url: str,
) -> None:
    jobs_root = tmp_path / "web-runs"
    app = create_app(
        services=ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5"),
        jobs_root=jobs_root,
    )

    with TestClient(app) as client:
        invalid = client.post(
            "/jobs",
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )
        assert invalid.status_code == 400
        assert "Please upload a PDF file." in invalid.text

        response = client.post(
            "/jobs",
            files={"file": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
            follow_redirects=False,
        )
        job_id = response.headers["location"].rsplit("/", 1)[-1]
        payload = _wait_for_terminal_status(client, job_id)
        assert payload["status"] == "succeeded"

    second_app = create_app(
        services=ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5"),
        jobs_root=jobs_root,
    )
    with TestClient(second_app) as second_client:
        home = second_client.get("/")
        assert home.status_code == 200
        assert "sample.pdf" in home.text


def test_web_app_reports_live_progress_from_trace(tmp_path: Path) -> None:
    jobs_root = tmp_path / "web-runs"
    job_dir = jobs_root / "job-running"
    job_dir.mkdir(parents=True)
    record = JobRecord(
        job_id="job-running",
        filename="sample.pdf",
        status="running",
        created_at="2026-03-12T14:00:00+00:00",
        updated_at="2026-03-12T14:00:00+00:00",
    )
    (job_dir / "job.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (job_dir / "trace.jsonl").write_text(
        "\n".join(
            [
                '{"type":"request","prompt_name":"key_idea_extraction"}',
                '{"type":"response","prompt_name":"key_idea_extraction"}',
                '{"type":"request","prompt_name":"equation_selection"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = create_app(
        services=ServiceConfig(base_url="http://127.0.0.1:9/v1", api_key="dummy", model="gpt-5"),
        jobs_root=jobs_root,
    )

    with TestClient(app) as client:
        payload = client.get("/api/jobs/job-running").json()
        assert payload["status"] == "running"
        assert payload["progress"]["started_steps"] == 2
        assert payload["progress"]["completed_steps"] == 1
        assert payload["progress"]["current_prompt"] == "equation_selection"
        assert payload["progress"]["stage_title"] == "Choosing equations"
        assert payload["progress"]["stage_detail"] == "deciding which equations should receive annotations."
        assert payload["progress"]["stage_index"] == 5
        assert payload["progress"]["total_stages"] == 7
        assert payload["progress"]["progress_percent"] == 65
        assert payload["progress"]["message"] == (
            "Choosing equations: deciding which equations should receive annotations. "
            "Step 2 is in progress and 1 model steps are complete."
        )

        detail = client.get("/jobs/job-running")
        assert detail.status_code == 200
        assert "Stage 5 of 7" in detail.text
        assert "65%" in detail.text
        assert "Choosing equations" in detail.text
        assert (
            "Choosing equations: deciding which equations should receive annotations. "
            "Step 2 is in progress and 1 model steps are complete."
        ) in detail.text
        assert "Completed model steps" in detail.text
        assert "Latest active step" in detail.text
        assert "/static/pdfjs/web/viewer.html" not in detail.text

        home = client.get("/")
        assert home.status_code == 200
        assert "Choosing equations: deciding which equations should receive annotations." not in home.text
