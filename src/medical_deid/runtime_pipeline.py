"""Configured local OCR and Qwen inference for the greenfield model store."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from pathlib import Path

from medical_deid_core.models import ModelStore

from .pipeline import (
    OcrBlock,
    _IDENTIFIER_KINDS,
    _entity_schema,
    _html_to_text,
    _image_size,
    _recommended_cpu_threads,
)
from .pipeline import LocalMedicalPipeline as BasePipeline
from .processing import ProcessingError
from .redaction import EntityMatch


class ModelStorePipeline(BasePipeline):
    """Run the existing safe reconstruction pipeline against verified model files."""

    def __init__(self, store: ModelStore, *, cpu_threads: int | None = None) -> None:
        super().__init__(models_dir=store.root, cpu_threads=cpu_threads)
        self._store = store
        self._surya_manager: Any | None = None

    def _model_path(self) -> Path:
        try:
            return self._store.model_path()
        except Exception as error:
            raise ProcessingError("The selected local identifier model is not ready.") from error

    def _run_surya(self, source_path: Path, work_dir: Path) -> list[OcrBlock]:
        try:
            ocr_model, ocr_projector = self._store.ocr_paths()
            runtime = self._store.runtime_server()
        except Exception as error:
            raise ProcessingError("OCR models or local runtime are not ready.") from error

        os.environ.update(
            {
                "SURYA_INFERENCE_BACKEND": "llamacpp",
                "SURYA_INFERENCE_PARALLEL": "1",
                "SURYA_GGUF_LOCAL_MODEL_PATH": str(ocr_model),
                "SURYA_GGUF_LOCAL_MMPROJ_PATH": str(ocr_projector),
                "LLAMA_CPP_BINARY": str(runtime),
            }
        )
        try:
            from surya.inference import SuryaInferenceManager
            from surya.input.load import load_from_file
            from surya.recognition import RecognitionPredictor
            from surya.settings import settings

            if self._surya_manager is None:
                self._surya_manager = SuryaInferenceManager(method="llamacpp")
            images, _ = load_from_file(str(source_path), dpi=settings.IMAGE_DPI_HIGHRES)
            pages = RecognitionPredictor(self._surya_manager)(images, full_page=True)
        except Exception as error:
            raise ProcessingError("OCR could not process this document.") from error
        return _blocks_from_surya_pages(pages)

    def _llm_entities(
        self,
        blocks: list[OcrBlock],
        work_dir: Path,
    ) -> dict[int, dict[int, list[EntityMatch]]]:
        entities_by_page: dict[int, dict[int, list[EntityMatch]]] = {}
        for page_number in sorted({block.page_number for block in blocks}):
            page_blocks = [
                block for block in blocks if block.page_number == page_number and block.text
            ]
            proposals = _extract_entities_with_qwen(
                page_blocks,
                work_dir / f"llm-page-{page_number}.json",
                self._model_path(),
                self._store.runtime_binary("llama-cli"),
                self._cpu_threads or _recommended_cpu_threads(),
                self._store.runtime_spec().backend != "cpu",
            )
            page_entities: dict[int, list[EntityMatch]] = {}
            for fragment_id, entity in proposals:
                page_entities.setdefault(fragment_id, []).append(entity)
            entities_by_page[page_number] = page_entities
        return entities_by_page


def _extract_entities_with_qwen(
    blocks: list[OcrBlock],
    schema_path: Path,
    model_path: Path,
    llama_cli: Path,
    threads: int,
    gpu_enabled: bool,
) -> list[tuple[int, EntityMatch]]:
    if not blocks:
        return []
    fragments = "\n".join(f"[{index}] {block.text}" for index, block in enumerate(blocks, start=1))
    schema = _entity_schema()
    schema_path.with_suffix(".schema.json").write_text(
        json.dumps(schema, ensure_ascii=False), encoding="utf-8"
    )
    prompt = (
        "Ты выделяешь только персональные данные пациента и его родственников в OCR медицинского "
        "документа. Не включай врачей, медсестёр, клиники, отделения, учреждения, диагнозы, "
        "исследования, результаты, референсы или даты лечения. Для каждого найденного значения верни "
        "точный фрагмент OCR без исправлений, fragment_id и тип. Если сомневаешься, верни пустой список. "
        'Верни только JSON вида {"entities":[{"fragment_id":1,"text":"...",'
        '"kind":"patient_name"}]}. Допустимые kind: '
        + ", ".join(sorted(_IDENTIFIER_KINDS))
        + "\n\nOCR-фрагменты:\n"
        + fragments
    )
    command = [
        str(llama_cli),
        "--model",
        str(model_path),
        "--gpu-layers",
        "all" if gpu_enabled else "0",
        "--ctx-size",
        "8192",
        "--temp",
        "0.1",
        "--reasoning",
        "off",
        "--single-turn",
        "--no-display-prompt",
        "--simple-io",
        "--log-disable",
        "--n-predict",
        "2048",
        "--threads",
        str(threads),
        "--threads-batch",
        str(threads),
        "--prompt",
        prompt,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        raise ProcessingError("The local identifier model could not process OCR text.")
    try:
        raw = json.loads(_json_object_from_output(completed.stdout))
    except json.JSONDecodeError as error:
        raise ProcessingError("The local identifier model returned an invalid result.") from error
    schema_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_entities = raw.get("entities")
    if not isinstance(raw_entities, list):
        raise ProcessingError("The local identifier model returned an invalid result.")
    extracted: list[tuple[int, EntityMatch]] = []
    for raw_entity in raw_entities:
        if not isinstance(raw_entity, dict):
            raise ProcessingError("The local identifier model returned an invalid result.")
        fragment_id = raw_entity.get("fragment_id")
        text = raw_entity.get("text")
        kind = raw_entity.get("kind")
        if (
            not isinstance(fragment_id, int)
            or not 1 <= fragment_id <= len(blocks)
            or not isinstance(text, str)
            or not isinstance(kind, str)
            or kind not in _IDENTIFIER_KINDS
        ):
            raise ProcessingError("The local identifier model returned an invalid result.")
        extracted.append((id(blocks[fragment_id - 1]), EntityMatch(text=text, kind=kind)))
    return extracted


def _blocks_from_surya_pages(pages: list[Any]) -> list[OcrBlock]:
    blocks: list[OcrBlock] = []
    for page_number, page in enumerate(pages, start=1):
        raw_page = page.model_dump()
        image_size = _image_size(raw_page.get("image_bbox"))
        for raw_block in raw_page.get("blocks", []):
            raw_bbox = raw_block.get("bbox")
            if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                continue
            blocks.append(
                OcrBlock(
                    page_number=page_number,
                    bbox=tuple(float(value) for value in raw_bbox),
                    text=_html_to_text(str(raw_block.get("html", ""))),
                    label=str(raw_block.get("label", "")),
                    image_size=image_size,
                )
            )
    return blocks


def _json_object_from_output(output: str) -> str:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("JSON object not found", output, 0)
    return output[start : end + 1]
