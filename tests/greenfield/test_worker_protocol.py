from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHONPATH = os.pathsep.join(
    [
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


def test_worker_review_round_trip() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "medical_deid_worker"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": PYTHONPATH},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        initialized = send(process, {"schema_version": "1.0", "request_id": "r1", "operation": "initialize"})
        assert initialized["ok"] is True
        assert initialized["data"]["mode"] == "review"

        created = send(
            process,
            {"schema_version": "1.0", "request_id": "r2", "operation": "create_review_session"},
        )
        assert created["data"]["status"] == "completed"
        assert len(created["data"]["changes"]) == 3
        assert "Иван Петров" not in created["data"]["resultText"]

        feedback = send(
            process,
            {
                "schema_version": "1.0",
                "request_id": "r3",
                "operation": "submit_feedback",
                "session_id": created["data"]["id"],
                "rating": "correct",
            },
        )
        assert feedback["data"] == {"accepted": True}

        stopped = send(process, {"schema_version": "1.0", "request_id": "r4", "operation": "shutdown"})
        assert stopped["data"]["stopped"] is True
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
