from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from medical_deid_core import create_review_session

CONTRACT_VERSION = "1.0"
SESSIONS: dict[str, dict[str, object]] = {}


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


def dispatch(message: dict[str, Any]) -> bool:
    request_id = str(message.get("request_id") or uuid.uuid4())
    operation = message.get("operation")
    if message.get("schema_version") != CONTRACT_VERSION:
        response(request_id, error="unsupported_schema_version")
        return True

    if operation == "initialize":
        response(
            request_id,
            {
                "mode": message.get("runtime_mode", "review"),
                "processingEnabled": False,
                "appVersion": "0.1.0",
                "coreVersion": "0.1.0",
                "ocrVersion": "not-loaded",
                "modelVersion": None,
                "modelStatus": "not_installed",
                "supportedFormats": ["pdf", "jpg", "jpeg", "png"],
            },
        )
        return True
    if operation == "create_review_session":
        session_id = str(message.get("session_id") or uuid.uuid4())
        session = create_review_session(session_id)
        SESSIONS[session_id] = session
        response(request_id, session)
        return True
    if operation == "get_session":
        session_id = str(message.get("session_id"))
        session = SESSIONS.get(session_id)
        response(request_id, session, error=None if session else "session_not_found")
        return True
    if operation == "delete_session":
        session_id = str(message.get("session_id"))
        existed = SESSIONS.pop(session_id, None) is not None
        response(request_id, {"deleted": existed})
        return True
    if operation == "submit_feedback":
        session_id = str(message.get("session_id"))
        session = SESSIONS.get(session_id)
        if session is None:
            response(request_id, error="session_not_found")
        elif message.get("rating") not in {"correct", "incorrect"}:
            response(request_id, error="invalid_feedback")
        else:
            session["feedback"] = {"rating": message["rating"], "note": message.get("note")}
            response(request_id, {"accepted": True})
        return True
    if operation == "shutdown":
        response(request_id, {"stopped": True})
        return False
    response(request_id, error="unknown_operation")
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
