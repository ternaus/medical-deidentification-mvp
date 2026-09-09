from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from medical_deid_core import ModelStore, ModelStoreError
from pydantic import BaseModel

from medical_deid.processing import ProcessingCoordinator
from medical_deid.runtime_pipeline import ModelStorePipeline
from medical_deid.sessions import SessionRecord, SessionRepository

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class DocumentSession(BaseModel):
    id: str
    sourceFilename: str
    status: str
    stage: str
    errorMessage: str | None
    resultAvailable: bool


def _session_response(record: SessionRecord) -> DocumentSession:
    return DocumentSession(
        id=record.id,
        sourceFilename=record.source_filename,
        status=record.status,
        stage=record.stage,
        errorMessage=record.error_message,
        resultAvailable=record.result_available,
    )


def create_app(store: ModelStore | None = None) -> FastAPI:
    models = store or ModelStore()
    repository = SessionRepository(models.root / "sessions.sqlite3", models.root / "sessions")
    coordinator = ProcessingCoordinator(repository, ModelStorePipeline(models))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        coordinator.start()
        yield
        coordinator.stop()

    app = FastAPI(title="Medical Deid Web API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/runtime")
    def runtime() -> dict[str, object]:
        inventory = models.snapshot()
        selected_profile = inventory.get("selectedProfile")
        preflight = inventory.get("preflight")
        ready = isinstance(preflight, dict) and preflight.get("ok") is True
        profiles = inventory.get("profiles")
        selected = (
            next((profile for profile in profiles if profile.get("id") == selected_profile), None)
            if isinstance(profiles, list)
            else None
        )
        return {
            "mode": "local" if ready else "setup",
            "processingEnabled": ready,
            "appVersion": "0.1.0",
            "coreVersion": "0.1.0",
            "ocrVersion": "surya-ocr-2" if inventory.get("ocrReady") else "not-installed",
            "modelVersion": selected.get("label") if isinstance(selected, dict) else None,
            "modelStatus": "ready" if ready else "not_installed",
            "supportedFormats": ["pdf", "jpg", "jpeg", "png"],
            "accelerator": inventory.get("runtime"),
        }

    @app.get("/api/models")
    def model_inventory() -> dict[str, object]:
        return models.snapshot()

    @app.post("/api/models/{profile_id}/install", status_code=status.HTTP_202_ACCEPTED)
    def install_model(profile_id: str) -> dict[str, object]:
        try:
            return models.start_install(profile_id)
        except ModelStoreError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post("/api/models/{profile_id}/select")
    def select_model(profile_id: str) -> dict[str, object]:
        try:
            return models.select(profile_id)
        except ModelStoreError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @app.post(
        "/api/documents", response_model=DocumentSession, status_code=status.HTTP_202_ACCEPTED
    )
    async def create_document(document: Annotated[UploadFile, File(...)]) -> DocumentSession:
        inventory = models.snapshot()
        preflight = inventory.get("preflight")
        if not isinstance(preflight, dict) or preflight.get("ok") is not True:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="models_are_not_ready")
        filename = Path(document.filename or "").name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Supported formats: JPG, JPEG, PNG, PDF.",
            )
        content = await document.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="document_too_large"
            )
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty_document"
            )
        record = repository.create(filename, suffix, content)
        coordinator.submit(record.id)
        return _session_response(record)

    @app.get("/api/documents/{session_id}", response_model=DocumentSession)
    def document_status(session_id: str) -> DocumentSession:
        try:
            return _session_response(repository.get(session_id))
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found"
            ) from error

    @app.get("/api/documents/{session_id}/result")
    def download_result(session_id: str) -> FileResponse:
        try:
            record = repository.get(session_id)
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found"
            ) from error
        if record.status != "completed" or not record.result_available:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="result_not_ready")
        return FileResponse(
            repository.result_path(session_id),
            media_type="application/pdf",
            filename=f"anonymized-{Path(record.source_filename).stem}.pdf",
        )

    return app


app = create_app()
