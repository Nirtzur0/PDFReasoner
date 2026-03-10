from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from papercoach.config import ServiceConfig
from papercoach.web.app import create_app


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
        assert payload["annotated_pdf_url"] == f"/files/{job_id}/annotated.pdf"

        detail = client.get(job_url)
        assert detail.status_code == 200
        assert "Annotated PDF" in detail.text
        assert payload["filename"] in detail.text

        pdf_response = client.get(payload["annotated_pdf_url"])
        assert pdf_response.status_code == 200
        assert pdf_response.headers["content-type"].startswith("application/pdf")

        home = client.get("/")
        assert home.status_code == 200
        assert payload["filename"] in home.text


def test_web_app_surfaces_pipeline_failures(
    sample_pdf: Path,
    tmp_path: Path,
) -> None:
    app = create_app(
        services=ServiceConfig(base_url=None, api_key=None, model="gpt-5"),
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
        assert "PAPERCOACH_BASE_URL is required" in payload["error"]


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
