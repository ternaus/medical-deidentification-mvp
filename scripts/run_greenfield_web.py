from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "python-core" / "src"),
    str(ROOT / "services" / "web-api" / "src"),
]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "medical_deid_web.app:app",
        host=os.environ.get("MEDICAL_DEID_HOST", "127.0.0.1"),
        port=int(os.environ.get("MEDICAL_DEID_PORT", "8000")),
        reload=os.environ.get("MEDICAL_DEID_RELOAD") == "1",
    )
