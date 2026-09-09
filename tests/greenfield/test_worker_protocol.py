from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from medical_deid.sessions import SessionRepository

ROOT = Path(__file__).resolve().parents[2]
PYTHONPATH = os.pathsep.join(
    [
        str(ROOT / "src"),
        str(ROOT / "packages" / "python-core" / "src"),
        str(ROOT / "packages" / "desktop-worker" / "src"),
    ]
)


def send(process: subprocess.Popen[str], message: dict[str, object]) -> dict[str, object]:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line
    return json.loads(line)


def test_worker_reports_setup_and_rejects_document_before_model_install(tmp_path) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "medical_deid_worker"],
        cwd=ROOT,
        env={
            **os.environ,
            "MEDICAL_DEID_DATA_DIR": str(tmp_path),
            "PYTHONPATH": PYTHONPATH,
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        initialized = send(
            process, {"schema_version": "1.0", "request_id": "r1", "operation": "initialize"}
        )
        assert initialized["ok"] is True
        assert initialized["data"]["mode"] == "setup"

        models = send(process, {"schema_version": "1.0", "request_id": "r2", "operation": "models"})
        assert models["data"]["profiles"][0]["id"] == "qwen3-4b-q4-k-m"

        blocked = send(
            process,
            {
                "schema_version": "1.0",
                "request_id": "r3",
                "operation": "create_document_path",
                "source_path": str(tmp_path / "scan.pdf"),
            },
        )
        assert blocked["ok"] is False
        assert blocked["error"]["code"] == "models_are_not_ready"

        stopped = send(
            process, {"schema_version": "1.0", "request_id": "r4", "operation": "shutdown"}
        )
        assert stopped["data"]["stopped"] is True
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()


def test_worker_lists_sessions_recovered_after_relaunch(tmp_path) -> None:
    repository = SessionRepository(tmp_path / "sessions.sqlite3", tmp_path / "sessions")
    repository.initialize()
    recovered = repository.create("recovered.pdf", ".pdf", b"%PDF-source")
    process = subprocess.Popen(
        [sys.executable, "-m", "medical_deid_worker"],
        cwd=ROOT,
        env={
            **os.environ,
            "MEDICAL_DEID_DATA_DIR": str(tmp_path),
            "PYTHONPATH": PYTHONPATH,
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        sessions = send(
            process, {"schema_version": "1.0", "request_id": "r1", "operation": "documents"}
        )

        assert sessions["ok"] is True
        assert [session["id"] for session in sessions["data"]] == [recovered.id]
    finally:
        if process.poll() is None:
            send(process, {"schema_version": "1.0", "request_id": "r2", "operation": "shutdown"})
            process.wait(timeout=2)
