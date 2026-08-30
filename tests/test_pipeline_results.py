import json
from datetime import date
from pathlib import Path

from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from medical_deid.pipeline import (
    _FONT_NAME,
    _FONT_PATH,
    OcrBlock,
    RedactedBlock,
    _erase_blue_signature_ink,
    _institution_contact_block_ids,
    _is_doctor_attribution,
    _is_institution_contact_block,
    _matching_birth_dates,
    _padded_bbox,
    _parse_surya_results,
    _regex_entities,
    _rendered_bbox,
    _sanitize_source_pixels,
    _should_omit_block,
    _signature_panel_blocks,
    _visible_text_layout,
    _with_age_replacement,
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


def test_electronic_signature_block_is_omitted_from_the_rebuilt_pdf() -> None:
    block = OcrBlock(
        page_number=1,
        bbox=(10, 10, 100, 100),
        text="ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ",
        label="SectionHeader",
    )

    assert _should_omit_block(block, page_width=1000, page_height=1000)


def test_electronic_signature_panel_keeps_the_separate_doctor_attribution() -> None:
    header = OcrBlock(1, (500, 100, 900, 130), "ДОКУМЕНТ ПОДПИСАН ЭЛЕКТРОННОЙ ПОДПИСЬЮ", "SectionHeader")
    certificate = OcrBlock(1, (500, 160, 900, 180), "Сертификат: ABC", "Text")
    doctor_attribution = OcrBlock(1, (500, 600, 900, 620), "Дежурный врач", "Text")

    omitted = _signature_panel_blocks([header, certificate, doctor_attribution])

    assert omitted == {id(header), id(certificate)}


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


def test_institution_contact_block_is_not_treated_as_patient_contact_data() -> None:
    assert _is_institution_contact_block(
        "ИНВИТРО СПБ ООО 8-800-200-363-0 Санкт-Петербург, ул. Бухарестская, д. 78"
    )


def test_contact_below_an_institution_header_is_not_patient_contact_data() -> None:
    header = OcrBlock(1, (10, 10, 100, 20), "ИНВИТРО СПБ ООО", "SectionHeader")
    contact = OcrBlock(1, (10, 22, 180, 40), "8-800-200-363-0 Санкт-Петербург", "Text")

    assert _institution_contact_block_ids([header, contact]) == {id(header), id(contact)}


def test_institution_contact_is_kept_when_header_columns_are_separate() -> None:
    institution = OcrBlock(1, (800, 85, 1400, 140), "Военно-медицинская академия", "SectionHeader")
    contact = OcrBlock(
        1,
        (380, 178, 1838, 247),
        "Санкт-Петербург, ул. Академика Лебедева, д. 6 Тел/факс: 8 (812) 292-32-63",
        "Text",
    )
    patient = OcrBlock(1, (70, 302, 1100, 368), "Пациент: ИГЛОВИКОВ НИКОЛАЙ ЮРЬЕВИЧ", "Text")

    omitted_as_patient_data = _institution_contact_block_ids([institution, contact, patient])

    assert id(contact) in omitted_as_patient_data
    assert id(patient) not in omitted_as_patient_data


def test_blue_signature_ink_is_removed_only_near_a_doctor_attribution() -> None:
    image = Image.new("RGB", (200, 200), "white")
    image.putpixel((30, 60), (10, 40, 200))
    image.putpixel((30, 170), (10, 40, 200))
    doctor = OcrBlock(1, (20, 100, 180, 120), "Врач: Иванов И.И.", "Text")

    _erase_blue_signature_ink(image, [doctor])

    assert image.getpixel((30, 60)) == (255, 255, 255)
    assert image.getpixel((30, 170)) == (10, 40, 200)


def test_date_field_named_doctor_is_not_treated_as_a_signature() -> None:
    assert not _is_doctor_attribution("Врач: 22.11.2023")
    assert _is_doctor_attribution("Врач: Иванов Иван Иванович")


def test_small_picture_mask_covers_barcode_caption_below_ocr_box(tmp_path: Path) -> None:
    source_path = tmp_path / "page.png"
    image = Image.new("RGB", (200, 200), "white")
    for y in range(40, 101):
        for x in range(80, 121):
            image.putpixel((x, y), (0, 0, 0))
    image.save(source_path)
    picture = OcrBlock(1, (80, 40, 120, 80), "", "Picture", image_size=(200, 200))

    [sanitized_path] = _sanitize_source_pixels(
        [source_path], {1: [RedactedBlock(picture, "", [])]}, tmp_path / "sanitized"
    )

    assert Image.open(sanitized_path).getpixel((100, 100)) == (255, 255, 255)
