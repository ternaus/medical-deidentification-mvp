from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from medical_deid_core import create_review_session
from pydantic import BaseModel, Field


class Feedback(BaseModel):
    rating: str = Field(pattern="^(correct|incorrect)$")
    note: str | None = Field(default=None, max_length=2000)


def create_app() -> FastAPI:
    app = FastAPI(title="Medical Deid Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    sessions: dict[str, dict[str, object]] = {}

    @app.get("/api/runtime")
    def runtime() -> dict[str, object]:
        return {
            "mode": "review",
            "processingEnabled": False,
            "appVersion": "0.1.0",
            "coreVersion": "0.1.0",
            "ocrVersion": "not-loaded",
            "modelVersion": None,
            "modelStatus": "not_installed",
            "supportedFormats": ["pdf", "jpg", "jpeg", "png"],
        }

    @app.post("/api/review/session")
    def review_session() -> dict[str, object]:
        session_id = str(uuid.uuid4())
        session = create_review_session(session_id)
        sessions[session_id] = session
        return session

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, object]:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        return session

    @app.post("/api/sessions/{session_id}/feedback")
    def add_feedback(session_id: str, feedback: Feedback) -> dict[str, object]:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        session["feedback"] = feedback.model_dump(exclude_none=True)
        return {"accepted": True, "rating": feedback.rating}

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, bool]:
        return {"deleted": sessions.pop(session_id, None) is not None}

    return app


app = create_app()
