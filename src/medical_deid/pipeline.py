"""Local OCR, identifier extraction, and searchable-PDF reconstruction."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from medical_deid.processing import DocumentProcessor, ProcessingError
from medical_deid.redaction import EntityMatch, RedactionChange, RedactionError, apply_replacements

_FONT_NAME = "MedicalDeidUnicode"
_FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
_IDENTIFIER_KINDS = {
    "address",
    "birth_date",
    "email",
    "government_id",
    "insurance_id",
    "medical_record_id",
    "other",
    "patient_name",
    "phone",
    "relative_name",
    "workplace",
}
_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


@dataclass(frozen=True)
class OcrBlock:
    """One positioned piece of OCR output on a rendered page."""

    page_number: int
    bbox: tuple[float, float, float, float]
    text: str
    label: str
    image_size: tuple[float, float] | None = None


@dataclass(frozen=True)
class RedactedBlock:
    """The text and visible replacements that belong to a positioned OCR block."""

    source: OcrBlock
    text: str
    changes: list[RedactionChange]
    omit: bool = False
    force_visible: bool = False


class LocalMedicalPipeline(DocumentProcessor):
    """Process one local upload without sending its text or pixels to a service."""

    def __init__(self, models_dir: Path = Path(".models")) -> None:
        self._models_dir = models_dir

    def process(self, source_path: Path, result_path: Path) -> None:
        """Create a safe PDF only when OCR and local-model proposals validate."""
        work_dir = result_path.parent / "work"
        pages = _render_source_pages(source_path, work_dir / "pages")
        blocks = self._run_surya(source_path, work_dir)
        if not blocks:
            raise ProcessingError("OCR did not return readable text blocks.")
        if max(block.page_number for block in blocks) != len(pages):
            raise ProcessingError("OCR page coordinates could not be validated.")

        try:
            redacted_blocks = self._redact_blocks(blocks, work_dir)
        except RedactionError as error:
            raise ProcessingError("An identifier proposal could not be verified against OCR text.") from error
        _write_change_log(work_dir / "change-log.json", redacted_blocks)
        _write_searchable_pdf(result_path, pages, redacted_blocks, work_dir)
        _validate_export(result_path, redacted_blocks)

    def _run_surya(self, source_path: Path, work_dir: Path) -> list[OcrBlock]:
        output_dir = work_dir / "ocr"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = _surya_command()
        environment = os.environ | {
            "SURYA_INFERENCE_BACKEND": "llamacpp",
            "SURYA_INFERENCE_PARALLEL": "1",
        }
        completed = subprocess.run(
            [str(command), str(source_path), "--images", "--output_dir", str(output_dir)],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            raise ProcessingError("OCR could not process this document.")
        results = list(output_dir.rglob("results.json"))
        if len(results) != 1:
            raise ProcessingError("OCR did not create one readable result.")
        return _parse_surya_results(results[0])

    def _redact_blocks(self, blocks: list[OcrBlock], work_dir: Path) -> list[RedactedBlock]:
        entities_by_page = self._llm_entities(blocks, work_dir)
        all_text = "\n".join(block.text for block in blocks)
        document_date = _latest_document_date(all_text)
        birth_dates = _birth_dates_from_proposals(entities_by_page)
        omitted_blocks = _signature_panel_blocks(blocks)
        institution_contact_blocks = _institution_contact_block_ids(blocks)
        doctor_signature_blocks = {id(block) for block in blocks if _is_doctor_attribution(block.text)}
        placeholder_counts: dict[str, int] = {}
        redacted: list[RedactedBlock] = []

        for block in blocks:
            entities = _regex_entities(block.text) + entities_by_page.get(block.page_number, {}).get(
                id(block), []
            )
            if id(block) in institution_contact_blocks:
                entities = [
                    entity
                    for entity in entities
                    if entity.kind not in {"address", "email", "phone", "workplace"}
                ]
            if not any(entity.kind == "birth_date" for entity in entities):
                entities.extend(_matching_birth_dates(block.text, birth_dates))
            entities = _with_age_replacement(block.text, entities, document_date)
            sanitized, changes = apply_replacements(
                block.text,
                entities,
                placeholder_counts=placeholder_counts,
            )
            redacted.append(
                RedactedBlock(
                    source=block,
                    text=sanitized,
                    changes=changes,
                    omit=id(block) in omitted_blocks,
                    force_visible=id(block) in doctor_signature_blocks,
                )
            )
        return redacted

    def _llm_entities(
        self,
        blocks: list[OcrBlock],
        work_dir: Path,
    ) -> dict[int, dict[int, list[EntityMatch]]]:
        entities_by_page: dict[int, dict[int, list[EntityMatch]]] = {}
        for page_number in sorted({block.page_number for block in blocks}):
            page_blocks = [block for block in blocks if block.page_number == page_number and block.text]
            proposals = _extract_entities_with_llm(
                page_blocks,
                work_dir / f"llm-page-{page_number}.json",
                self._model_path(),
            )
            page_entities: dict[int, list[EntityMatch]] = {}
            for fragment_id, entity in proposals:
                page_entities.setdefault(fragment_id, []).append(entity)
            entities_by_page[page_number] = page_entities
        return entities_by_page

    def _model_path(self) -> Path:
        candidates = [
            self._models_dir
            / "qwen3-next-80b-a3b-q4_k_m"
            / "Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf",
            self._models_dir / "qwen3-30b-a3b-q4_k_m" / "Qwen3-30B-A3B-Q4_K_M.gguf",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ProcessingError("The local identifier model is not available yet.")


def _surya_command() -> Path:
    candidate = Path(sys.executable).with_name("surya_ocr")
    if candidate.is_file():
        return candidate
    executable = shutil.which("surya_ocr")
    if executable is None:
        raise ProcessingError("The local OCR runtime is not available yet.")
    return Path(executable)


def _parse_surya_results(path: Path) -> list[OcrBlock]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProcessingError("OCR returned an unreadable result.") from error
    if not isinstance(payload, dict):
        raise ProcessingError("OCR returned an invalid result shape.")

    blocks: list[OcrBlock] = []
    page_number = 0
    for page_results in payload.values():
        if not isinstance(page_results, list):
            raise ProcessingError("OCR page grouping could not be validated.")
        for page in page_results:
            if not isinstance(page, dict):
                raise ProcessingError("OCR page grouping could not be validated.")
            page_number += 1
            image_size = _image_size(page.get("image_bbox"))
            for raw_block in page.get("blocks", []):
                raw_bbox = raw_block.get("bbox")
                if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                    continue
                text = _html_to_text(str(raw_block.get("html", "")))
                blocks.append(
                    OcrBlock(
                        page_number=page_number,
                        bbox=tuple(float(value) for value in raw_bbox),
                        text=text,
                        label=str(raw_block.get("label", "")),
                        image_size=image_size,
                    )
                )
    return blocks


def _render_source_pages(source_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if source_path.suffix.lower() == ".pdf":
        document = pdfium.PdfDocument(str(source_path))
        paths: list[Path] = []
        try:
            for index in range(len(document)):
                page = document[index]
                image = page.render(scale=2).to_pil().convert("RGB")
                destination = output_dir / f"page-{index + 1:03}.png"
                image.save(destination)
                paths.append(destination)
        finally:
            document.close()
        if not paths:
            raise ProcessingError("The PDF has no renderable pages.")
        return paths

    with Image.open(source_path) as source_image:
        image = ImageOps.exif_transpose(source_image).convert("RGB")
        destination = output_dir / "page-001.png"
        image.save(destination)
    return [destination]


def _extract_entities_with_llm(
    blocks: list[OcrBlock],
    schema_path: Path,
    model_path: Path,
) -> list[tuple[int, EntityMatch]]:
    if not blocks:
        return []
    fragments = "\n".join(
        f"[{index}] {block.text}" for index, block in enumerate(blocks, start=1)
    )
    schema_path.with_suffix(".schema.json").write_text(
        json.dumps(_entity_schema(), ensure_ascii=False), encoding="utf-8"
    )
    prompt = (
        "Ты выделяешь только персональные данные пациента и его родственников в OCR медицинского "
        "документа. Не включай врачей, медсестёр, клиники, отделения, учреждения, диагнозы, "
        "исследования, результаты, референсы или даты лечения. Для каждого найденного значения верни "
        "точный фрагмент OCR без исправлений, fragment_id и тип. Если сомневаешься, верни пустой список. "
        "Верни только JSON вида {\"entities\":[{\"fragment_id\":1,\"text\":\"...\","
        "\"kind\":\"patient_name\"}]}. Допустимые kind: "
        + ", ".join(sorted(_IDENTIFIER_KINDS))
        + ".\n\n"
        f"OCR-фрагменты:\n{fragments}"
    )
    completed = subprocess.run(
        [
            "llama-cli",
            "--model",
            str(model_path),
            "--gpu-layers",
            "all",
            "--ctx-size",
            "32768",
            "--cache-type-k",
            "q8_0",
            "--cache-type-v",
            "q8_0",
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
            "--prompt",
            prompt,
        ],
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
            or fragment_id < 1
            or fragment_id > len(blocks)
            or not isinstance(text, str)
            or not isinstance(kind, str)
            or kind not in _IDENTIFIER_KINDS
        ):
            raise ProcessingError("The local identifier model returned an invalid result.")
        extracted.append((id(blocks[fragment_id - 1]), EntityMatch(text=text, kind=kind)))
    return extracted


def _entity_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fragment_id": {"type": "integer"},
                        "text": {"type": "string"},
                        "kind": {"type": "string", "enum": sorted(_IDENTIFIER_KINDS)},
                    },
                    "required": ["fragment_id", "text", "kind"],
                },
            }
        },
        "required": ["entities"],
    }


def _regex_entities(text: str) -> list[EntityMatch]:
    matches: list[EntityMatch] = []
    patterns = [
        ("email", r"\b[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-яЁё]{2,}\b"),
        ("phone", r"(?<!\d)(?:\+7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"),
        ("insurance_id", r"(?i)\bИНЗ\s*:\s*\d{4,}"),
        ("government_id", r"(?<!\d)\d{3}-\d{3}-\d{3}\s?\d{2}(?!\d)"),
        (
            "medical_record_id",
            r"(?i)(?<=номер ЭМК:\s)[A-Za-zА-Яа-яЁё0-9/-]{4,}|(?<=№ ЭМК:\s)[A-Za-zА-Яа-яЁё0-9/-]{4,}",
        ),
        (
            "birth_date",
            r"(?i:дата\s+рождения|д\.?\s*р\.?)\s*:\s*(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{1,2}\s+(?:"
            + "|".join(_MONTHS)
            + r")\s+\d{4})",
        ),
    ]
    for kind, pattern in patterns:
        matches.extend(EntityMatch(text=match.group(0), kind=kind) for match in re.finditer(pattern, text))
    return matches


def _with_age_replacement(
    text: str,
    entities: list[EntityMatch],
    document_date: date | None,
) -> list[EntityMatch]:
    replacements: list[EntityMatch] = []
    for entity in entities:
        if entity.kind != "birth_date":
            replacements.append(entity)
            continue
        date_matches = [
            (candidate, parsed)
            for candidate in _date_candidates(entity.text)
            if (parsed := _parse_date(candidate)) is not None
        ]
        birth_text, birth_date = date_matches[0] if len(date_matches) == 1 else (None, None)
        if birth_date is None and _is_age_expression(entity.text):
            continue
        if birth_date is None or document_date is None or document_date <= birth_date:
            raise ProcessingError("Date of birth was found but the document date could not be verified.")
        age = document_date.year - birth_date.year - (
            (document_date.month, document_date.day) < (birth_date.month, birth_date.day)
        )
        labelled_date = re.search(
            r"дата\s+рождения\s*:\s*" + re.escape(birth_text),
            text,
            flags=re.IGNORECASE,
        )
        source_text = labelled_date.group(0) if labelled_date is not None else birth_text
        source_start = text.find(source_text)
        if source_start >= 0 and source_text.lower().startswith("дата рождения"):
            existing_age = re.match(
                r"\s+(?:Возраст:\s*)?(?:\(\s*)?\d+\s+(?:года|год|лет)(?:\s*\))?",
                text[source_start + len(source_text) :],
                flags=re.IGNORECASE,
            )
            if existing_age is not None:
                source_text += existing_age.group(0)
        replacements.append(
            EntityMatch(
                text=source_text,
                kind="birth_date",
                replacement=f"Возраст: {age} {_age_word(age)}",
            )
        )
    return replacements


def _is_age_expression(value: str) -> bool:
    return re.fullmatch(r"\d{1,3}\s+(?:год|года|лет)", value.strip(), flags=re.IGNORECASE) is not None


def _birth_dates_from_proposals(
    entities_by_page: dict[int, dict[int, list[EntityMatch]]],
) -> set[date]:
    dates: set[date] = set()
    for blocks in entities_by_page.values():
        for entities in blocks.values():
            for entity in entities:
                if entity.kind == "birth_date":
                    dates.update(
                        parsed
                        for candidate in _date_candidates(entity.text)
                        if (parsed := _parse_date(candidate)) is not None
                    )
    return dates


def _matching_birth_dates(text: str, birth_dates: set[date]) -> list[EntityMatch]:
    return [
        EntityMatch(text=candidate, kind="birth_date")
        for candidate in _date_candidates(text)
        if _parse_date(candidate) in birth_dates
    ]


def _age_word(age: int) -> str:
    if 11 <= age % 100 <= 14:
        return "лет"
    if age % 10 == 1:
        return "год"
    if 2 <= age % 10 <= 4:
        return "года"
    return "лет"


def _latest_document_date(text: str) -> date | None:
    dates = [parsed for candidate in _date_candidates(text) if (parsed := _parse_date(candidate))]
    return max(dates, default=None)


def _date_candidates(text: str) -> list[str]:
    numeric = re.findall(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{4}(?!\d)", text)
    written = re.findall(
        r"(?<!\d)\d{1,2}\s+(?:" + "|".join(_MONTHS) + r")\s+\d{4}(?!\d)",
        text,
        flags=re.IGNORECASE,
    )
    return numeric + written


def _parse_date(value: str) -> date | None:
    numeric = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
    else:
        written = re.fullmatch(r"(\d{1,2})\s+(\S+)\s+(\d{4})", value, flags=re.IGNORECASE)
        if written is None:
            return None
        day = int(written.group(1))
        month = _MONTHS.get(written.group(2).lower())
        year = int(written.group(3))
        if month is None:
            return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _write_searchable_pdf(
    destination: Path,
    page_paths: list[Path],
    blocks: list[RedactedBlock],
    work_dir: Path,
) -> None:
    if not _FONT_PATH.is_file():
        raise ProcessingError("The local PDF font is not available.")
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_PATH)))
    pdf = Canvas(str(destination))
    blocks_by_page: dict[int, list[RedactedBlock]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.source.page_number, []).append(block)

    sanitized_pages = _sanitize_source_pixels(page_paths, blocks_by_page, work_dir / "sanitized")

    for page_number, page_path in enumerate(sanitized_pages, start=1):
        with Image.open(page_path) as image:
            width, height = image.size
        pdf.setPageSize((width, height))
        pdf.drawImage(ImageReader(str(page_path)), 0, 0, width=width, height=height)
        page_blocks = blocks_by_page.get(page_number, [])
        for block in page_blocks:
            if block.omit:
                continue
            if block.changes or block.force_visible:
                _draw_visible_replacement(pdf, block, width, height)
            else:
                _draw_sanitized_text_layer(pdf, block, width, height)
        pdf.showPage()
    pdf.save()


def _draw_visible_replacement(
    pdf: Canvas,
    block: RedactedBlock,
    page_width: int,
    page_height: int,
) -> None:
    x0, y0, x1, y1 = _rendered_bbox(block.source, page_width, page_height)
    width = max(1, x1 - x0 - 6)
    height = max(1, y1 - y0 - 6)
    font_size, lines = _visible_text_layout(block.text, width, height)
    baseline = page_height - y0 - font_size - 2
    pdf.addLiteral("0 Tr")
    text = pdf.beginText(x0 + 3, baseline)
    text.setFillColorRGB(0, 0, 0)
    text.setFont(_FONT_NAME, font_size)
    for line in lines:
        text.textLine(line)
    pdf.drawText(text)


def _visible_text_layout(text: str, width: float, height: float) -> tuple[float, list[str]]:
    font_size = min(48, max(11, height / 1.8))
    while True:
        lines = simpleSplit(text, _FONT_NAME, font_size, width)
        max_lines = max(1, int(height // (font_size * 1.2)))
        if len(lines) <= max_lines or font_size <= 11:
            return font_size, lines[:max_lines]
        font_size = max(11, font_size - 1)


def _draw_sanitized_text_layer(
    pdf: Canvas,
    block: RedactedBlock,
    page_width: int,
    page_height: int,
) -> None:
    if not block.text:
        return
    x0, y0, _, _ = _rendered_bbox(block.source, page_width, page_height)
    text = pdf.beginText(x0, page_height - y0)
    text.setFont(_FONT_NAME, 7)
    text.setTextRenderMode(3)
    text.textLine(block.text)
    pdf.drawText(text)


def _sanitize_source_pixels(
    page_paths: list[Path],
    blocks_by_page: dict[int, list[RedactedBlock]],
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sanitized: list[Path] = []
    for page_number, page_path in enumerate(page_paths, start=1):
        with Image.open(page_path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        page_blocks = blocks_by_page.get(page_number, [])
        for block in page_blocks:
            should_omit = _should_omit_block(block.source, *image.size)
            if block.changes or block.omit or should_omit:
                padding = 48 if should_omit else 16
                draw.rectangle(_padded_bbox(block.source, *image.size, padding=padding), fill="white")
            if block.force_visible:
                draw.rectangle(_rendered_bbox(block.source, *image.size), fill="white")
                draw.rectangle(_doctor_signature_bbox(block.source, *image.size), fill="white")
        _erase_blue_signature_ink(image, [block.source for block in page_blocks])
        destination = output_dir / page_path.name
        image.save(destination)
        sanitized.append(destination)
    return sanitized


def _should_omit_block(block: OcrBlock, page_width: int, page_height: int) -> bool:
    if "ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ" in block.text.upper():
        return True
    if block.label != "Picture":
        return False
    x0, y0, x1, y1 = block.bbox
    image_width, image_height = block.image_size or (page_width, page_height)
    return (x1 - x0) * (y1 - y0) / (image_width * image_height) < 0.15


def _is_institution_contact_block(text: str) -> bool:
    institution_markers = (
        "БОЛЬНИЦ",
        "ГБУЗ",
        "ИНВИТРО",
        "КЛИНИК",
        "ЛАБОРАТОР",
        "МЕДИЦИНСК",
        "ПОЛИКЛИНИК",
        "ООО",
    )
    normalized = text.upper()
    return any(marker in normalized for marker in institution_markers)


def _institution_contact_block_ids(blocks: list[OcrBlock]) -> set[int]:
    institution_blocks = {
        id(block) for block in blocks if _is_institution_contact_block(block.text)
    }
    institution_pages = {block.page_number for block in blocks if id(block) in institution_blocks}
    patient_starts = {
        page_number: min(
            block.bbox[1]
            for block in blocks
            if block.page_number == page_number
            and re.search(r"\b(?:пациент|фио)\b", block.text, flags=re.IGNORECASE)
        )
        for page_number in institution_pages
        if any(
            block.page_number == page_number
            and re.search(r"\b(?:пациент|фио)\b", block.text, flags=re.IGNORECASE)
            for block in blocks
        )
    }
    for block in blocks:
        if block.page_number not in patient_starts or id(block) in institution_blocks:
            continue
        if block.bbox[1] >= patient_starts[block.page_number]:
            continue
        if re.search(r"(?i)\b(?:тел|факс)\b|www\.|@", block.text):
            institution_blocks.add(id(block))
    for header in blocks:
        if id(header) not in institution_blocks:
            continue
        header_x0, _, _, header_y1 = header.bbox
        for block in blocks:
            block_x0, block_y0, _, _ = block.bbox
            if (
                block.page_number == header.page_number
                and 0 <= block_y0 - header_y1 <= 80
                and abs(block_x0 - header_x0) <= 80
            ):
                institution_blocks.add(id(block))
    return institution_blocks


def _erase_blue_signature_ink(image: Image.Image, blocks: list[OcrBlock]) -> None:
    pixels = image.load()
    page_width, page_height = image.size
    for block in blocks:
        if not _is_doctor_attribution(block.text):
            continue
        x0, y0, x1, y1 = _rendered_bbox(block, page_width, page_height)
        line_height = y1 - y0
        left = max(0, int(x0 - 16))
        right = min(page_width, int(x1 + 16))
        top = max(0, int(y0 - 5 * line_height))
        bottom = min(page_height, int(y1 + 2 * line_height))
        for y_coordinate in range(top, bottom):
            for x_coordinate in range(left, right):
                red, green, blue = pixels[x_coordinate, y_coordinate]
                if blue > 100 and blue > red + 10 and blue > green + 5:
                    pixels[x_coordinate, y_coordinate] = (255, 255, 255)


def _is_doctor_attribution(text: str) -> bool:
    if re.search(r"\bврач", text, flags=re.IGNORECASE) is None:
        return False
    return re.search(
        r"\bврач\s*:\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}\b",
        text,
        flags=re.IGNORECASE,
    ) is None


def _doctor_signature_bbox(
    block: OcrBlock,
    page_width: int,
    page_height: int,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = _rendered_bbox(block, page_width, page_height)
    line_height = y1 - y0
    return (
        max(0, x0 - 16),
        max(0, y1 - 0.25 * line_height),
        min(page_width, x0 + max(100, 0.45 * (x1 - x0))),
        min(page_height, y1 + 2 * line_height),
    )


def _image_size(raw_bbox: object) -> tuple[float, float] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    _, _, width, height = raw_bbox
    if not all(isinstance(value, (int, float)) for value in (width, height)):
        return None
    if width <= 0 or height <= 0:
        return None
    return float(width), float(height)


def _rendered_bbox(
    block: OcrBlock,
    page_width: int,
    page_height: int,
) -> tuple[float, float, float, float]:
    """Translate Surya coordinates onto the rendered page used for reconstruction."""
    source_width, source_height = block.image_size or (page_width, page_height)
    x_scale = page_width / source_width
    y_scale = page_height / source_height
    x0, y0, x1, y1 = block.bbox
    return x0 * x_scale, y0 * y_scale, x1 * x_scale, y1 * y_scale


def _padded_bbox(
    block: OcrBlock,
    page_width: int,
    page_height: int,
    padding: float = 16,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = _rendered_bbox(block, page_width, page_height)
    return (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(page_width, x1 + padding),
        min(page_height, y1 + padding),
    )


def _signature_panel_blocks(blocks: list[OcrBlock]) -> set[int]:
    """Return the OCR blocks that belong to an electronic-signature panel."""
    headers = [
        block
        for block in blocks
        if "ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ" in block.text.upper()
    ]
    omitted: set[int] = set()
    for header in headers:
        header_x0, header_y0, _, header_y1 = header.bbox
        for block in blocks:
            x0, y0, _, y1 = block.bbox
            if (
                block.page_number == header.page_number
                and x0 >= header_x0 - 8
                and y0 >= header_y0 - 8
                and y1 <= header_y1 + 360
            ):
                omitted.add(id(block))
    return omitted


def _validate_export(path: Path, blocks: list[RedactedBlock]) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ProcessingError("The anonymized PDF could not be created.")
    sources = {change.source for block in blocks for change in block.changes}
    exported_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if any(source in exported_text for source in sources):
        raise ProcessingError("The anonymized PDF failed a text-layer validation.")


def _write_change_log(path: Path, blocks: list[RedactedBlock]) -> None:
    entries = [
        {
            "page": block.source.page_number,
            "bbox": block.source.bbox,
            "kind": change.kind,
            "source": change.source,
            "replacement": change.replacement,
        }
        for block in blocks
        for change in block.changes
    ]
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_object_from_output(output: str) -> str:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("JSON object not found", output, 0)
    return output[start : end + 1]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"br", "p", "tr", "li"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("\t")


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"[ \t]+", " ", "".join(parser.parts)).strip()
