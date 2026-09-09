from __future__ import annotations

from fastapi.testclient import TestClient
from medical_deid_core import ModelStore
from medical_deid_web.app import create_app

from medical_deid.sessions import SessionRepository


def test_setup_api_blocks_documents_until_models_are_verified(tmp_path) -> None:
    with TestClient(create_app(ModelStore(tmp_path))) as client:
        runtime = client.get("/api/runtime").json()
        assert runtime["mode"] == "setup"
        assert runtime["processingEnabled"] is False

        models = client.get("/api/models").json()
        assert models["profiles"][0]["id"] == "qwen3-4b-q4-k-m"
        assert models["runtime"]["backend"] in {"metal", "cuda", "cpu", "unsupported"}

        unknown = client.post("/api/models/not-a-model/install")
        assert unknown.status_code == 409
        assert unknown.json()["detail"] == "unknown_model_profile:not-a-model"

        response = client.post(
            "/api/documents",
            files={"document": ("scan.pdf", b"not-a-pdf", "application/pdf")},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "models_are_not_ready"


def test_web_api_lists_sessions_recovered_after_relaunch(tmp_path) -> None:
    store = ModelStore(tmp_path)
    repository = SessionRepository(store.root / "sessions.sqlite3", store.root / "sessions")
    repository.initialize()
    recovered = repository.create("recovered.pdf", ".pdf", b"%PDF-source")

    with TestClient(create_app(store)) as client:
        response = client.get("/api/documents")

    assert response.status_code == 200
    assert [session["id"] for session in response.json()] == [recovered.id]
