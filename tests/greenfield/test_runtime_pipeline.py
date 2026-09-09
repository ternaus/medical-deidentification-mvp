from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from medical_deid.pipeline import OcrBlock
from medical_deid.redaction import EntityMatch
from medical_deid.runtime_pipeline import ModelStorePipeline


class SwitchingModelStore:
    def __init__(self, model_paths: list[Path]) -> None:
        self.root = model_paths[0].parent
        self._model_paths = iter(model_paths)

    def model_path(self) -> Path:
        return next(self._model_paths)

    def runtime_binary(self, _: str) -> Path:
        return Path("/runtime/llama-cli")

    def runtime_spec(self) -> SimpleNamespace:
        return SimpleNamespace(backend="cpu")


def test_document_uses_one_model_for_every_page(monkeypatch, tmp_path: Path) -> None:
    first_model = tmp_path / "first.gguf"
    second_model = tmp_path / "second.gguf"
    used_models: list[Path] = []

    def capture_model(
        _blocks: list[OcrBlock],
        _schema_path: Path,
        model_path: Path,
        _llama_cli: Path,
        _threads: int,
        _gpu_enabled: bool,
    ) -> list[tuple[int, EntityMatch]]:
        used_models.append(model_path)
        return []

    monkeypatch.setattr("medical_deid.runtime_pipeline._extract_entities_with_qwen", capture_model)
    pipeline = ModelStorePipeline(SwitchingModelStore([first_model, second_model]))
    blocks = [
        OcrBlock(page_number=1, bbox=(0, 0, 10, 10), text="first", label="Text"),
        OcrBlock(page_number=2, bbox=(0, 0, 10, 10), text="second", label="Text"),
    ]

    pipeline._redact_blocks(blocks, tmp_path)

    assert used_models == [first_model, first_model]


def test_pipeline_snapshots_the_model_when_processing_starts(monkeypatch, tmp_path: Path) -> None:
    first_model = tmp_path / "first.gguf"
    second_model = tmp_path / "second.gguf"

    def verify_snapshot(pipeline: ModelStorePipeline, _: Path, __: Path) -> None:
        assert pipeline._model_path() == first_model
        assert pipeline._model_path() == first_model

    monkeypatch.setattr("medical_deid.runtime_pipeline.BasePipeline.process", verify_snapshot)

    ModelStorePipeline(SwitchingModelStore([first_model, second_model])).process(
        tmp_path / "source.pdf", tmp_path / "result.pdf"
    )
