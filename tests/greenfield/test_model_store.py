from __future__ import annotations

import json

from medical_deid_core import ModelStore


def test_restart_marks_an_interrupted_model_download_as_retryable(tmp_path) -> None:
    (tmp_path / "model-state.json").write_text(
        json.dumps(
            {
                "install": {
                    "profile_id": "qwen3-4b-q4-k-m",
                    "state": "downloading",
                    "current_asset": "Qwen3 4B Q4_K_M",
                    "downloaded_bytes": 123,
                    "total_bytes": 456,
                    "error": None,
                }
            }
        ),
        encoding="utf-8",
    )

    profile = ModelStore(tmp_path).snapshot()["profiles"][0]

    assert profile["state"] == "failed"
    assert profile["error"] == "download_interrupted"
