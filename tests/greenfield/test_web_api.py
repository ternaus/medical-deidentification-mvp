from __future__ import annotations

from fastapi.testclient import TestClient
from medical_deid_web.app import create_app


def test_review_api_creates_and_deletes_synthetic_session() -> None:
    client = TestClient(create_app())
    assert client.get("/api/runtime").json()["processingEnabled"] is False
    session = client.post("/api/review/session").json()
    assert session["sourceLabel"] == "synthetic-review.pdf"
    assert client.get(f"/api/sessions/{session['id']}").status_code == 200
    assert client.post(f"/api/sessions/{session['id']}/feedback", json={"rating": "correct"}).status_code == 200
    assert client.delete(f"/api/sessions/{session['id']}").json() == {"deleted": True}
