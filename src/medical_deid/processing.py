"""Single-worker local processing coordination."""

from pathlib import Path
from queue import Queue
from threading import Event, Thread

from medical_deid.sessions import SessionNotFoundError, SessionRepository


class ProcessingError(RuntimeError):
    """A safe, user-visible failure that must not produce an export."""


class DocumentProcessor:
    """Base interface for the OCR, extraction, and reconstruction pipeline."""

    def process(self, source_path: Path, result_path: Path) -> None:
        """Create one validated anonymized PDF or raise ProcessingError."""
        raise NotImplementedError


class ProcessingCoordinator:
    """Run one document at a time and recover unfinished local sessions."""

    def __init__(self, repository: SessionRepository, processor: DocumentProcessor) -> None:
        self._repository = repository
        self._processor = processor
        self._queue: Queue[str | None] = Queue()
        self._stopped = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start the sole worker and resume sessions interrupted by an app restart."""
        self._thread = Thread(target=self._run, name="medical-deid-worker", daemon=True)
        self._thread.start()
        for session_id in self._repository.list_unfinished():
            self.submit(session_id)

    def stop(self) -> None:
        """Stop accepting work when the FastAPI application shuts down."""
        self._stopped.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=1)

    def submit(self, session_id: str) -> None:
        """Add exactly one session to the sequential local queue."""
        if not self._stopped.is_set():
            self._queue.put(session_id)

    def _run(self) -> None:
        while True:
            session_id = self._queue.get()
            if session_id is None:
                return
            self._process(session_id)

    def _process(self, session_id: str) -> None:
        try:
            self._repository.update_status(session_id, status="running", stage="processing")
            result_path = self._repository.result_path(session_id)
            result_path.unlink(missing_ok=True)
            self._repository.work_dir(session_id).mkdir(exist_ok=True)
            self._processor.process(self._repository.source_path(session_id), result_path)
            if not result_path.is_file() or result_path.stat().st_size == 0:
                raise ProcessingError("The anonymized PDF could not be validated.")
            self._repository.update_status(session_id, status="completed", stage="ready")
        except SessionNotFoundError:
            return
        except ProcessingError as error:
            self._repository.result_path(session_id).unlink(missing_ok=True)
            self._repository.update_status(
                session_id,
                status="failed",
                stage="failed",
                error_message=str(error),
            )
        except Exception:
            self._repository.result_path(session_id).unlink(missing_ok=True)
            self._repository.update_status(
                session_id,
                status="failed",
                stage="failed",
                error_message="Processing stopped before a safe result could be created.",
            )
