from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from medical_deid_core import ModelStore, ModelStoreError

from medical_deid.processing import ProcessingCoordinator
from medical_deid.runtime_pipeline import ModelStorePipeline
from medical_deid.sessions import SessionNotFoundError, SessionRecord, SessionRepository

CONTRACT_VERSION = "1.0"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}
MODELS = ModelStore()
REPOSITORY = SessionRepository(MODELS.root / "sessions.sqlite3", MODELS.root / "sessions")
COORDINATOR = ProcessingCoordinator(REPOSITORY, ModelStorePipeline(MODELS))
INITIALIZED = False


def write_message(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def response(request_id: str, data: object | None = None, *, error: str | None = None) -> None:
    payload: dict[str, object] = {
        "schema_version": CONTRACT_VERSION,
        "type": "response",
        "request_id": request_id,
        "ok": error is None,
    }
    if error is None:
        payload["data"] = data
    else:
        payload["error"] = {"code": error}
    write_message(payload)


def ensure_initialized() -> None:
    global INITIALIZED
    if INITIALIZED:
        return
    REPOSITORY.initialize()
    COORDINATOR.start()
    INITIALIZED = True


def session_response(record: SessionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "sourceFilename": record.source_filename,
        "status": record.status,
        "stage": record.stage,
        "errorMessage": record.error_message,
        "resultAvailable": record.result_available,
    }


def runtime_info() -> dict[str, object]:
    inventory = MODELS.snapshot()
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


def create_document_from_path(message: dict[str, Any]) -> dict[str, object]:
    inventory = MODELS.snapshot()
    preflight = inventory.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("ok") is not True:
        raise ModelStoreError("models_are_not_ready")
    source_path = Path(str(message.get("source_path") or ""))
    filename = source_path.name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in SUPPORTED_SUFFIXES:
        raise ModelStoreError("unsupported_document_format")
    try:
        source_size = source_path.stat().st_size
    except OSError as error:
        raise ModelStoreError("document_is_not_readable") from error
    if source_size == 0:
        raise ModelStoreError("empty_document")
    if source_size > MAX_UPLOAD_BYTES:
        raise ModelStoreError("document_too_large")
    try:
        content = source_path.read_bytes()
    except OSError as error:
        raise ModelStoreError("document_is_not_readable") from error
    record = REPOSITORY.create(filename, suffix, content)
    COORDINATOR.submit(record.id)
    return session_response(record)


def save_result(message: dict[str, Any]) -> None:
    session_id = str(message.get("session_id") or "")
    destination = Path(str(message.get("destination_path") or ""))
    record = REPOSITORY.get(session_id)
    if record.status != "completed" or not record.result_available:
        raise ModelStoreError("result_not_ready")
    try:
        shutil.copy2(REPOSITORY.result_path(session_id), destination)
    except OSError as error:
        raise ModelStoreError("result_save_failed") from error


def dispatch(message: dict[str, Any]) -> bool:
    request_id = str(message.get("request_id") or uuid.uuid4())
    operation = message.get("operation")
    if message.get("schema_version") != CONTRACT_VERSION:
        response(request_id, error="unsupported_schema_version")
        return True

    try:
        ensure_initialized()
        if operation == "initialize":
            response(request_id, runtime_info())
        elif operation == "models":
            response(request_id, MODELS.snapshot())
        elif operation == "install_model":
            response(request_id, MODELS.start_install(str(message.get("profile_id"))))
        elif operation == "select_model":
            response(request_id, MODELS.select(str(message.get("profile_id"))))
        elif operation == "create_document_path":
            response(request_id, create_document_from_path(message))
        elif operation == "documents":
            response(request_id, [session_response(record) for record in REPOSITORY.list_recent()])
        elif operation == "document":
            response(request_id, session_response(REPOSITORY.get(str(message.get("session_id")))))
        elif operation == "save_result":
            save_result(message)
            response(request_id, {"saved": True})
        elif operation == "shutdown":
            COORDINATOR.stop()
            response(request_id, {"stopped": True})
            return False
        else:
            response(request_id, error="unknown_operation")
    except ModelStoreError as error:
        response(request_id, error=str(error))
    except SessionNotFoundError:
        response(request_id, error="session_not_found")
    return True


def main() -> None:
    for raw_line in sys.stdin:
        try:
            message = json.loads(raw_line)
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            keep_running = dispatch(message)
        except (TypeError, ValueError, json.JSONDecodeError):
            write_message(
                {
                    "schema_version": CONTRACT_VERSION,
                    "type": "error",
                    "error": {"code": "malformed_message"},
                }
            )
            keep_running = True
        if not keep_running:
            break


if __name__ == "__main__":
    main()
