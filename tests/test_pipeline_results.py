import json
from datetime import date
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from medical_deid.pipeline import (
    _FONT_NAME,
    _FONT_PATH,
    OcrBlock,
    RedactedBlock,
    _append_llama_threads,
    _code_related_to_box,
    _document_date,
    _filter_entities_for_block,
    _matching_birth_dates,
    _padded_bbox,
    _parse_surya_results,
    _recommended_cpu_threads,
    _regex_entities,
    _rendered_bbox,
    _sanitize_source_pixels,
    _visible_text_layout,
    _with_age_replacement,
    _write_searchable_pdf,
)
from medical_deid.redaction import EntityMatch, apply_replacements


def test_surya_result_with_multiple_pages_under_one_source_key(tmp_path: Path) -> None:
    result_path = tmp_path / "results.json"
    result_path.write_text(
        json.dumps(
            {
                "source": [
                    {"blocks": [{"bbox": [0, 0, 10, 10], "html": "first", "label": "Text"}]},
                    {"blocks": [{"bbox": [0, 0, 10, 10], "html": "second", "label": "Text"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    blocks = _parse_surya_results(result_path)

    assert [(block.page_number, block.text) for block in blocks] == [(1, "first"), (2, "second")]


def test_birth_date_replacement_consumes_a_written_existing_age() -> None:
    source = "Дата рождения: 22 сентября 1982 Возраст: 43 года"

    entities = _with_age_replacement(
        source,
        [EntityMatch(text="22 сентября 1982", kind="birth_date")],
        date(2025, 12, 3),
    )
    redacted, changes = apply_replacements(source, entities)

    assert redacted == "Возраст: 43 года"
    assert [change.source for change in changes] == [source]


def test_birth_date_replacement_consumes_a_parenthesized_existing_age() -> None:
    source = "Дата рождения: 28.08.1955 (71 год)"

    entities = _with_age_replacement(
        source,
        [EntityMatch(text="28.08.1955", kind="birth_date")],
        date(2026, 8, 26),
    )
    redacted, changes = apply_replacements(source, entities)

    assert redacted == "Возраст: 70 лет"
    assert [change.source for change in changes] == [source]


def test_existing_age_is_not_mistaken_for_a_date_of_birth() -> None:
    source = "Игловиков Николай Юрьевич (43 года) ВелоЭМ N356 от 11.11.2025"

    entities = _with_age_replacement(
        source,
        [EntityMatch(text="43 года", kind="birth_date")],
        date(2025, 11, 11),
    )

    assert entities == []


def test_signature_picture_is_preserved_when_no_code_is_detected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("medical_deid.pipeline._detect_code_boxes", lambda image: [])
    source_path = tmp_path / "page.png"
    image = Image.new("RGB", (200, 200), "white")
    image.putpixel((100, 60), (0, 0, 0))
    image.save(source_path)
    picture = OcrBlock(1, (80, 40, 120, 80), "", "Picture", image_size=(200, 200))

    [sanitized_path], omitted_blocks = _sanitize_source_pixels(
        [source_path], {1: [RedactedBlock(picture, "", [])]}, tmp_path / "sanitized"
    )

    assert Image.open(sanitized_path).getpixel((100, 60)) == (0, 0, 0)
    assert omitted_blocks == set()


def test_detected_code_masks_its_picture_and_caption(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "medical_deid.pipeline._detect_code_boxes", lambda image: [(80, 40, 120, 80)]
    )
    source_path = tmp_path / "page.png"
    image = Image.new("RGB", (200, 200), "white")
    image.putpixel((100, 60), (0, 0, 0))
    image.putpixel((100, 90), (0, 0, 0))
    image.save(source_path)
    picture = OcrBlock(1, (80, 40, 120, 80), "", "Picture", image_size=(200, 200))
    caption = OcrBlock(1, (80, 85, 120, 95), "123456", "Text", image_size=(200, 200))

    [sanitized_path], omitted_blocks = _sanitize_source_pixels(
        [source_path],
        {1: [RedactedBlock(picture, "", []), RedactedBlock(caption, "123456", [])]},
        tmp_path / "sanitized",
    )

    sanitized = Image.open(sanitized_path)
    assert sanitized.getpixel((100, 60)) == (255, 255, 255)
    assert sanitized.getpixel((100, 90)) == (255, 255, 255)
    assert omitted_blocks == {id(picture), id(caption)}


def test_detected_code_caption_is_not_added_to_searchable_pdf_layer(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "medical_deid.pipeline._detect_code_boxes", lambda image: [(80, 40, 120, 80)]
    )
    source_path = tmp_path / "page.png"
    image = Image.new("RGB", (200, 200), "white")
    image.save(source_path)
    picture = OcrBlock(1, (80, 40, 120, 80), "", "Picture", image_size=(200, 200))
    caption = OcrBlock(1, (80, 85, 120, 95), "123456", "Text", image_size=(200, 200))
    destination = tmp_path / "result.pdf"

    _write_searchable_pdf(
        destination,
        [source_path],
        [RedactedBlock(picture, "", []), RedactedBlock(caption, "123456", [])],
        tmp_path / "work",
    )

    assert "123456" not in (PdfReader(destination).pages[0].extract_text() or "")


def test_code_relation_uses_relative_block_geometry() -> None:
    code_box = (80, 40, 120, 80)
    caption = OcrBlock(1, (80, 85, 120, 95), "123456", "Text", image_size=(200, 200))
    unrelated = OcrBlock(1, (80, 130, 120, 140), "result", "Text", image_size=(200, 200))

    assert _code_related_to_box(caption, code_box, page_width=200, page_height=200)
    assert not _code_related_to_box(unrelated, code_box, page_width=200, page_height=200)


def test_visible_text_layout_fits_all_lines_in_a_short_block() -> None:
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_PATH)))
    font_size, lines = _visible_text_layout(
        "Распечатано 28.08.2026\nДежурный врач клиники\nИГЛОВИКОВ Н.Ю.",
        width=441,
        height=124,
    )

    assert font_size >= 11
    assert len(lines) == 3


def test_reconstruction_scales_ocr_coordinates_to_the_rendered_pdf_page() -> None:
    block = OcrBlock(
        page_number=1,
        bbox=(20, 40, 100, 120),
        text="patient",
        label="Text",
        image_size=(200, 200),
    )

    assert _rendered_bbox(block, page_width=100, page_height=100) == (10, 20, 50, 60)
    assert _padded_bbox(block, page_width=100, page_height=100) == (0, 4, 66, 76)


def test_date_of_birth_label_is_detected_without_an_llm_proposal() -> None:
    entities = _regex_entities("Пол: Мужской Дата рождения: 25.01.1956 Возраст: 70 лет")

    assert entities == [EntityMatch(text="Дата рождения: 25.01.1956", kind="birth_date")]


def test_inz_identifier_is_detected_as_insurance_id() -> None:
    assert _regex_entities("ИНЗ: 818093994") == [
        EntityMatch(text="ИНЗ: 818093994", kind="insurance_id")
    ]


def test_known_birth_date_is_detected_when_ocr_glues_it_to_a_name() -> None:
    entities = _matching_birth_dates(
        "Игловиков Николай Юрьевич22.09.1982 Печать: 03.12.2025",
        {date(1982, 9, 22)},
    )

    assert entities == [EntityMatch(text="22.09.1982", kind="birth_date")]


def test_public_institution_contact_is_not_a_regex_patient_entity() -> None:
    assert _regex_entities(
        "ИНВИТРО СПБ ООО 8-800-200-363-0 Санкт-Петербург, ул. Бухарестская, д. 78"
    ) == []


def test_labeled_patient_phone_is_detected_by_regex() -> None:
    assert _regex_entities("Телефон пациента: +7 999 123-45-67") == [
        EntityMatch(text="+7 999 123-45-67", kind="phone")
    ]


def test_contact_proposals_need_patient_context() -> None:
    institution_text = "ИНВИТРО СПБ ООО 8-800-200-363-0 Санкт-Петербург, ул. Бухарестская, д. 78"
    patient_text = "Адрес проживания: Санкт-Петербург, ул. Ленина, д. 1"

    assert _filter_entities_for_block(
        institution_text,
        [EntityMatch(text="8-800-200-363-0", kind="phone")],
    ) == []
    assert _filter_entities_for_block(
        patient_text,
        [EntityMatch(text="Санкт-Петербург, ул. Ленина, д. 1", kind="address")],
    ) == [EntityMatch(text="Санкт-Петербург, ул. Ленина, д. 1", kind="address")]


def test_document_date_prefers_a_clinical_label_over_print_date() -> None:
    assert _document_date("Печать: 03.12.2025 Дата забора: 17.11.2025") == date(2025, 11, 17)


def test_cpu_threads_use_the_m4_performance_core_cap(monkeypatch) -> None:
    monkeypatch.setattr("medical_deid.pipeline.os.cpu_count", lambda: 16)

    assert _recommended_cpu_threads() == 12


def test_llama_thread_arguments_preserve_explicit_environment_options() -> None:
    assert _append_llama_threads("--gpu-layers all --threads=8", 12) == (
        "--gpu-layers all --threads=8 --threads-batch 12"
    )
