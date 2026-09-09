"""Run the local de-identification pipeline over a fixed synthetic corpus."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from pypdf import PdfReader

from medical_deid.pipeline import LocalMedicalPipeline
from medical_deid.processing import ProcessingError

_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}


def main() -> int:
    """Process every supported file and save an inspectable local run manifest."""
    arguments = _parse_arguments()
    sources = sorted(
        path
        for path in arguments.source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _SUFFIXES
    )
    if not sources:
        raise SystemExit("The corpus directory has no supported PDF, JPG, JPEG, or PNG files.")

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = LocalMedicalPipeline(
        models_dir=arguments.models_dir,
        llm_model_path=arguments.llm_model_path,
    )
    records = []
    for index, source in enumerate(sources, start=1):
        session_dir = arguments.output_dir / f"{index:02}-{source.stem}"
        session_dir.mkdir(parents=True, exist_ok=True)
        copied_source = session_dir / f"source{source.suffix.lower()}"
        shutil.copy2(source, copied_source)
        result_path = session_dir / "anonymized.pdf"
        started = time.monotonic()
        try:
            pipeline.process(copied_source, result_path)
        except ProcessingError as error:
            if result_path.is_file():
                result_path.rename(session_dir / "candidate-invalid.pdf")
            records.append(
                {
                    "source": source.name,
                    "status": "failed",
                    "seconds": round(time.monotonic() - started, 1),
                    "reason": str(error),
                }
            )
            continue
        extracted_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(str(result_path)).pages
        )
        (session_dir / "extracted-result.txt").write_text(extracted_text, encoding="utf-8")
        records.append(
            {
                "source": source.name,
                "status": "completed",
                "seconds": round(time.monotonic() - started, 1),
                "result": str(result_path.relative_to(arguments.output_dir)),
                "pages": len(PdfReader(str(result_path)).pages),
            }
        )

    manifest = {"documents": records}
    (arguments.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 1 if any(record["status"] == "failed" for record in records) else 0


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, default=Path(".models"))
    parser.add_argument(
        "--llm-model-path",
        type=Path,
        help="Use this GGUF for the LLM stage instead of the default baseline model.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
