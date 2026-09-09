from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from medical_deid.app import create_app
from medical_deid.processing import ProcessingError
from medical_deid.settings import Settings


class SuccessfulProcessor:
    def __init__(self) -> None:
        self.called = Event()

    def process(self, source_path: Path, result_path: Path) -> None:
        result_path.write_bytes(b"%PDF-result")
        self.called.set()


class FailingProcessor:
    def process(self, source_path: Path, result_path: Path) -> None:
        raise ProcessingError("OCR result could not be validated.")


def test_supported_upload_creates_persistent_queued_session(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, processing_enabled=False)

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/sessions",
            files={"document": ("sample.jpg", b"jpeg bytes", "image/jpeg")},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["source_filename"] == "sample.jpg"
    assert payload["status"] == "queued"
    assert payload["stage"] == "queued"
    assert (tmp_path / "sessions.sqlite3").is_file()
    assert (tmp_path / "sessions" / payload["id"] / "source.jpg").read_bytes() == b"jpeg bytes"


def test_recent_sessions_survive_application_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, processing_enabled=False)

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/sessions",
            files={"document": ("sample.pdf", b"pdf bytes", "application/pdf")},
        ).json()

    with TestClient(create_app(settings)) as restarted_client:
        response = restarted_client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == [created]


def test_background_processing_persists_result_and_feedback(tmp_path: Path) -> None:
    processor = SuccessfulProcessor()
    settings = Settings(data_dir=tmp_path)

    with TestClient(create_app(settings, processor=processor)) as client:
        created = client.post(
            "/api/sessions",
            files={"document": ("sample.pdf", b"%PDF-source", "application/pdf")},
        ).json()
        assert processor.called.wait(timeout=2)

        detail = client.get(f"/api/sessions/{created['id']}")
        result = client.get(f"/api/sessions/{created['id']}/result")
        feedback = client.post(
            f"/api/sessions/{created['id']}/feedback",
            json={"text": "В таблице пропущена строка."},
        )

    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["result_available"] is True
    assert result.status_code == 200
    assert result.content == b"%PDF-result"
    assert feedback.status_code == 201
    assert feedback.json()["saved"] is True

    with TestClient(create_app(Settings(data_dir=tmp_path, processing_enabled=False))) as client:
        restarted_detail = client.get(f"/api/sessions/{created['id']}")

    assert restarted_detail.json()["feedback_submitted"] is True


def test_failed_processing_does_not_expose_result(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    with TestClient(create_app(settings, processor=FailingProcessor())) as client:
        created = client.post(
            "/api/sessions",
            files={"document": ("sample.png", b"png", "image/png")},
        ).json()

        for _ in range(100):
            detail = client.get(f"/api/sessions/{created['id']}")
            if detail.json()["status"] == "failed":
                break

        result = client.get(f"/api/sessions/{created['id']}/result")

    assert detail.json()["status"] == "failed"
    assert detail.json()["error_message"] == "OCR result could not be validated."
    assert result.status_code == 409


def test_delete_session_removes_artifacts_and_metadata(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, processing_enabled=False)

    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/sessions",
            files={"document": ("sample.jpg", b"jpeg", "image/jpeg")},
        ).json()
        session_dir = tmp_path / "sessions" / created["id"]

        response = client.delete(f"/api/sessions/{created['id']}")

        assert response.status_code == 204
        assert not session_dir.exists()
        assert client.get(f"/api/sessions/{created['id']}").status_code == 404
