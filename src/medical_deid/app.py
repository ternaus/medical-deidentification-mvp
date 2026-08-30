"""FastAPI application factory for the local web application."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medical_deid.processing import DocumentProcessor, ProcessingCoordinator
from medical_deid.sessions import SessionNotFoundError, SessionRecord, SessionRepository
from medical_deid.settings import Settings

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}


class SessionResponse(BaseModel):
    """Public processing-session state without document text."""

    id: str
    source_filename: str
    status: str
    stage: str
    created_at: str
    updated_at: str
    error_message: str | None
    result_available: bool
    feedback_submitted: bool


class FeedbackRequest(BaseModel):
    """The intentionally large text area submitted by a reviewer."""

    text: str = Field(min_length=1, max_length=10_000)


class FeedbackResponse(BaseModel):
    """Persistence receipt shown only after the write completed."""

    saved: bool


class DisabledProcessor(DocumentProcessor):
    """Keep API-only tests deterministic when processing is intentionally disabled."""

    def process(self, source_path: Path, result_path: Path) -> None:
        raise RuntimeError("Processing is disabled.")


def create_app(
    settings: Settings | None = None,
    *,
    processor: DocumentProcessor | None = None,
) -> FastAPI:
    """Build an application with explicit local filesystem dependencies."""
    resolved_settings = settings or Settings()
    repository = SessionRepository(
        resolved_settings.database_path,
        resolved_settings.sessions_dir,
    )
    if processor is not None:
        selected_processor = processor
    elif resolved_settings.processing_enabled:
        from medical_deid.pipeline import LocalMedicalPipeline

        selected_processor = LocalMedicalPipeline()
    else:
        selected_processor = DisabledProcessor()
    coordinator = ProcessingCoordinator(repository, selected_processor)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        if resolved_settings.processing_enabled:
            coordinator.start()
        yield
        if resolved_settings.processing_enabled:
            coordinator.stop()

    app = FastAPI(title="Medical document de-identification", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.post(
        "/api/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_session(
        document: Annotated[UploadFile, File(...)],
    ) -> SessionRecord:
        filename = Path(document.filename or "").name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Supported formats: JPG, JPEG, PNG, PDF.",
            )

        content = await document.read(resolved_settings.max_upload_bytes + 1)
        if len(content) > resolved_settings.max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="The document exceeds the upload limit.",
            )
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The uploaded document is empty.",
            )

        record = repository.create(filename, suffix, content)
        if resolved_settings.processing_enabled:
            coordinator.submit(record.id)
        return record

    @app.get("/api/sessions", response_model=list[SessionResponse])
    def list_sessions() -> list[SessionRecord]:
        return repository.list_recent()

    @app.get("/api/sessions/{session_id}", response_model=SessionResponse)
    def get_session(session_id: str) -> SessionRecord:
        return _get_session_or_404(repository, session_id)

    @app.get("/api/sessions/{session_id}/result")
    def download_result(session_id: str) -> FileResponse:
        record = _get_session_or_404(repository, session_id)
        if record.status != "completed" or not record.result_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A safe anonymized PDF is not available for this session.",
            )
        return FileResponse(
            repository.result_path(session_id),
            media_type="application/pdf",
            filename=f"anonymized-{Path(record.source_filename).stem}.pdf",
        )

    @app.post(
        "/api/sessions/{session_id}/feedback",
        response_model=FeedbackResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def save_feedback(session_id: str, feedback: FeedbackRequest) -> FeedbackResponse:
        cleaned_text = feedback.text.strip()
        if not cleaned_text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Feedback cannot be empty.",
            )
        try:
            repository.save_feedback(session_id, cleaned_text)
        except SessionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.") from error
        return FeedbackResponse(saved=True)

    @app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_session(session_id: str) -> Response:
        try:
            repository.delete(session_id)
        except SessionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    frontend_dir = Path(__file__).parents[2] / "frontend" / "out"
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


def _get_session_or_404(repository: SessionRepository, session_id: str) -> SessionRecord:
    try:
        return repository.get(session_id)
    except SessionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.") from error


app = create_app()
